"""Lee export_templates + hojas + columnas de FacturIA (PROCESS_SCHEMA)."""

from __future__ import annotations

from typing import Any, Dict, List

from facturia_matching.infra.config import PROCESS_SCHEMA, _mysql_table_ref, get_mysql_connection

TEMPLATES_TABLE = "export_templates"
SHEETS_TABLE = "export_template_sheets"
COLUMNS_TABLE = "export_template_columns"


class ExportTemplateNotFound(LookupError):
    """No hay template activo para ese id y cliente."""


def load_export_template(template_id: int, company_id: int) -> Dict[str, Any]:
    """Template activo (deleted_at nulo) del cliente, o company_id nulo (global).

    Raises ExportTemplateNotFound si no existe, está borrado o es de otro cliente.
    """
    templates_ref = _mysql_table_ref(PROCESS_SCHEMA, TEMPLATES_TABLE)
    sheets_ref = _mysql_table_ref(PROCESS_SCHEMA, SHEETS_TABLE)
    columns_ref = _mysql_table_ref(PROCESS_SCHEMA, COLUMNS_TABLE)
    conn = get_mysql_connection()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                f"""
                SELECT id, company_id, name, export_format
                FROM {templates_ref}
                WHERE id = %s AND deleted_at IS NULL
                """,
                (int(template_id),),
            )
            template = cur.fetchone()
            if not template:
                raise ExportTemplateNotFound(
                    f"No se encontró el template {template_id}."
                )
            owner = template.get("company_id")
            if owner is not None and int(owner) != int(company_id):
                raise ExportTemplateNotFound(
                    f"El template {template_id} no pertenece al cliente {company_id}."
                )

            cur.execute(
                f"""
                SELECT id, name, sort_order
                FROM {sheets_ref}
                WHERE template_id = %s
                ORDER BY sort_order, id
                """,
                (int(template_id),),
            )
            sheets = list(cur.fetchall() or [])
            sheet_ids = [int(s["id"]) for s in sheets if s.get("id") is not None]
            columns_by_sheet: Dict[int, List[Dict[str, Any]]] = {sid: [] for sid in sheet_ids}
            if sheet_ids:
                placeholders = ", ".join(["%s"] * len(sheet_ids))
                cur.execute(
                    f"""
                    SELECT id, sheet_id, header_label, source_type, source_value,
                           should_repeat, sort_order, lookup_suggest,
                           lookup_integration_id, lookup_sheet_title,
                           lookup_match_column, lookup_return_column
                    FROM {columns_ref}
                    WHERE sheet_id IN ({placeholders})
                    ORDER BY sort_order, id
                    """,
                    tuple(sheet_ids),
                )
                for col in cur.fetchall() or []:
                    sid = col.get("sheet_id")
                    if sid is None:
                        continue
                    columns_by_sheet.setdefault(int(sid), []).append(_column_dict(col))

            return {
                "id": int(template["id"]),
                "company_id": None if owner is None else int(owner),
                "name": str(template.get("name") or ""),
                "export_format": str(template.get("export_format") or ""),
                "sheets": [
                    {
                        "id": int(s["id"]),
                        "name": str(s.get("name") or ""),
                        "sort_order": s.get("sort_order"),
                        "columns": columns_by_sheet.get(int(s["id"]), []),
                    }
                    for s in sheets
                    if s.get("id") is not None
                ],
            }
        finally:
            cur.close()
    finally:
        conn.close()


def _column_dict(col: Dict[str, Any]) -> Dict[str, Any]:
    repeat = col.get("should_repeat")
    suggest = col.get("lookup_suggest")
    integ = col.get("lookup_integration_id")
    return {
        "id": col.get("id"),
        "header_label": str(col.get("header_label") or ""),
        "source_type": str(col.get("source_type") or "canonical"),
        "source_value": "" if col.get("source_value") is None else str(col.get("source_value")),
        "should_repeat": 1 if repeat is None else int(repeat),
        "sort_order": col.get("sort_order"),
        "lookup_suggest": 0 if suggest is None else int(suggest),
        "lookup_integration_id": None if integ is None else int(integ),
        "lookup_sheet_title": str(col.get("lookup_sheet_title") or ""),
        "lookup_match_column": str(col.get("lookup_match_column") or ""),
        "lookup_return_column": str(col.get("lookup_return_column") or ""),
    }
