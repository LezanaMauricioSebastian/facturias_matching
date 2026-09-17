"""Flags URL para modo padrón Excel en la UI principal (?excel_user=1, ?pepe=1, …)."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Union

# Aliases de cliente demo → override opcional de company_id del padrón Sheet.
# company_id None = usar el del proceso FacturIA (o 0).
EXCEL_USER_ALIASES: Dict[str, Dict[str, Any]] = {
    "pepe": {"company_id": 0},
}


def is_truthy_flag(raw: Optional[Any]) -> bool:
    """True si el valor es 1 / true / yes / on."""
    return str(raw or "").strip().lower() in ("1", "true", "yes", "on")


def _query_get(query_params: Optional[Mapping[str, Any]], key: str) -> Any:
    if not query_params:
        return None
    if hasattr(query_params, "getlist"):
        # Starlette QueryParams: primer valor
        try:
            return query_params.get(key)
        except Exception:
            return None
    return query_params.get(key)


def matched_excel_alias(
    query_params: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    """Nombre del alias activo (?pepe=1) o None."""
    if not query_params:
        return None
    for alias in EXCEL_USER_ALIASES:
        if is_truthy_flag(_query_get(query_params, alias)):
            return alias
    return None


def is_excel_user_request(
    excel_user: Optional[Any] = None,
    query_params: Optional[Mapping[str, Any]] = None,
    payload: Optional[Mapping[str, Any]] = None,
) -> bool:
    """True si excel_user=1 o un alias de cliente (?pepe=1)."""
    if is_truthy_flag(excel_user):
        return True
    if payload and is_truthy_flag(payload.get("excel_user")):
        return True
    if matched_excel_alias(query_params):
        return True
    if payload:
        for alias in EXCEL_USER_ALIASES:
            if is_truthy_flag(payload.get(alias)):
                return True
    return False


def resolve_excel_company_id(
    process_company_id: Optional[Union[int, str]] = None,
    query_params: Optional[Mapping[str, Any]] = None,
    payload: Optional[Mapping[str, Any]] = None,
) -> int:
    """
    company_id del padrón Sheet.
    Alias con company_id fijado gana; si no, el del proceso; default 0.
    """
    alias = matched_excel_alias(query_params)
    if alias is None and payload:
        for name in EXCEL_USER_ALIASES:
            if is_truthy_flag(payload.get(name)):
                alias = name
                break
    if alias is not None:
        cfg = EXCEL_USER_ALIASES.get(alias) or {}
        if cfg.get("company_id") is not None:
            try:
                return int(cfg["company_id"])
            except (TypeError, ValueError):
                pass

    if process_company_id is not None and str(process_company_id).strip() != "":
        try:
            return int(process_company_id)
        except (TypeError, ValueError):
            pass
    return 0
