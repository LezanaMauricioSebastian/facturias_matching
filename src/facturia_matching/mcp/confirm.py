"""Server-side confirmation gate: preview → token → import."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class ConfirmationError(ValueError):
    """Invalid or expired preview / confirmation token."""


def _payload_fingerprint(rows: list, process_number: str) -> str:
    raw = repr((str(process_number), rows)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass
class PreviewRecord:
    preview_id: str
    process_number: str
    empresa: Optional[str]
    odoo_profile: str
    rows: list
    fingerprint: str
    summary: Dict[str, Any]
    created_at: float
    confirmation_token: Optional[str] = None
    confirmed_at: Optional[float] = None


@dataclass
class ConfirmStore:
    """In-memory preview + confirmation tokens (one MCP process / session)."""

    secret: str = field(default_factory=lambda: os.environ.get("FACTURIA_MCP_SECRET") or secrets.token_hex(32))
    preview_ttl_sec: float = 30 * 60
    confirm_ttl_sec: float = 10 * 60
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _previews: Dict[str, PreviewRecord] = field(default_factory=dict, repr=False)
    _tokens: Dict[str, str] = field(default_factory=dict, repr=False)

    def _purge_locked(self, now: float) -> None:
        expired = [
            pid
            for pid, rec in self._previews.items()
            if now - rec.created_at > self.preview_ttl_sec
            or (
                rec.confirmed_at is not None
                and now - rec.confirmed_at > self.confirm_ttl_sec
            )
        ]
        for pid in expired:
            rec = self._previews.pop(pid, None)
            if rec and rec.confirmation_token:
                self._tokens.pop(rec.confirmation_token, None)

    def create_preview(
        self,
        *,
        process_number: str,
        rows: list,
        summary: Dict[str, Any],
        empresa: Optional[str] = None,
        odoo_profile: str = "default",
    ) -> PreviewRecord:
        now = time.time()
        with self._lock:
            self._purge_locked(now)
            preview_id = str(uuid.uuid4())
            rec = PreviewRecord(
                preview_id=preview_id,
                process_number=str(process_number),
                empresa=empresa,
                odoo_profile=odoo_profile or "default",
                rows=list(rows),
                fingerprint=_payload_fingerprint(rows, process_number),
                summary=dict(summary),
                created_at=now,
            )
            self._previews[preview_id] = rec
            return rec

    def get_preview(self, preview_id: str) -> PreviewRecord:
        now = time.time()
        with self._lock:
            self._purge_locked(now)
            rec = self._previews.get(preview_id)
            if not rec:
                raise ConfirmationError(
                    "preview_id inválido o expirado. Volvé a llamar preview_invoice_match."
                )
            if now - rec.created_at > self.preview_ttl_sec:
                raise ConfirmationError("El preview expiró. Generá uno nuevo.")
            return rec

    def confirm(self, preview_id: str) -> str:
        """User said the preview looks correct → issue short-lived confirmation token."""
        now = time.time()
        with self._lock:
            self._purge_locked(now)
            rec = self._previews.get(preview_id)
            if not rec:
                raise ConfirmationError(
                    "preview_id inválido o expirado. Volvé a preview_invoice_match."
                )
            if now - rec.created_at > self.preview_ttl_sec:
                raise ConfirmationError("El preview expiró. Generá uno nuevo y pedí confirmación otra vez.")
            if rec.confirmation_token:
                self._tokens.pop(rec.confirmation_token, None)
            token = hmac.new(
                self.secret.encode("utf-8"),
                f"{preview_id}:{rec.fingerprint}:{secrets.token_hex(8)}".encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            rec.confirmation_token = token
            rec.confirmed_at = now
            self._tokens[token] = preview_id
            return token

    def consume_for_import(self, confirmation_token: str) -> PreviewRecord:
        """Validate token and return the bound preview (single-use)."""
        now = time.time()
        with self._lock:
            if not confirmation_token or not str(confirmation_token).strip():
                raise ConfirmationError(
                    "Falta confirmation_token. Primero preview_invoice_match, "
                    "mostrá el resumen al contador, confirm_invoice_preview, y recién importá."
                )
            # Resolve token before purge so expiry can be reported distinctly.
            preview_id = self._tokens.get(confirmation_token)
            if preview_id:
                rec = self._previews.get(preview_id)
                if rec and rec.confirmation_token == confirmation_token:
                    if rec.confirmed_at is None or now - rec.confirmed_at > self.confirm_ttl_sec:
                        self._tokens.pop(confirmation_token, None)
                        rec.confirmation_token = None
                        rec.confirmed_at = None
                        raise ConfirmationError(
                            "La confirmación expiró. Confirmá el preview otra vez."
                        )
                    self._tokens.pop(confirmation_token, None)
                    rec.confirmation_token = None
                    rec.confirmed_at = None
                    return rec
            self._purge_locked(now)
            raise ConfirmationError(
                "confirmation_token inválido o ya usado. Pedí confirmación de nuevo."
            )

    def invalidate_preview(self, preview_id: str) -> None:
        with self._lock:
            rec = self._previews.pop(preview_id, None)
            if rec and rec.confirmation_token:
                self._tokens.pop(rec.confirmation_token, None)
