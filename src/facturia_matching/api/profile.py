"""Resolución de perfil Odoo por request y helpers de health público."""

from typing import Any, Dict, Optional

from facturia_matching.odoo.empresa_profile import resolve_odoo_profile_from_empresa
from facturia_matching.odoo.env import is_odoo_cloud_flag
from facturia_matching.odoo.request_context import odoo_profile_context

# No exponer uid Odoo en respuestas HTTP de health (dato interno de sesión XML-RPC).
_HEALTH_PRIVATE_KEYS = ("uid", "auth_uid", "uid_source")


def _public_health_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Copia de un dict de health sin campos de identidad Odoo."""
    return {k: v for k, v in data.items() if k not in _HEALTH_PRIVATE_KEYS}


def _coalesce_odoo_profile(
    perfil: Optional[str],
    odoo_profile_q: Optional[str],
) -> Optional[str]:
    return odoo_profile_q or perfil


def _resolve_request_odoo_profile(
    perfil: Optional[str] = None,
    odoo_profile_q: Optional[str] = None,
    odoo_cloud: Optional[Any] = None,
    payload: Optional[Dict[str, Any]] = None,
    empresa: Optional[Any] = None,
) -> Optional[str]:
    """odoo_cloud=1 → sudata; perfil explícito gana sobre ?empresa=N (PROCESS_SCHEMA)."""
    if payload:
        if is_odoo_cloud_flag(payload.get("odoo_cloud")):
            return "sudata"
        body_profile = payload.get("odoo_profile_test") or payload.get("perfil")
        if body_profile is not None and str(body_profile).strip() != "":
            return str(body_profile).strip()
        if empresa is None:
            empresa = payload.get("empresa")
    if is_odoo_cloud_flag(odoo_cloud):
        return "sudata"
    explicit = _coalesce_odoo_profile(perfil, odoo_profile_q)
    if explicit is not None and str(explicit).strip() != "":
        return str(explicit).strip()
    mapped = resolve_odoo_profile_from_empresa(empresa)
    if mapped:
        return mapped
    return None


def _with_odoo_profile(
    odoo_profile: Optional[str],
    fn,
    empresa: Optional[Any] = None,
):
    emp = str(empresa).strip() if empresa is not None and str(empresa).strip() != "" else None
    with odoo_profile_context(odoo_profile, empresa=emp):
        return fn()


def _payload_odoo_profile(payload: Optional[Dict[str, Any]]) -> Optional[str]:
    return _resolve_request_odoo_profile(payload=payload)
