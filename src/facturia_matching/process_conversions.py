"""Persist edited rows in MySQL process_conversions (Odoo template 99)."""

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from facturia_matching.back_check import PROCESS_SCHEMA, get_process
from facturia_matching.config import _mysql_table_ref, get_mysql_connection
from facturia_matching.odoo_env import current_odoo_profile, get_conversion_template_id

CONVERSIONS_TABLE = "process_conversions"
# Compat tests / referencias históricas (perfil default / Dinner).
ODOO_TEMPLATE_ID = 99
CONVERSION_FORMAT = "odoo_matching_ui"
CONVERSION_VERSION = 1

_OTRO_IMPUESTO_N_RE = re.compile(r"^otros_impuestos_(\d+)$")
_OTRO_IMPUESTO_MONTO_N_RE = re.compile(r"^otros_impuestos_(\d+)_monto$")


class ProcessConversionError(RuntimeError):
    """Invalid process row or conversion payload for persistence."""


def resolve_process_row(
    process_number: Any,
    empresa: Optional[Any] = None,
) -> Dict[str, Any]:
    """Resolve process_number (+ optional empresa) to id, company_id, user_id."""
    row = get_process(process_number, empresa=empresa)
    if not row:
        raise ProcessConversionError(f"No se encontró el proceso {process_number}.")
    process_id = row.get("id")
    if not process_id:
        raise ProcessConversionError("El proceso no tiene id interno.")
    company_id = row.get("company_id")
    if company_id is None or str(company_id).strip() == "":
        raise ProcessConversionError(
            "El proceso no tiene company_id; no se puede guardar la conversión."
        )
    return {
        "id": int(process_id),
        "company_id": int(company_id),
        "user_id": row.get("user_id"),
        "process_number": row.get("process_number"),
    }


def infer_otro_impuesto_indices(rows: List[Dict[str, Any]]) -> List[int]:
    """Return sorted N values for otros_impuestos_N columns present in rows."""
    indices: set[int] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for key in row:
            if key == "otros_impuestos":
                indices.add(1)
                continue
            m = _OTRO_IMPUESTO_N_RE.match(key)
            if m:
                indices.add(int(m.group(1)))
                continue
            mm = _OTRO_IMPUESTO_MONTO_N_RE.match(key)
            if mm:
                indices.add(int(mm.group(1)))
    return sorted(indices)


def build_converted_payload(rows: List[Dict[str, Any]]) -> str:
    payload = {
        "format": CONVERSION_FORMAT,
        "version": CONVERSION_VERSION,
        "odoo_profile": current_odoo_profile(),
        "rows": rows,
    }
    return json.dumps(payload, ensure_ascii=False)


def parse_converted_payload(raw: Any) -> List[Dict[str, Any]]:
    if raw is None:
        raise ProcessConversionError("converted_data vacío.")
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProcessConversionError(f"converted_data no es JSON válido: {e}") from e
    elif isinstance(raw, dict):
        data = raw
    else:
        raise ProcessConversionError("converted_data tiene un tipo no soportado.")

    if not isinstance(data, dict):
        raise ProcessConversionError("converted_data debe ser un objeto JSON.")

    fmt = data.get("format")
    if fmt and fmt != CONVERSION_FORMAT:
        raise ProcessConversionError(f"Formato de conversión no soportado: {fmt}")

    rows = data.get("rows")
    if not isinstance(rows, list):
        raise ProcessConversionError("converted_data.rows debe ser una lista.")
    return rows


def get_saved_conversion(process_id: int) -> Optional[Dict[str, Any]]:
    template_id = get_conversion_template_id()
    table_ref = _mysql_table_ref(PROCESS_SCHEMA, CONVERSIONS_TABLE)
    conn = get_mysql_connection()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                f"""
                SELECT id, process_id, template_id, company_id, user_id,
                       converted_data, created_at, updated_at
                FROM {table_ref}
                WHERE process_id = %s AND template_id = %s
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (process_id, template_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            rows = parse_converted_payload(row.get("converted_data"))
            return {
                "id": row.get("id"),
                "process_id": row.get("process_id"),
                "template_id": row.get("template_id"),
                "company_id": row.get("company_id"),
                "user_id": row.get("user_id"),
                "rows": rows,
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
                "extra_tax_indices": infer_otro_impuesto_indices(rows),
            }
        finally:
            cur.close()
    finally:
        conn.close()


def save_conversion(
    process_id: int,
    company_id: int,
    user_id: Optional[Any],
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not isinstance(rows, list):
        raise ProcessConversionError("rows debe ser una lista.")

    template_id = get_conversion_template_id()
    converted_data = build_converted_payload(rows)
    now = datetime.now().replace(microsecond=0)
    table_ref = _mysql_table_ref(PROCESS_SCHEMA, CONVERSIONS_TABLE)
    conn = get_mysql_connection()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                f"""
                SELECT id FROM {table_ref}
                WHERE process_id = %s AND template_id = %s
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (process_id, template_id),
            )
            existing = cur.fetchone()
            uid = int(user_id) if user_id is not None and str(user_id).strip() != "" else None

            if existing:
                conv_id = existing["id"]
                cur.execute(
                    f"""
                    UPDATE {table_ref}
                    SET converted_data = %s, company_id = %s, user_id = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (converted_data, company_id, uid, now, conv_id),
                )
            else:
                cur.execute(
                    f"""
                    INSERT INTO {table_ref}
                        (process_id, template_id, company_id, user_id, converted_data, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        process_id,
                        template_id,
                        company_id,
                        uid,
                        converted_data,
                        now,
                        now,
                    ),
                )
                conv_id = cur.lastrowid
            conn.commit()
            return {
                "id": conv_id,
                "process_id": process_id,
                "template_id": template_id,
                "odoo_profile": current_odoo_profile(),
                "saved_at": now.isoformat(sep=" "),
            }
        finally:
            cur.close()
    finally:
        conn.close()


def delete_conversion(process_id: int) -> int:
    template_id = get_conversion_template_id()
    table_ref = _mysql_table_ref(PROCESS_SCHEMA, CONVERSIONS_TABLE)
    conn = get_mysql_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                f"DELETE FROM {table_ref} WHERE process_id = %s AND template_id = %s",
                (process_id, template_id),
            )
            deleted = cur.rowcount or 0
            conn.commit()
            return deleted
        finally:
            cur.close()
    finally:
        conn.close()


def load_process_rows(
    process_number: str,
    empresa: Optional[str] = None,
    regenerate: bool = False,
) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, Any], str, Optional[Dict[str, Any]]]:
    """
    Load rows for a process.

    Returns (rows, etiqueta_options, purchase_summary, source, conversion_meta).
    source is 'saved' or 'generated'.
    """
    from facturia_matching.back_check import get_process
    from facturia_matching.process import parse_process_json
    from facturia_matching.purchase_matching import enrich_rows_with_purchase_data

    process_row = get_process(process_number, empresa=empresa)
    if not process_row:
        return ([], [], {"enabled": False}, "generated", None)

    process_id = process_row.get("id")
    conversion_meta: Optional[Dict[str, Any]] = None

    profile = current_odoo_profile()
    template_id = get_conversion_template_id()

    if not regenerate and process_id:
        saved = get_saved_conversion(int(process_id))
        if saved and saved.get("rows"):
            from facturia_matching.saved_row_remap import remap_saved_rows_to_catalog

            filas = remap_saved_rows_to_catalog(saved["rows"])
            conversion_meta = {
                "id": saved.get("id"),
                "saved_at": _format_dt(saved.get("updated_at") or saved.get("created_at")),
                "extra_tax_indices": saved.get("extra_tax_indices") or [],
                "odoo_profile": profile,
                "template_id": template_id,
            }
            purchase_summary = enrich_rows_with_purchase_data(filas)
            etiqueta_opts: List[str] = []
            for row in filas:
                desc = row.get("invoice_line_ids/name") or row.get("Nombre de producto") or ""
                if desc and str(desc).strip():
                    etiqueta_opts.append(str(desc).strip())
            etiqueta_opts = sorted({p for p in etiqueta_opts if p})
            # #region agent log
            try:
                import time

                header = filas[0] if filas else {}
                with open(
                    "/home/cdlezana/Downloads/Trabajo/facturia-matching-ui/.cursor/debug-bebbc2.log",
                    "a",
                    encoding="utf-8",
                ) as _df:
                    _df.write(
                        json.dumps(
                            {
                                "sessionId": "bebbc2",
                                "location": "process_conversions.py:load_process_rows",
                                "message": "loaded saved conversion",
                                "data": {
                                    "process_number": process_number,
                                    "odoo_profile": profile,
                                    "template_id": template_id,
                                    "source": "saved",
                                    "partner_id": header.get("partner_id"),
                                    "proveedor": header.get("Nombre de Proveedor"),
                                    "conversion_id": saved.get("id"),
                                },
                                "hypothesisId": "H3",
                                "timestamp": int(time.time() * 1000),
                            }
                        )
                        + "\n"
                    )
            except Exception:
                pass
            # #endregion
            return (filas, etiqueta_opts, purchase_summary, "saved", conversion_meta)

    filas, etiqueta_opts, purchase_summary = parse_process_json(process_number, empresa=empresa)
    # #region agent log
    try:
        import time

        header = filas[0] if filas else {}
        with open(
            "/home/cdlezana/Downloads/Trabajo/facturia-matching-ui/.cursor/debug-bebbc2.log",
            "a",
            encoding="utf-8",
        ) as _df:
            _df.write(
                json.dumps(
                    {
                        "sessionId": "bebbc2",
                        "location": "process_conversions.py:load_process_rows",
                        "message": "generated process rows",
                        "data": {
                            "process_number": process_number,
                            "odoo_profile": profile,
                            "template_id": template_id,
                            "source": "generated",
                            "partner_id": header.get("partner_id"),
                            "proveedor": header.get("Nombre de Proveedor"),
                            "oc_matched": purchase_summary.get("rows_matched"),
                        },
                        "hypothesisId": "H3",
                        "timestamp": int(time.time() * 1000),
                    }
                )
                + "\n"
            )
    except Exception:
        pass
    # #endregion
    return (filas, etiqueta_opts, purchase_summary, "generated", conversion_meta)


def _format_dt(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)
