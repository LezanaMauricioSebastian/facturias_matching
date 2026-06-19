"""Metadata and dropdown options for the UI."""

from typing import Any, Dict, List, Optional

from psycopg2.sql import Identifier, SQL

from facturia_matching.constants import (
    COLUMN_LABELS,
    DOCUMENT_TYPES_OPTIONS,
    IVA_OPTIONS,
    OTROS_IMPUESTOS_OPTIONS,
    OUTPUT_HEADERS,
    UI_COLUMNS,
    append_purchase_columns,
    csv_export_headers,
    ui_header_keys,
)
from facturia_matching.odoo_catalog import get_catalog
from facturia_matching.padron import (
    detect_line_label_column,
    detect_padron_fields,
    get_table_columns,
    pg_conn,
    table_ident,
)
from facturia_matching.utils import normalize

# Re-export for routes that need product options helper
__all__ = [
    "build_metadata_payload",
    "get_options",
    "options_base_payload",
    "options_from_odoo_catalog",
    "options_from_postgres",
    "pg_product_options",
]


def pg_product_options(limit: int = 20000) -> List[Dict[str, Any]]:
    try:
        with pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, default_code
                    FROM public.product_product
                    WHERE active IS DISTINCT FROM false
                      AND name IS NOT NULL AND trim(name) <> ''
                    ORDER BY name
                    LIMIT %s
                    """,
                    (int(limit),),
                )
                out = []
                for pid, name, code in cur.fetchall():
                    if not name:
                        continue
                    row: Dict[str, Any] = {"id": int(pid), "name": normalize(name)}
                    if code:
                        row["code"] = normalize(code)
                    out.append(row)
                return out
    except Exception:
        return []


def pg_sample_strings(col: Optional[str], limit: int = 5000) -> List[str]:
    if not col:
        return []
    with pg_conn() as conn:
        with conn.cursor() as cur:
            q = SQL(
                "SELECT {c} "
                "FROM {t} "
                "WHERE {c} IS NOT NULL AND trim(CAST({c} AS text)) <> '' "
                "LIMIT {lim}"
            ).format(c=Identifier(col), t=table_ident(), lim=SQL(str(int(limit))))
            cur.execute(q)
            return sorted({normalize(r[0]) for r in cur.fetchall() if normalize(r[0])})


def strings_to_legacy_options(names: List[str]) -> List[Dict[str, Any]]:
    return [{"id": n, "name": n} for n in names if n]


def options_base_payload() -> Dict[str, Any]:
    return {
        "iva_options": IVA_OPTIONS,
        "otros_impuestos_options": OTROS_IMPUESTOS_OPTIONS,
        "productos": [],
        "etiquetas": [],
        "proveedores": [],
        "proveedores_cuit_map": {},
        "rubros": [],
        "journals": [],
        "cuentas": [],
        "document_types": [],
        "facturas_c_type_ids": [],
        "catalog_source": "none",
    }


def options_from_odoo_catalog(catalog: Dict[str, Any]) -> Dict[str, Any]:
    out = options_base_payload()
    out.update(
        {
            "proveedores": catalog.get("proveedores") or [],
            "proveedores_cuit_map": catalog.get("proveedores_cuit_map") or {},
            "rubros": catalog.get("rubros") or [],
            "journals": catalog.get("journals") or [],
            "cuentas": catalog.get("cuentas") or [],
            "document_types": catalog.get("document_types") or [],
            "facturas_c_type_ids": catalog.get("facturas_c_type_ids") or [],
            "productos": catalog.get("productos") or [],
            "catalog_source": "odoo",
        }
    )
    return out


def options_from_postgres(padron: bool) -> Dict[str, Any]:
    out = options_base_payload()
    out["catalog_source"] = "postgres"
    try:
        with pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, vat
                    FROM public.res_partner
                    WHERE name IS NOT NULL AND trim(name) <> ''
                    LIMIT 20000
                    """
                )
                provs = []
                cuit_map: Dict[str, str] = {}
                for pid, n, v in cur.fetchall():
                    if not n:
                        continue
                    sid = str(pid) if pid is not None else normalize(n)
                    provs.append({"id": int(pid) if pid is not None else sid, "name": normalize(n)})
                    vv = normalize(v)
                    if vv:
                        cuit_map[str(sid)] = vv
                out["proveedores"] = sorted(provs, key=lambda x: x["name"].upper())
                out["proveedores_cuit_map"] = cuit_map

                cur.execute(
                    """
                    SELECT id, name FROM public.account_journal
                    WHERE name IS NOT NULL AND trim(name) <> '' LIMIT 5000
                    """
                )
                out["journals"] = [{"id": r[0], "name": normalize(r[1])} for r in cur.fetchall() if r[1]]

                cur.execute(
                    """
                    SELECT id, name FROM public.account_account
                    WHERE name IS NOT NULL AND trim(name) <> '' LIMIT 5000
                    """
                )
                out["cuentas"] = [{"id": r[0], "name": normalize(r[1])} for r in cur.fetchall() if r[1]]
    except Exception:
        pass

    out["document_types"] = strings_to_legacy_options(DOCUMENT_TYPES_OPTIONS)

    if padron:
        try:
            cols = get_table_columns()
            fields = detect_padron_fields(cols)
            rubros = pg_sample_strings(fields.get("rubro"), 5000)
            if rubros:
                out["rubros"] = strings_to_legacy_options(rubros)
            line_name_col = detect_line_label_column(cols)
            if line_name_col:
                out["etiquetas"] = pg_sample_strings(line_name_col, 5000)
            if not out.get("productos"):
                out["productos"] = pg_product_options()
        except Exception:
            pass
    elif not out.get("productos"):
        out["productos"] = pg_product_options()
    return out


def get_options(padron: bool = False) -> Dict[str, Any]:
    catalog, from_odoo = get_catalog()
    if from_odoo and catalog:
        out = options_from_odoo_catalog(catalog)
    else:
        out = options_from_postgres(padron)

    if padron:
        etiquetas_db: List[str] = []
        try:
            cols = get_table_columns()
            line_name_col = detect_line_label_column(cols)
            if line_name_col:
                etiquetas_db = pg_sample_strings(line_name_col, 5000)
        except Exception:
            etiquetas_db = []
        if etiquetas_db:
            out["etiquetas"] = etiquetas_db

    return out


def build_metadata_payload() -> Dict[str, Any]:
    columns = []
    dropdown_cols = {
        "partner_id": "proveedores",
        "l10n_latam_document_type_id": "document_types",
        "x_studio_category": "rubros",
        "journal_id": "journals",
        "invoice_line_ids/account_id": "cuentas",
        "invoice_line_ids/product_id": "productos",
        "iva_pct": "iva_options",
        "otros_impuestos": "otros_impuestos_options",
    }
    numeric_cols = {"invoice_line_ids/quantity", "invoice_line_ids/price_unit", "iva_monto", "otros_impuestos_monto"}
    readonly_cols = {"CUIT"}
    for key in [*ui_header_keys(), *UI_COLUMNS]:
        if key in dropdown_cols:
            col_type = "selection"
        elif key in numeric_cols:
            col_type = "numeric"
        else:
            col_type = "text"
        label = COLUMN_LABELS.get(key, key)
        columns.append(
            {
                "key": key,
                "label": label,
                "type": col_type,
                "options_key": dropdown_cols.get(key),
                "readonly": key in readonly_cols,
                "editable": (col_type == "text") and (key not in readonly_cols),
            }
        )
    append_purchase_columns(columns, readonly_cols)
    csv_headers = csv_export_headers(list(OUTPUT_HEADERS))
    return {
        "columns": columns,
        "output_headers": OUTPUT_HEADERS,
        "csv_export_headers": csv_headers,
    }
