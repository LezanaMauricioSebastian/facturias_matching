"""Helpers compartidos del matching OC / UM (sin deps internas del paquete)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from facturia_matching.odoo.api import get_active_odoo_config, is_odoo_config_ready


def _pkg():
    """Paquete `purchase_matching` (lazy): permite que `@patch` en el root siga funcionando."""
    from facturia_matching.odoo import purchase_matching as pm

    return pm


def _purchase_odoo_config() -> Dict[str, Any]:
    """Tenant Odoo para OC: misma instancia que import (Dinner o Aliare según perfil)."""
    return get_active_odoo_config()


def is_purchase_odoo_configured() -> bool:
    return is_odoo_config_ready(_purchase_odoo_config())


def _normalize(s: Any) -> str:
    if s is None:
        return ""
    return " ".join(str(s).strip().split())


def _normalize_key(s: Any) -> str:
    return _normalize(s).upper()


def _parse_amount(raw: Any) -> Optional[float]:
    s = _normalize(raw)
    if not s or s.lower() in {"nan", "none", "null"}:
        return None
    from facturia_matching.core.amounts import parse_amount_loose

    return parse_amount_loose(s)



def _tenant_cache_key() -> str:
    cfg = _purchase_odoo_config()
    return f"{cfg.get('base_url', '')}|{cfg.get('db', '')}"


def _is_content_row(row: Dict[str, Any]) -> bool:
    if row.get("__solo_encabezado"):
        return False
    desc = _normalize(row.get("invoice_line_ids/name"))
    qty = _parse_amount(row.get("invoice_line_ids/quantity"))
    return bool(desc or qty is not None)

