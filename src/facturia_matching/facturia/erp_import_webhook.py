"""Notifica a FacturIA cuando el matching UI guardó comprobantes en Odoo.

FacturIA (CodeIgniter) expone:

- Staging: ``POST https://facturia-staging.sudata.co/api/erp-imports/webhook``
- Prod:    ``POST https://facturia.sudata.co/api/erp-imports/webhook``

Body JSON: ``import_id`` + ``token`` (callback_token de ``process_erp_imports``).
Opcional: ``status``, ``comprobantes_importados``, ``comprobantes_reportados``.

La UI recibe ``import_id`` / ``token`` en el deep-link del iframe (tras
``GET /api/process/{id}/erp-import/init`` en FacturIA).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import requests

from facturia_matching.infra.config import PROCESS_SCHEMA, resolve_process_schema
from facturia_matching.infra.env import env_strip

logger = logging.getLogger(__name__)

_DEFAULT_STAGING_BASE = "https://facturia-staging.sudata.co"
_DEFAULT_PROD_BASE = "https://facturia.sudata.co"
_WEBHOOK_PATH = "/api/erp-imports/webhook"


def resolve_facturia_base_url(process_schema: Optional[str] = None) -> str:
    """Base URL FacturIA según env o PROCESS_SCHEMA (staging vs prod)."""
    explicit = env_strip("FACTURIA_BASE_URL")
    if explicit:
        return explicit.rstrip("/")

    schema = resolve_process_schema(process_schema or PROCESS_SCHEMA)
    if "staging" in (schema or "").lower():
        return _DEFAULT_STAGING_BASE
    return _DEFAULT_PROD_BASE


def resolve_erp_import_webhook_url(process_schema: Optional[str] = None) -> str:
    """URL completa del webhook; override con FACTURIA_ERP_WEBHOOK_URL."""
    explicit = env_strip("FACTURIA_ERP_WEBHOOK_URL")
    if explicit:
        return explicit
    return f"{resolve_facturia_base_url(process_schema)}{_WEBHOOK_PATH}"


def _parse_import_id(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    text = str(raw).strip()
    if not text or not text.isdigit():
        return None
    value = int(text)
    return value if value > 0 else None


def extract_erp_import_callback(payload: Optional[Dict[str, Any]]) -> Tuple[Optional[int], str]:
    """Lee import_id + token desde body del import Odoo (o aliases)."""
    data = payload if isinstance(payload, dict) else {}
    import_id = None
    for key in ("import_id", "erp_import_id", "process_erp_import_id"):
        import_id = _parse_import_id(data.get(key))
        if import_id is not None:
            break
    token = ""
    for key in ("token", "callback_token", "erp_token", "erp_import_token"):
        raw = data.get(key)
        if raw is not None and str(raw).strip():
            token = str(raw).strip()
            break
    return import_id, token


def build_webhook_payload(
    *,
    import_id: int,
    token: str,
    import_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Arma el body del webhook a partir del resumen de ``import_rows_to_odoo``."""
    result = import_result if isinstance(import_result, dict) else {}
    created = result.get("created") or []
    updated = result.get("updated_taxes") or []
    errors = result.get("errors") or []
    imported = len(created) + len(updated)
    ok = bool(result.get("ok")) and imported > 0 and not errors
    if imported > 0 and errors:
        # Parcial: FacturIA igual marca completed con el conteo importado.
        status = "completed"
    elif ok or imported > 0:
        status = "completed"
    else:
        status = "failed"

    body: Dict[str, Any] = {
        "import_id": int(import_id),
        "token": token,
        "status": status,
        "comprobantes_importados": int(imported),
    }
    return body


def notify_erp_import_webhook(
    *,
    import_id: int,
    token: str,
    import_result: Optional[Dict[str, Any]] = None,
    process_schema: Optional[str] = None,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    """POST al webhook FacturIA. No lanza: el import Odoo no debe fallar por esto."""
    url = resolve_erp_import_webhook_url(process_schema)
    body = build_webhook_payload(
        import_id=import_id, token=token, import_result=import_result
    )
    try:
        resp = requests.post(
            url,
            json=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=timeout,
        )
        text = (resp.text or "")[:500]
        try:
            data = resp.json()
        except Exception:
            data = {"raw": text}
        ok = 200 <= resp.status_code < 300 and (
            not isinstance(data, dict) or data.get("status") is not False
        )
        out = {
            "ok": bool(ok),
            "http_status": resp.status_code,
            "url": url,
            "response": data,
        }
        if not ok:
            logger.warning(
                "FacturIA erp-imports webhook no OK: status=%s body=%s",
                resp.status_code,
                text,
            )
        return out
    except Exception as exc:
        logger.warning("FacturIA erp-imports webhook error: %s", exc)
        return {"ok": False, "url": url, "error": str(exc)}
