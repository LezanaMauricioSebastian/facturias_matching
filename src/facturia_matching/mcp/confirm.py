"""Server-side confirmation gate: preview → token → import.

Confirmation tokens are HMAC-signed and portable across MCP instances (Cloud Run):
import re-fetches the proceso using metadata in the token. In-memory store still
speeds up same-instance confirm and best-effort single-use.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
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


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


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
    # FacturIA erp-imports (GET …/erp-import/init → webhook tras import)
    erp_import_id: Optional[int] = None
    erp_import_token: Optional[str] = None
    # True when rows were not loaded (portable token → caller must re-fetch)
    rows_pending_reload: bool = False


@dataclass
class ConfirmStore:
    """Preview cache + HMAC confirmation tokens (portable for remote MCP)."""

    secret: str = field(default_factory=lambda: os.environ.get("FACTURIA_MCP_SECRET") or secrets.token_hex(32))
    preview_ttl_sec: float = 30 * 60
    confirm_ttl_sec: float = 10 * 60
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _previews: Dict[str, PreviewRecord] = field(default_factory=dict, repr=False)
    _tokens: Dict[str, str] = field(default_factory=dict, repr=False)
    _used_jti: Dict[str, float] = field(default_factory=dict, repr=False)

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
        dead_jti = [j for j, exp in self._used_jti.items() if exp < now]
        for j in dead_jti:
            self._used_jti.pop(j, None)

    def _sign(self, body: bytes) -> str:
        return hmac.new(self.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    def _issue_portable_token(self, rec: PreviewRecord, *, now: float) -> str:
        jti = secrets.token_hex(8)
        payload = {
            "v": 1,
            "jti": jti,
            "preview_id": rec.preview_id,
            "process_number": rec.process_number,
            "empresa": rec.empresa,
            "odoo_profile": rec.odoo_profile,
            "fingerprint": rec.fingerprint,
            "erp_import_id": rec.erp_import_id,
            "erp_import_token": rec.erp_import_token,
            "exp": int(now + self.confirm_ttl_sec),
        }
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        token = f"v1.{_b64url_encode(body)}.{self._sign(body)}"
        return token

    def _parse_portable_token(self, token: str, *, now: float) -> PreviewRecord:
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != "v1":
            raise ConfirmationError(
                "confirmation_token inválido o ya usado. Pedí confirmación de nuevo."
            )
        _, body_b64, sig = parts
        try:
            body = _b64url_decode(body_b64)
        except Exception as exc:
            raise ConfirmationError("confirmation_token malformado.") from exc
        expected = self._sign(body)
        if not hmac.compare_digest(expected, sig):
            raise ConfirmationError("confirmation_token inválido (firma).")
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise ConfirmationError("confirmation_token malformado.") from exc
        if int(payload.get("exp") or 0) < int(now):
            raise ConfirmationError("La confirmación expiró. Confirmá el preview otra vez.")
        jti = str(payload.get("jti") or "")
        if jti and jti in self._used_jti:
            raise ConfirmationError(
                "confirmation_token inválido o ya usado. Pedí confirmación de nuevo."
            )
        if jti:
            self._used_jti[jti] = float(payload.get("exp") or now)
        return PreviewRecord(
            preview_id=str(payload.get("preview_id") or ""),
            process_number=str(payload.get("process_number") or ""),
            empresa=payload.get("empresa"),
            odoo_profile=str(payload.get("odoo_profile") or "default"),
            rows=[],
            fingerprint=str(payload.get("fingerprint") or ""),
            summary={},
            created_at=now,
            erp_import_id=payload.get("erp_import_id"),
            erp_import_token=payload.get("erp_import_token"),
            rows_pending_reload=True,
        )

    def create_preview(
        self,
        *,
        process_number: str,
        rows: list,
        summary: Dict[str, Any],
        empresa: Optional[str] = None,
        odoo_profile: str = "default",
        erp_import_id: Optional[int] = None,
        erp_import_token: Optional[str] = None,
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
                erp_import_id=erp_import_id,
                erp_import_token=(erp_import_token or None),
            )
            self._previews[preview_id] = rec
            return rec

    def attach_erp_callback(
        self,
        preview_id: str,
        *,
        import_id: int,
        token: str,
    ) -> PreviewRecord:
        with self._lock:
            rec = self._previews.get(preview_id)
            if not rec:
                raise ConfirmationError(
                    "preview_id inválido o expirado. Volvé a preview_invoice_match."
                )
            rec.erp_import_id = int(import_id)
            rec.erp_import_token = str(token).strip()
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
                raise ConfirmationError(
                    "El preview expiró. Generá uno nuevo y pedí confirmación otra vez."
                )
            if rec.confirmation_token:
                self._tokens.pop(rec.confirmation_token, None)
            token = self._issue_portable_token(rec, now=now)
            rec.confirmation_token = token
            rec.confirmed_at = now
            self._tokens[token] = preview_id
            return token

    def consume_for_import(self, confirmation_token: str) -> PreviewRecord:
        """Validate token and return the bound preview (single-use best-effort)."""
        now = time.time()
        with self._lock:
            if not confirmation_token or not str(confirmation_token).strip():
                raise ConfirmationError(
                    "Falta confirmation_token. Primero preview_invoice_match, "
                    "mostrá el resumen al contador, confirm_invoice_preview, y recién importá."
                )
            token = str(confirmation_token).strip()

            # Same-instance path: keep rows without re-fetch.
            preview_id = self._tokens.get(token)
            if preview_id:
                rec = self._previews.get(preview_id)
                if rec and rec.confirmation_token == token:
                    if rec.confirmed_at is None or now - rec.confirmed_at > self.confirm_ttl_sec:
                        self._tokens.pop(token, None)
                        rec.confirmation_token = None
                        rec.confirmed_at = None
                        raise ConfirmationError(
                            "La confirmación expiró. Confirmá el preview otra vez."
                        )
                    self._tokens.pop(token, None)
                    rec.confirmation_token = None
                    rec.confirmed_at = None
                    # Mark jti used if portable
                    if token.startswith("v1."):
                        try:
                            body = _b64url_decode(token.split(".")[1])
                            payload = json.loads(body.decode("utf-8"))
                            jti = str(payload.get("jti") or "")
                            if jti:
                                self._used_jti[jti] = float(payload.get("exp") or now)
                        except Exception:
                            pass
                    return rec

            # Cross-instance / after restart: portable HMAC token.
            if token.startswith("v1."):
                return self._parse_portable_token(token, now=now)

            self._purge_locked(now)
            raise ConfirmationError(
                "confirmation_token inválido o ya usado. Pedí confirmación de nuevo."
            )

    def invalidate_preview(self, preview_id: str) -> None:
        with self._lock:
            rec = self._previews.pop(preview_id, None)
            if rec and rec.confirmation_token:
                self._tokens.pop(rec.confirmation_token, None)
