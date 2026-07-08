"""Parsing, IDs, and Odoo move-line field helpers."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional

from facturia_matching.odoo.api import odoo_execute_kw_with_config

_DATE_DD_MM = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")

_MOVE_LINE_PURCHASE_LINK_CACHE: Dict[str, bool] = {}


def _odoo_config_cache_key(config: Dict[str, Any]) -> str:
    return f"{config.get('base_url', '')}|{config.get('db', '')}"


def _move_line_supports_purchase_link(config: Dict[str, Any]) -> bool:
    """False si account.move.line no tiene purchase_line_id (ej. Odoo Cloud Sudata sin purchase)."""
    key = _odoo_config_cache_key(config)
    if key in _MOVE_LINE_PURCHASE_LINK_CACHE:
        return _MOVE_LINE_PURCHASE_LINK_CACHE[key]
    supported = False
    try:
        fg = odoo_execute_kw_with_config(
            config,
            "account.move.line",
            "fields_get",
            [],
            {"attributes": []},
        )
        supported = isinstance(fg, dict) and "purchase_line_id" in fg
    except Exception:
        supported = False
    _MOVE_LINE_PURCHASE_LINK_CACHE[key] = supported
    return supported


def _move_product_line_fields(config: Dict[str, Any]) -> List[str]:
    fields = ["id", "name", "sequence", "tax_ids"]
    if _move_line_supports_purchase_link(config):
        fields.append("purchase_line_id")
    fields.extend(["product_id", "quantity", "price_unit", "account_id"])
    return fields


def _normalize(s: Any) -> str:
    if s is None:
        return ""
    return " ".join(str(s).strip().split())


def _int_id(raw: Any) -> Optional[int]:
    s = _normalize(raw)
    if not s or not s.isdigit():
        return None
    return int(s)


def _m2o_id(raw: Any) -> Optional[int]:
    if isinstance(raw, (list, tuple)) and raw:
        try:
            return int(raw[0])
        except (TypeError, ValueError):
            return None
    if isinstance(raw, int):
        return raw
    return _int_id(raw)


def _floats_differ(left: float, right: float, tolerance: float = 0.001) -> bool:
    return abs(float(left) - float(right)) > tolerance


def _parse_amount_loose(raw: Any) -> Optional[float]:
    s = _normalize(raw)
    if not s or s.lower() == "nan":
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts) >= 2 and all(p.isdigit() and len(p) == 3 for p in parts[1:]):
            s = "".join(parts)
    try:
        return float(s)
    except ValueError:
        return None


def _date_ddmm_to_iso(raw: Any) -> Optional[str]:
    s = _normalize(raw)
    if not s:
        return None
    s = s.replace("-", "/")
    m = _DATE_DD_MM.match(s)
    if not m:
        if re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", s):
            return s
        return None
    dd, mm, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        d = date(yyyy, mm, dd)
    except ValueError:
        return None
    return d.isoformat()


def _line_has_content(row: Dict[str, Any]) -> bool:
    return bool(
        _normalize(row.get("invoice_line_ids/name"))
        or _parse_amount_loose(row.get("invoice_line_ids/price_unit")) is not None
        or _parse_amount_loose(row.get("invoice_line_ids/quantity")) is not None
    )


def _content_rows_from_group(group: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in group if _line_has_content(r)]


def _first_content_row_index(group: List[Dict[str, Any]]) -> Optional[int]:
    for i, row in enumerate(group):
        if _line_has_content(row):
            return i
    return None


def _is_first_content_row(row: Dict[str, Any], group: List[Dict[str, Any]]) -> bool:
    idx = _first_content_row_index(group)
    if idx is None:
        return False
    return group[idx] is row
