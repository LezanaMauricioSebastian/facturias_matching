"""Padrón desde últimas facturas de compra publicadas en Odoo (equiv. view_padron_facturia)."""

from typing import Any, Dict, List, Optional, Tuple

from facturia_matching.infra.config import PADRON_ODOO_LIMIT
from facturia_matching.odoo.api import is_odoo_config_ready, odoo_execute_kw, odoo_search_read
from facturia_matching.odoo.env import current_odoo_profile, get_odoo_main_config, supports_rubro_field

MOVE_FIELDS_BASE = [
    "id",
    "name",
    "partner_id",
    "journal_id",
    "invoice_date",
    "invoice_line_ids",
    "l10n_latam_document_type_id",
]

RUBRO_FIELD_CANDIDATES = ("x_studio_category", "x_rubro_id", "category_id")

_PADRON_ODOO_CACHE_BY_PROFILE: Dict[str, List[Dict[str, Any]]] = {}


def reset_padron_odoo_cache() -> None:
    global _PADRON_ODOO_CACHE_BY_PROFILE
    _PADRON_ODOO_CACHE_BY_PROFILE = {}


def _m2o_id(val: Any) -> Optional[int]:
    if isinstance(val, (list, tuple)) and val:
        try:
            return int(val[0])
        except (TypeError, ValueError):
            return None
    if isinstance(val, int):
        return val
    if isinstance(val, str) and val.isdigit():
        return int(val)
    return None


def _m2o_label(val: Any) -> str:
    if isinstance(val, (list, tuple)) and len(val) > 1:
        return str(val[1] or "").strip()
    return ""


def resolve_move_fields() -> Tuple[List[str], Optional[str]]:
    try:
        fg = odoo_execute_kw("account.move", "fields_get", [], {"attributes": ["type"]})
        names = set(fg.keys()) if isinstance(fg, dict) else set()
    except Exception:
        names = set(MOVE_FIELDS_BASE)

    fields = list(MOVE_FIELDS_BASE)
    rubro_field: Optional[str] = None
    for candidate in RUBRO_FIELD_CANDIDATES:
        if candidate in names:
            fields.append(candidate)
            rubro_field = candidate
            break
    return fields, rubro_field


def _fetch_posted_vendor_bills(limit: int) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    fields, rubro_field = resolve_move_fields()
    rows = odoo_search_read(
        "account.move",
        [("move_type", "=", "in_invoice"), ("state", "=", "posted")],
        fields,
        limit=limit,
        order="invoice_date desc, id desc",
    )
    return rows, rubro_field


def _pick_latest_per_partner(moves: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[int, Dict[str, Any]] = {}
    for move in moves:
        partner_id = _m2o_id(move.get("partner_id"))
        if partner_id is None:
            continue
        if partner_id not in seen:
            seen[partner_id] = move
    return list(seen.values())


def _fetch_partners(partner_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not partner_ids:
        return {}
    rows = odoo_search_read(
        "res.partner",
        [("id", "in", partner_ids)],
        ["id", "name", "vat"],
        limit=len(partner_ids) + 10,
    )
    return {int(r["id"]): r for r in rows if r.get("id") is not None}


def _fetch_first_line_account_by_move(move_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not move_ids:
        return {}
    lines = odoo_search_read(
        "account.move.line",
        [("move_id", "in", move_ids), ("display_type", "not in", ["line_section", "line_note"])],
        ["id", "move_id", "account_id"],
        limit=max(len(move_ids) * 20, 500),
        order="move_id, id",
    )
    out: Dict[int, Dict[str, Any]] = {}
    for line in lines:
        move_id = _m2o_id(line.get("move_id"))
        if move_id is None or move_id in out:
            continue
        account_id = _m2o_id(line.get("account_id"))
        if account_id is None:
            continue
        out[move_id] = {
            "account_id": account_id,
            "account_name": _m2o_label(line.get("account_id")),
        }
    account_ids = sorted({v["account_id"] for v in out.values()})
    if not account_ids:
        return out
    accounts = odoo_search_read(
        "account.account",
        [("id", "in", account_ids)],
        ["id", "name", "code", "display_name"],
        limit=len(account_ids) + 10,
    )
    acc_by_id = {int(a["id"]): a for a in accounts if a.get("id") is not None}
    for move_id, row in out.items():
        acc = acc_by_id.get(row["account_id"]) or {}
        code = str(acc.get("code") or "").strip()
        name = str(acc.get("name") or row.get("account_name") or "").strip()
        display = str(acc.get("display_name") or "").strip()
        if not display and code and name:
            display = f"{code} {name}".strip()
        row["cuenta_contable_completo"] = display or name
    return out


def _fetch_rubro_names(category_values: List[Any]) -> Dict[str, str]:
    ids: List[int] = []
    for val in category_values:
        mid = _m2o_id(val)
        if mid is not None:
            ids.append(mid)
        elif isinstance(val, str) and val.isdigit():
            ids.append(int(val))
    if not ids:
        return {}
    rows = odoo_search_read(
        "x_rubros",
        [("id", "in", sorted(set(ids)))],
        ["id", "x_name", "name"],
        limit=len(ids) + 10,
    )
    out: Dict[str, str] = {}
    for r in rows:
        rid = r.get("id")
        if rid is None:
            continue
        label = str(r.get("x_name") or r.get("name") or "").strip()
        out[str(rid)] = label
    return out


def build_padron_rows_from_odoo(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Una fila por proveedor: última factura de compra publicada."""
    if not is_odoo_config_ready(get_odoo_main_config(current_odoo_profile())):
        return []

    lim = limit if limit is not None else PADRON_ODOO_LIMIT
    moves, rubro_field = _fetch_posted_vendor_bills(lim)
    latest = _pick_latest_per_partner(moves)
    partner_ids = [p for p in (_m2o_id(m.get("partner_id")) for m in latest) if p is not None]

    partners = _fetch_partners(partner_ids)
    move_ids = [int(m["id"]) for m in latest if m.get("id") is not None]
    accounts_by_move = _fetch_first_line_account_by_move(move_ids)

    category_vals = [m.get(rubro_field) for m in latest if rubro_field and m.get(rubro_field)]
    rubro_names = _fetch_rubro_names(category_vals) if supports_rubro_field() else {}

    rows: List[Dict[str, Any]] = []
    for move in latest:
        move_id = int(move["id"])
        partner_id = _m2o_id(move.get("partner_id"))
        partner = partners.get(partner_id or -1, {})
        acc = accounts_by_move.get(move_id, {})

        rubro = ""
        if supports_rubro_field():
            cat = move.get(rubro_field) if rubro_field else None
            cat_key = str(_m2o_id(cat) or cat or "")
            rubro = _m2o_label(cat) or rubro_names.get(cat_key, "")

        nombre = str(partner.get("name") or _m2o_label(move.get("partner_id")) or "").strip()
        doc = str(partner.get("vat") or "").strip()
        cuenta = acc.get("cuenta_contable_completo") or ""
        rows.append(
            {
                "name": nombre,
                "doc": doc,
                "rubro": rubro,
                "diario": _m2o_label(move.get("journal_id")),
                "cuenta": cuenta,
            }
        )
    return rows


def get_padron_odoo_cached() -> List[Dict[str, Any]]:
    from facturia_matching.odoo.env import current_odoo_profile

    profile = current_odoo_profile()
    cached = _PADRON_ODOO_CACHE_BY_PROFILE.get(profile)
    if cached is not None:
        return cached
    try:
        rows = build_padron_rows_from_odoo()
    except Exception:
        rows = []
    _PADRON_ODOO_CACHE_BY_PROFILE[profile] = rows
    return rows
