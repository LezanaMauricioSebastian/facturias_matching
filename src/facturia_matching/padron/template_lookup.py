"""Sugerencia de columnas con tilde lookup_suggest contra el Sheet de la integración."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from facturia_matching.infra.config import PROCESS_SCHEMA, _mysql_table_ref, get_mysql_connection

logger = logging.getLogger(__name__)

INTEGRATIONS_TABLE = "company_google_sheets_integrations"
_CUIT_MATCH_COLS = {"cuit", "cuil", "dni", "documento"}

LookupKey = Tuple[int, str, str, str]
LookupIndex = Dict[LookupKey, Dict[str, Any]]


def resolved_return_column(col: Dict[str, Any]) -> str:
    """Retorno explícito, o la columna de match si la segunda viene vacía."""
    explicit = str(col.get("lookup_return_column") or "").strip()
    if explicit:
        return explicit
    return str(col.get("lookup_match_column") or "").strip()


def lookup_key(col: Dict[str, Any]) -> Optional[LookupKey]:
    """Clave del índice de la lista (haya o no tilde de sugerencia)."""
    integ = col.get("lookup_integration_id")
    sheet = str(col.get("lookup_sheet_title") or "").strip()
    match_col = str(col.get("lookup_match_column") or "").strip()
    return_col = resolved_return_column(col)
    if integ is None or not sheet or not match_col or not return_col:
        return None
    return (int(integ), sheet.casefold(), match_col.casefold(), return_col.casefold())


def suggest_enabled(col: Dict[str, Any]) -> bool:
    """Tilde de sugerencia: llenar con matching + historial Gastos + IA."""
    try:
        return int(col.get("lookup_suggest") or 0) != 0
    except (TypeError, ValueError):
        return False


def column_role(col: Dict[str, Any]) -> str:
    """Qué pieza del matching Excel llena esta columna, si corresponde."""
    parts = (
        col.get("header_label"),
        col.get("lookup_match_column"),
        col.get("lookup_return_column"),
        col.get("source_value"),
    )
    blob = " ".join(str(p or "") for p in parts).casefold()
    for src, dst in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
        blob = blob.replace(src, dst)
    if "categoria" in blob:
        return "categoria"
    if "concepto" in blob:
        return "concepto"
    if "forma de pago" in blob or "formapago" in blob:
        return "forma_pago"
    if "proveedor" in blob or "razon social" in blob:
        return "proveedor"
    return ""


def pipeline_suggestion(
    col: Dict[str, Any],
    header_excel: Optional[Dict[str, Any]],
    line_excel: Optional[Dict[str, Any]],
) -> str:
    """Valor ya matcheado (proveedor / concepto / categoría / forma de pago)."""
    role = column_role(col)
    field = {
        "proveedor": "__excel_proveedor",
        "concepto": "__excel_concepto",
        "categoria": "__excel_categoria",
        "forma_pago": "__excel_forma_pago",
    }.get(role)
    if not field:
        return ""
    source = header_excel if role in ("proveedor", "forma_pago") else line_excel
    hit = str((source or {}).get(field) or "").strip()
    if hit:
        return hit
    return str((header_excel or {}).get(field) or "").strip()


def suggest_for(col: Dict[str, Any], raw_key: str, index: Optional[LookupIndex]) -> str:
    """Valor de la columna de retorno si el origen matchea. Vacío si no hay hit."""
    key = lookup_key(col)
    if key is None or not index:
        return ""
    table = index.get(key) or {}
    by_key = table.get("by_key") or {}
    norm = normalize_match_key(raw_key, str(col.get("lookup_match_column") or ""))
    if not norm:
        return ""
    return str(by_key.get(norm) or "")


def options_for(col: Dict[str, Any], index: Optional[LookupIndex]) -> List[str]:
    key = lookup_key(col)
    if key is None or not index:
        return []
    return list((index.get(key) or {}).get("options") or [])


def normalize_match_key(raw: Any, match_column: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if str(match_column or "").strip().casefold() in _CUIT_MATCH_COLS:
        return "".join(ch for ch in s if ch.isdigit())
    return s.casefold()


def build_lookup_index(template: Dict[str, Any]) -> LookupIndex:
    """Lee las hojas de las integraciones marcadas en las columnas del template."""
    columns: List[Dict[str, Any]] = []
    for sheet in template.get("sheets") or []:
        columns.extend(sheet.get("columns") or [])
    wanted = [c for c in columns if lookup_key(c)]
    if not wanted:
        return {}
    integ_ids = {int(c["lookup_integration_id"]) for c in wanted}
    integrations = _load_integrations(integ_ids)
    index: LookupIndex = {}
    for col in wanted:
        key = lookup_key(col)
        if key is None or key in index:
            continue
        integ = integrations.get(key[0])
        if not integ:
            continue
        try:
            index[key] = _index_sheet(integ, col)
        except Exception as e:
            logger.warning(
                "lookup sheet failed integration=%s sheet=%s: %s",
                key[0],
                col.get("lookup_sheet_title"),
                e,
            )
            index[key] = {"by_key": {}, "options": []}
    return index


def _load_integrations(ids: Sequence[int]) -> Dict[int, Dict[str, Any]]:
    if not ids:
        return {}
    table = _mysql_table_ref(PROCESS_SCHEMA, INTEGRATIONS_TABLE)
    placeholders = ", ".join(["%s"] * len(ids))
    conn = get_mysql_connection()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                f"""
                SELECT id, spreadsheet_id, sheet_title, sheet_gid, is_active, deleted_at
                FROM {table}
                WHERE id IN ({placeholders})
                """,
                tuple(int(i) for i in ids),
            )
            out: Dict[int, Dict[str, Any]] = {}
            for row in cur.fetchall() or []:
                if row.get("deleted_at") is not None:
                    continue
                if row.get("is_active") is not None and int(row.get("is_active") or 0) == 0:
                    continue
                out[int(row["id"])] = row
            return out
        finally:
            cur.close()
    finally:
        conn.close()


def _index_sheet(integ: Dict[str, Any], col: Dict[str, Any]) -> Dict[str, Any]:
    from facturia_matching.padron.google_sheets import (
        list_spreadsheet_sheets,
        service_account_configured,
    )
    from facturia_matching.padron.sheet_loader import fetch_sheet

    sid = str(integ.get("spreadsheet_id") or "").strip()
    if not sid:
        return {"by_key": {}, "options": []}
    title = str(col.get("lookup_sheet_title") or integ.get("sheet_title") or "").strip()
    gid = str(integ.get("sheet_gid") or "").strip()
    integ_title = str(integ.get("sheet_title") or "").strip()
    if service_account_configured() and title and (not gid or integ_title.casefold() != title.casefold()):
        meta = list_spreadsheet_sheets(sid)
        match = next(
            (s for s in meta.get("sheets") or [] if str(s.get("title") or "").casefold() == title.casefold()),
            None,
        )
        if match:
            gid = str(match.get("gid") or "")
    rows = fetch_sheet(spreadsheet_id=sid, gid=gid or None, force=False)
    match_name = _header_name(rows, str(col.get("lookup_match_column") or ""))
    return_name = _header_name(rows, resolved_return_column(col))
    match_label = str(col.get("lookup_match_column") or "")
    by_key: Dict[str, str] = {}
    options: List[str] = []
    seen_opt = set()
    if not match_name or not return_name:
        return {"by_key": by_key, "options": options}
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_key = row.get(match_name)
        raw_val = str(row.get(return_name) or "").strip()
        norm = normalize_match_key(raw_key, match_label)
        if norm and raw_val and norm not in by_key:
            by_key[norm] = raw_val
        opt_key = raw_val.casefold()
        if raw_val and opt_key not in seen_opt:
            seen_opt.add(opt_key)
            options.append(raw_val)
    return {"by_key": by_key, "options": options}


def _header_name(rows: Sequence[Dict[str, Any]], wanted: str) -> str:
    target = str(wanted or "").strip().casefold()
    if not target or not rows:
        return ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in row.keys():
            if key is None:
                continue
            if str(key).strip().casefold() == target:
                return str(key)
        break
    return ""
