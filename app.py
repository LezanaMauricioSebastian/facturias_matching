import csv
import io
import json
import os
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from psycopg2 import connect
from psycopg2.extras import RealDictCursor
from psycopg2.sql import Identifier, SQL
from rapidfuzz import fuzz, process as rf_process

# Carga env desde `.env` en la raíz del repo.
_here = os.path.dirname(__file__)
dotenv.load_dotenv(os.path.join(_here, ".env"))
#nota. los cambios realizados son para un tipo de factura no contable.
#cambio. odoo espera el campo invoice_line_ids/tax_ids para los impuestos. 
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_TABLE_NAME = os.getenv("DB_TABLE_NAME", "").strip() or "view_padron_facturia"
DB_TABLE_NAME_FALLBACK = (
    os.getenv("DB_TABLE_NAME_FALLBACK", "").strip()
    or os.getenv("DB_TABLE_NAME_TAXES", "").strip()
    or "view_padron_facturia_actualizado"
)
DB_SCHEMA = os.getenv("DB_SCHEMA", "public").strip() or "public"
PADRON_FUZZY_MIN_SCORE = float(os.getenv("PADRON_FUZZY_MIN_SCORE", "72") or "72")

from back_check import MySQLUnavailableError, ProcessTableError, get_process
from padron_taxes import apply_padron_taxes_to_row, build_csv_tax_ids_dot_id
from config import DEFAULT_JOURNAL_NAME, DEFAULT_RUBRO_NAME, _env_strip, get_table_columns as cfg_get_table_columns
from config import ODOO_CONFIG
from odoo_api import (
    _jsonrpc_url,
    get_odoo_test_config,
    get_odoo_uid,
    is_odoo_config_ready,
    is_odoo_configured,
    odoo_xmlrpc_version,
    verify_odoo_config_connection,
)
from odoo_import import import_rows_to_odoo_test
from odoo_catalog import (
    get_catalog,
    resolve_account_id,
    resolve_doc_type_id,
    resolve_id_fuzzy,
    resolve_partner_id,
)

# Claves internas (UI/filas) → encabezado CSV para importación Odoo por id numérico
CSV_HEADER_BY_ROW_KEY: Dict[str, str] = {
    "partner_id": "partner_id/.id",
    "l10n_latam_document_type_id": "l10n_latam_document_type_id/.id",
    "x_studio_category": "x_studio_category/.id",
    "journal_id": "journal_id/.id",
    "invoice_line_ids/account_id": "invoice_line_ids/account_id/.id",
}

# Columna solo en export CSV (Odoo: varios impuestos en una celda, ej. "63,1")
CSV_EXPORT_TAX_IDS_HEADER = "invoice_line_ids/tax_ids/.id"


def _csv_export_header(row_key: str) -> str:
    return CSV_HEADER_BY_ROW_KEY.get(row_key, row_key)


def _csv_export_headers(row_keys: List[str]) -> List[str]:
    return [_csv_export_header(k) for k in row_keys]


OUTPUT_HEADERS = [
    "l10n_latam_document_number",
    "CUIT",
    "partner_id",
    "l10n_latam_document_type_id",
    "invoice_date",
    "invoice_date_due",
    "x_studio_category",
    "invoice_line_ids/name",
    "journal_id",
    "invoice_line_ids/account_id",
    "invoice_line_ids/quantity",
    "invoice_line_ids/price_unit",
    # montos absolutos (se exportan al CSV)
    "iva_monto",
    "otros_impuestos_monto",
]

IVA_SPECIAL_OPTIONS = ["IVA No Corresponde", "IVA No Gravado", "IVA Exento"]
IVA_OPTIONS = [
    *IVA_SPECIAL_OPTIONS,
    "0",
    "2,5",
    "5",
    "10,5",
    "21",
    "27",
]
OTROS_IMPUESTOS_OPTIONS = [
"Percepción IIBB CABA Sufrida",
"Percepción IIBB ARBA Sufrida",
"Percepción IIBB Catamarca Sufrida",
"Percepción IIBB Córdoba Sufrida",
"Percepción IIBB Corrientes Sufrida",
"Percepción IIBB Entre Ríos Sufrida",
"Percepción IIBB Jujuy Sufrida",
"Percepción IIBB Mendoza Sufrida",
"Percepción IIBB La Rioja Sufrida",
"Percepción IIBB Salta Sufrida",
"Percepción IIBB San Juan Sufrida",
"Percepción IIBB San Luis Sufrida",
"Percepción IIBB Santa Fe Sufrida",
"Percepción IIBB Santiago del Estero Sufrida",
"Percepción IIBB Tucumán Sufrida",
"Percepción IIBB Chaco Sufrida",
"Percepción IIBB Chubut Sufrida",
"Percepción IIBB Formosa Sufrida",
"Percepción IIBB Misiones Sufrida",
"Percepción IIBB Neuquén Sufrida",
"Percepción IIBB La Pampa Sufrida",
"Percepción IIBB Río Negro Sufrida",
"Percepción IIBB Santa Cruz Sufrida",
"Percepción IIBB Tierra del Fuego Sufrida",
"Percepción IVA Aplicada",
"Percepción Ganancias Aplicada",
"Percepción Ganancias Sufrida",
"Percepción IIBB CABA Aplicada",
"Percepción IIBB ARBA Aplicada",
"Percepción IIBB Catamarca Aplicada",
"Percepción IIBB Córdoba Aplicada",
"Percepción IIBB Corrientes Aplicada",
"Percepción IIBB Entre Ríos Aplicada",
"Percepción IIBB Jujuy Aplicada",
"Percepción IIBB Mendoza Aplicada",
"Percepción IIBB La Rioja Aplicada",
"Percepción IIBB Salta Aplicada",
"Percepción IIBB San Juan Aplicada",
"Percepción IIBB San Luis Aplicada",
"Percepción IIBB Santa Fe Aplicada",
"Percepción IIBB Santiago del Estero Aplicada",
"Percepción IIBB Tucumán Aplicada",
"Percepción IIBB Chaco Aplicada",
"Percepción IIBB Chubut Aplicada",
"Percepción IIBB Formosa Aplicada",
"Percepción IIBB Misiones Aplicada",
"Percepción IIBB Neuquén Aplicada",
"Percepción IIBB La Pampa Aplicada",
"Percepción IIBB Río Negro Aplicada",
"Percepción IIBB Santa Cruz Aplicada",
"Percepción IIBB Tierra del Fuego Aplicada",
"Percepción IVA Sufrida",
"IVA Adicional 20%",
]
DOCUMENT_TYPES_OPTIONS = ["FACTURAS A", "FACTURAS B", "FACTURAS C", "OC-X"]

UI_COLUMNS = [
    "iva_pct",
    "otros_impuestos",
]

COLUMN_LABELS = {
    "l10n_latam_document_number": "Número de Documento",
    "partner_id": "Proveedor",
    "CUIT": "Cuit",
    "l10n_latam_document_type_id": "Tipo de Documento",
    "invoice_date": "Fecha factura",
    "invoice_date_due": "Fecha de vencimiento",
    "x_studio_category": "Rubros",
    "invoice_line_ids/name": "Etiqueta",
    "journal_id": "Diario",
    "invoice_line_ids/account_id": "Cuenta",
    "invoice_line_ids/quantity": "Cantidad",
    "invoice_line_ids/price_unit": "Precio",
    "iva_pct": "Impuesto IVA",
    "iva_monto": "Monto IVA",
    "otros_impuestos": "Otros Impuestos",
    "otros_impuestos_monto": "Monto Otros Impuestos",
}


def _normalize_iva_pct_value(raw: str) -> str:
    """
    Alícuota IVA para la UI: coma decimal (10,5).
    Acepta entradas legacy con punto (10.5) desde FacturIA.
    """
    s = _normalize(raw)
    if not s or s in IVA_SPECIAL_OPTIONS:
        return s
    if s in IVA_OPTIONS:
        return s
    cleaned = s.replace(" ", "")
    m = re.match(r"^(\d+)\.(\d+)$", cleaned)
    if m and "," not in cleaned:
        s = f"{m.group(1)},{m.group(2)}"
        if s in IVA_OPTIONS:
            return s
    return s


def _iva_pct_for_odoo_tax_label(iva_pct: str) -> str:
    """Nombre de impuesto en Odoo: suele ir con punto (IVA 10.5%)."""
    s = _normalize(iva_pct)
    if re.match(r"^\d+,\d+$", s.replace(" ", "")):
        return s.replace(",", ".")
    return s


def _ui_header_keys() -> List[str]:
    """Headers que se muestran en la UI (sin columnas solo-export)."""
    return list(OUTPUT_HEADERS)


def _build_tax_names(row: Dict[str, Any]) -> List[str]:
    """
    Devuelve lista de impuestos (NOMBRES).
    Odoo resuelve el impuesto del lado de importación.
    """
    names: List[str] = []

    iva_pct = _normalize(row.get("iva_pct"))
    if iva_pct:
        if iva_pct in IVA_SPECIAL_OPTIONS:
            names.append(iva_pct)
        elif iva_pct != "0":
            names.append(f"IVA {_iva_pct_for_odoo_tax_label(iva_pct)}%")

    for k, v in row.items():
        if not isinstance(k, str):
            continue
        # Solo claves de selección (no montos)
        if k == "otros_impuestos" or (k.startswith("otros_impuestos_") and not k.endswith("_monto")):
            n = _normalize(v)
            if n:
                names.append(n)

    # dedupe conservando orden
    seen = set()
    out: List[str] = []
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        out.append(n)

    return out


def _pg_conn():
    if not (DB_HOST and DB_USER and DB_PASSWORD and DB_NAME):
        raise ValueError("Faltan variables de entorno de Postgres (DB_HOST/DB_USER/DB_PASSWORD/DB_NAME).")
    return connect(
        host=DB_HOST,
        port=int(DB_PORT),
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
    )


def _table_ident(table_name: Optional[str] = None) -> SQL:
    return SQL("{}.{}").format(Identifier(DB_SCHEMA), Identifier((table_name or DB_TABLE_NAME).strip()))

def _odoo_table_ident(table: str, schema: str = "public") -> SQL:
    schema = (schema or "public").strip() or "public"
    table = (table or "").strip()
    return SQL("{}.{}").format(Identifier(schema), Identifier(table))


def _get_table_columns() -> List[str]:
    """
    Devuelve columnas disponibles en DB_TABLE_NAME.
    - Si DB_SCHEMA == public, reutiliza helper de config.py
    - Si no, usa information_schema con DB_SCHEMA
    """
    if DB_SCHEMA.lower() == "public":
        cols = cfg_get_table_columns(DB_TABLE_NAME) or []
        # cfg_get_table_columns devuelve lista de tuplas [('col',), ...]
        out = []
        for c in cols:
            if isinstance(c, (list, tuple)) and c:
                out.append(str(c[0]))
            elif c:
                out.append(str(c))
        if out:
            return out
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            # information_schema a veces no expone columnas de materialized views
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                (DB_SCHEMA, DB_TABLE_NAME),
            )
            cols = [r[0] for r in cur.fetchall()]
            if cols:
                return cols

            # Fallback pg_catalog (incluye matviews)
            cur.execute(
                """
                SELECT a.attname
                FROM pg_catalog.pg_attribute a
                JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s
                  AND c.relname = %s
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                ORDER BY a.attnum
                """,
                (DB_SCHEMA, DB_TABLE_NAME),
            )
            return [r[0] for r in cur.fetchall()]


# Columnas reales de view_padron_facturia (consultadas en PG)
PADRON_FIELD_COLUMNS = {
    "name": "nombre_contacto",
    "doc": "numero_documento",
    "rubro": "rubro",
    "diario": "diario",
    "cuenta": "cuenta_contable_completo",
    "tipo_documento": "tipo_documento",
}


def _detect_padron_fields(cols: List[str]) -> Dict[str, Optional[str]]:
    """Mapea campos lógicos a columnas exactas del padrón (sin tanteo de nombres)."""
    cols_set = set(cols)
    return {
        key: col_name if col_name in cols_set else None
        for key, col_name in PADRON_FIELD_COLUMNS.items()
    }


def _normalize(s: Any) -> str:
    if s is None:
        return ""
    return " ".join(str(s).strip().split())


_DATE_DD_MM = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$")
_DATE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")


def _normalize_date_ddmmyyyy(raw: Any) -> str:
    """Formato canónico de fechas en la UI: dd/mm/yyyy."""
    s = _normalize(raw)
    if not s:
        return ""
    m = _DATE_DD_MM.match(s)
    if m:
        dd, mm, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = _DATE_ISO.match(s)
        if not m:
            return s
        yyyy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        d = date(yyyy, mm, dd)
    except ValueError:
        return s
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def _pick(row: Dict[str, Any], candidates: List[str]) -> str:
    lower_map = {k.lower(): k for k in row.keys()}
    for cand in candidates:
        key = lower_map.get(cand.lower())
        if key is not None:
            v = row.get(key)
            if v is None:
                continue
            vs = _normalize(v)
            if vs.lower() != "nan":
                return vs
    return ""


# Totales a nivel comprobante (`factura` en JSON FacturIA). Lista ampliable cuando haya muestras reales.
_FAC_SUBTOTAL_KEYS = [
    "subtotal",
    "subtotal_sin_iva",
    "subtotal_sin_ivas",
    "base_imponible",
    "importe_neto",
    "total_sin_iva",
    "total_neto",
    "neto",
    "importe_total_neto",
    "monto_neto",
]
_FAC_IVA_MONTO_KEYS = [
    "iva_monto",
    "iva_total",
    "importe_iva",
    "total_iva",
    "monto_iva",
    "impuesto_iva",
]
# Desglose IVA por alícuota (FacturIA a nivel comprobante)
_FAC_IVA_RATE_KEYS = ["iva_21", "iva_10_5", "iva_27", "iva_2_5", "iva_5"]
_FAC_PERCEPCION_AMOUNT_KEYS = ["percepcion_iibb", "percepcion_iva", "otros_tributos"]


def _parse_amount(raw: Any) -> Optional[float]:
    s = _normalize(raw)
    if not s or s.lower() == "nan":
        return None
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_amount_loose(raw: Any) -> Optional[float]:
    """Acepta número plano o formato es-AR (1.702.755,50 / 45.000) para export/UI."""
    s = _normalize(raw)
    if not s or s.lower() == "nan":
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        # Miles con punto: cada tramo tras el primero tiene 3 dígitos (1.657.755, 45.000)
        if len(parts) >= 2 and all(p.isdigit() and len(p) == 3 for p in parts[1:]):
            s = "".join(parts)
    try:
        return float(s)
    except ValueError:
        return None


def _format_amount_for_odoo_csv(raw: Any, *, money: bool = False) -> str:
    """
    Solo al exportar CSV: la UI sigue en es-AR (1.000,50); Odoo recibe sin miles y coma→punto.
    Ej.: 1.000,50 → 1000.50 · 1.657.755 → 1657755 · 45.000 → 45000
    """
    n = _parse_amount_loose(raw)
    if n is None:
        return _normalize(raw)
    if money:
        return f"{round(n, 2):.2f}"
    s = f"{round(n, 6):.6f}".rstrip("0").rstrip(".")
    return s or "0"


_CSV_AMOUNT_ROW_KEYS = frozenset(
    {
        "invoice_line_ids/quantity",
        "invoice_line_ids/price_unit",
        "iva_monto",
        "otros_impuestos_monto",
    }
)


def _is_otros_monto_row_key(key: str) -> bool:
    return key == "otros_impuestos_monto" or (
        key.startswith("otros_impuestos_") and key.endswith("_monto")
    )


def _csv_export_cell(row: Dict[str, Any], key: str) -> str:
    val = row.get(key, "")
    if key in _CSV_AMOUNT_ROW_KEYS or _is_otros_monto_row_key(key):
        return _format_amount_for_odoo_csv(val, money=key != "invoice_line_ids/quantity")
    return "" if val is None else str(val)


def _rows_prepared_for_odoo_csv(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Repite encabezado del comprobante en líneas 2+ y deja montos listos para import."""
    out: List[Dict[str, Any]] = [dict(r) for r in rows if isinstance(r, dict)]
    header_keys = (
        "l10n_latam_document_number",
        "partner_id",
        "l10n_latam_document_type_id",
        "invoice_date",
        "invoice_date_due",
        "x_studio_category",
        "journal_id",
    )
    for i in range(1, len(out)):
        cur, prev = out[i], out[i - 1]
        same_inv = (
            cur.get("__comprobante_idx") is not None
            and cur.get("__comprobante_idx") == prev.get("__comprobante_idx")
        ) or (
            not _normalize(cur.get("l10n_latam_document_number"))
            and _normalize(prev.get("l10n_latam_document_number"))
        )
        if not same_inv:
            continue
        for k in header_keys:
            if not _normalize(cur.get(k)) and _normalize(prev.get(k)):
                cur[k] = prev[k]
    return out


def _amount_to_str(val: float) -> str:
    if abs(val) < 1e-12:
        return ""
    return f"{round(val, 2):.2f}"


def _fac_header_amount_str(fac: Dict[str, Any], candidates: List[str]) -> str:
    """Primer valor no vacío entre claves candidatas (case-insensitive)."""
    if not isinstance(fac, dict):
        return ""
    return _pick(fac, candidates)


def _fac_iva_monto_str(fac: Dict[str, Any]) -> str:
    """IVA total a nivel comprobante: suma iva_21/iva_10_5/… o claves genéricas."""
    if not isinstance(fac, dict):
        return ""
    total = 0.0
    found = False
    for key in _FAC_IVA_RATE_KEYS:
        amt = _parse_amount(_pick(fac, [key]))
        if amt is not None and amt > 0:
            total += amt
            found = True
    if found:
        return _amount_to_str(total)
    return _fac_header_amount_str(fac, _FAC_IVA_MONTO_KEYS)


def _otros_impuesto_monto_key(n: int) -> str:
    return "otros_impuestos_monto" if n == 1 else f"otros_impuestos_{n}_monto"


def _apply_fac_percepciones_to_row(fac: Dict[str, Any], row_out: Dict[str, Any]) -> None:
    """Montos de percepciones/otros tributos desde factura; no rellena etiquetas."""
    if not isinstance(fac, dict) or not isinstance(row_out, dict):
        return
    percepciones: List[Dict[str, str]] = []
    slot = 1
    for fac_key in _FAC_PERCEPCION_AMOUNT_KEYS:
        amt = _parse_amount(_pick(fac, [fac_key]))
        if amt is None or amt <= 0:
            continue
        monto_key = _otros_impuesto_monto_key(slot)
        monto_str = _amount_to_str(amt)
        if not _normalize(row_out.get(monto_key)):
            row_out[monto_key] = monto_str
        percepciones.append(
            {"amount_key": fac_key, "monto": monto_str, "ui_monto_key": monto_key}
        )
        slot += 1
    if percepciones:
        row_out["__fac_percepciones"] = percepciones


def _doc_type_label(raw_tipo: str) -> str:
    """
    Normaliza tipo de comprobante a etiqueta (FACTURAS A / B / C u OC-X).
    """
    tipo = _normalize(raw_tipo).upper()
    if not tipo:
        return "OC-X"

    tipo = tipo.replace("FACTURAS", "FACTURA").strip()

    if tipo in {"A", "B", "C"}:
        tipo = f"FACTURA {tipo}"
    if tipo and not tipo.startswith("FACTURA"):
        tipo = f"FACTURA {tipo}"

    if tipo in {"FACTURA A", "FACTURA B", "FACTURA C"}:
        return tipo.replace("FACTURA", "FACTURAS", 1)
    return "OC-X"


def _get_odoo_catalog() -> Tuple[Optional[Dict[str, Any]], bool]:
    return get_catalog()


def _get_table_columns_for(table_name: str) -> List[str]:
    """Columnas de una vista de padrón (p. ej. fallback actualizado). Incluye matviews vía pg_catalog."""
    table_name = (table_name or "").strip()
    if not table_name:
        return []
    if DB_SCHEMA.lower() == "public":
        cols = cfg_get_table_columns(table_name) or []
        out = []
        for c in cols:
            if isinstance(c, (list, tuple)) and c:
                out.append(str(c[0]))
            elif c:
                out.append(str(c))
        if out:
            return out
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                (DB_SCHEMA, table_name),
            )
            cols = [r[0] for r in cur.fetchall()]
            if cols:
                return cols
            cur.execute(
                """
                SELECT a.attname
                FROM pg_catalog.pg_attribute a
                JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s
                  AND c.relname = %s
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                ORDER BY a.attnum
                """,
                (DB_SCHEMA, table_name),
            )
            return [r[0] for r in cur.fetchall()]


def _padron_rows(table_name: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Carga padron desde Postgres (DB_TABLE_NAME o table_name indicado).
    Columnas típicas vistas: nombre_contacto, numero_documento, rubro, diario, tipo_documento.
    """
    table_name = (table_name or DB_TABLE_NAME).strip()
    if limit is None:
        # Evita demoras grandes en /api/options (se usa al cargar la UI)
        # Ajustable por env si hiciera falta.
        limit = int(os.getenv("PADRON_LIMIT", "50000"))
    cols = _get_table_columns_for(table_name) if table_name != DB_TABLE_NAME else _get_table_columns()
    fields = _detect_padron_fields(cols)
    name_col = fields.get("name")
    if not name_col:
        # Fallback Odoo: si no existe view_padron_facturia, usamos res_partner (nombre + vat)
        try:
            with _pg_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    q = SQL(
                        """
                        SELECT
                          name AS name,
                          vat  AS doc,
                          ''   AS rubro,
                          ''   AS diario,
                          ''   AS cuenta
                        FROM {t}
                        WHERE name IS NOT NULL AND trim(name) <> ''
                        LIMIT {lim}
                        """
                    ).format(t=_odoo_table_ident("res_partner", "public"), lim=SQL(str(int(limit))))
                    cur.execute(q)
                    return list(cur.fetchall())
        except Exception:
            # Fail-soft total
            return []

    table_ident = _table_ident(table_name)
    select_cols: List[Tuple[str, str]] = [("name", name_col)]
    for key in ["doc", "rubro", "diario", "tipo_documento"]:
        col = fields.get(key)
        if col:
            select_cols.append((key, col))
    cuenta_col = fields.get("cuenta")
    if cuenta_col:
        select_cols.append(("cuenta", cuenta_col))

    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            select_sql = SQL(", ").join(
                SQL("{} AS {}").format(Identifier(col_name), Identifier(alias))
                for alias, col_name in select_cols
            )
            q = SQL("SELECT {} FROM {} WHERE {} IS NOT NULL AND trim({}) <> '' LIMIT {}").format(
                select_sql,
                table_ident,
                Identifier(name_col),
                Identifier(name_col),
                SQL(str(int(limit))),
            )
            cur.execute(q)
            return list(cur.fetchall())


_PADRON_CACHE: Optional[List[Dict[str, Any]]] = None
_PADRON_FALLBACK_CACHE: Optional[List[Dict[str, Any]]] = None


def _get_padron_cached() -> List[Dict[str, Any]]:
    global _PADRON_CACHE
    if _PADRON_CACHE is None:
        try:
            _PADRON_CACHE = _padron_rows()
        except Exception:
            _PADRON_CACHE = []
    return _PADRON_CACHE


def _get_padron_fallback_cached() -> List[Dict[str, Any]]:
    """Padrón reciente (view_padron_facturia_actualizado): CUITs que no están en la vista vieja."""
    global _PADRON_FALLBACK_CACHE
    if _PADRON_FALLBACK_CACHE is None:
        if not DB_TABLE_NAME_FALLBACK or DB_TABLE_NAME_FALLBACK == DB_TABLE_NAME:
            _PADRON_FALLBACK_CACHE = []
        else:
            try:
                _PADRON_FALLBACK_CACHE = _padron_rows(DB_TABLE_NAME_FALLBACK)
            except Exception:
                _PADRON_FALLBACK_CACHE = []
    return _PADRON_FALLBACK_CACHE


def _padron_row_from_cuit(padron: List[Dict[str, Any]], cuit_n: str) -> Optional[Dict[str, Any]]:
    if not cuit_n:
        return None
    for r in padron:
        doc = "".join(ch for ch in _normalize(r.get("doc")) if ch.isdigit())
        if doc and doc == cuit_n:
            return r
    return None


def _tuple_from_padron_row(r: Dict[str, Any], score: float) -> Tuple[str, str, str, str, float]:
    return (
        _normalize(r.get("name")),
        _normalize(r.get("rubro")),
        _normalize(r.get("diario")),
        _normalize(r.get("cuenta")),
        score,
    )


def _match_proveedor(nombre: str, cuit: str) -> Tuple[str, str, str, str, float]:
    """
    Devuelve (name, rubro, diario, cuenta, score).
    1) CUIT en padrón principal (view_padron_facturia).
    2) CUIT en padrón fallback (view_padron_facturia_actualizado).
    3) Fuzzy por nombre en principal solo si score >= PADRON_FUZZY_MIN_SCORE (default 72).
    """
    nombre_n = _normalize(nombre)
    cuit_n = "".join(ch for ch in _normalize(cuit) if ch.isdigit())

    for padron in (_get_padron_cached(), _get_padron_fallback_cached()):
        hit = _padron_row_from_cuit(padron, cuit_n)
        if hit:
            return _tuple_from_padron_row(hit, 100.0)

    padron = _get_padron_cached()
    names = [(_normalize(r.get("name")), r) for r in padron]
    choices = [n for n, _ in names]
    if not nombre_n or not choices:
        return ("", "", "", "", 0.0)

    best = rf_process.extractOne(nombre_n, choices, scorer=fuzz.WRatio)
    if not best:
        return ("", "", "", "", 0.0)
    best_name, score, idx = best[0], float(best[1]), int(best[2])
    if score < PADRON_FUZZY_MIN_SCORE:
        return ("", "", "", "", 0.0)
    return _tuple_from_padron_row(names[idx][1], score)


def _parse_process_json(process_number: str, empresa: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Devuelve filas 'normalizadas' para UI y opciones de productos (desde items).
    """
    catalog, odoo_ok = _get_odoo_catalog()
    maps = (catalog or {}).get("maps") or {}
    doc_label_map = maps.get("document_type_labels") or {}
    proveedores_odoo = (catalog or {}).get("proveedores") or []
    journals_odoo = (catalog or {}).get("journals") or []
    cuentas_odoo = (catalog or {}).get("cuentas") or []
    rubros_odoo = (catalog or {}).get("rubros") or []
    partner_cuit_to_id = (catalog or {}).get("partner_cuit_to_id") or {}

    # MySQL: sudataco_facturia.process
    row = get_process(int(process_number), empresa=empresa)
    if not row:
        return ([], [])

    json_data = row.get("json_data")
    if json_data is None:
        raise HTTPException(status_code=500, detail="El proceso no tiene json_data.")
    try:
        obj = json.loads(json_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo parsear json_data del proceso: {e}")

    facturas = obj.get("facturas") or []
    out_rows: List[Dict[str, Any]] = []
    product_opts: List[str] = []
    comprobante_idx = -1

    for fac_wrap in facturas:
        j = fac_wrap.get("json") if isinstance(fac_wrap, dict) else None
        if not isinstance(j, dict):
            continue
        fac = j.get("factura") if isinstance(j.get("factura"), dict) else {}
        comprobante_idx += 1

        fac_subtotal_hdr = _fac_header_amount_str(fac, _FAC_SUBTOTAL_KEYS)
        fac_iva_monto_hdr = _fac_iva_monto_str(fac)

        nro = _normalize(fac.get("numero_factura"))
        fecha = _normalize_date_ddmmyyyy(fac.get("fecha"))
        venc = _normalize_date_ddmmyyyy(
            fac.get("fecha_de_vencimiento") or fac.get("fecha_de_vencimiento") or fac.get("fecha_vencimiento")
        )
        tipo = _normalize(fac.get("tipo_comprobante"))
        doc_type_label = _doc_type_label(tipo)
        doc_type_id = resolve_doc_type_id(doc_type_label, doc_label_map) if odoo_ok else ""

        prov = fac.get("proveedor") if isinstance(fac.get("proveedor"), dict) else {}
        prov_nombre = _normalize(prov.get("razon_social") or prov.get("nombre") or "")
        prov_cuit = _normalize(prov.get("cuit") or "")

        matched_name, matched_rubro, matched_diario, matched_cuenta, score = _match_proveedor(prov_nombre, prov_cuit)

        if odoo_ok:
            partner_id, score_odoo = resolve_partner_id(
                prov_nombre,
                prov_cuit,
                proveedores_odoo,
                partner_cuit_to_id,
            )
            if not partner_id and matched_name:
                partner_id = resolve_id_fuzzy(matched_name, proveedores_odoo, min_score=72.0)
                score_odoo = score if not score_odoo else score_odoo
            score = max(score, score_odoo)
            journal_id = resolve_id_fuzzy(
                matched_diario,
                journals_odoo,
                fallback_name=DEFAULT_JOURNAL_NAME or None,
                min_score=75.0,
            )
            account_maps = maps.get("accounts") or {}
            account_id = resolve_account_id(
                matched_cuenta,
                cuentas_odoo,
                account_maps,
                min_score=65.0,
            )
            rubro_id = resolve_id_fuzzy(
                matched_rubro,
                rubros_odoo,
                fallback_name=DEFAULT_RUBRO_NAME or None,
                min_score=72.0,
            )
        else:
            partner_id = ""
            journal_id = ""
            account_id = ""
            rubro_id = ""

        items = fac.get("items") if isinstance(fac.get("items"), list) else []
        if not items:
            # fila de encabezado sin items
            items = [{"descripcion": "", "cantidad": "", "precio_unitario": ""}]

        for i, it in enumerate(items):
            desc = _normalize((it or {}).get("descripcion"))
            if desc:
                product_opts.append(desc)
            qty = (it or {}).get("cantidad")
            price = (it or {}).get("precio_unitario")
            iva = (it or {}).get("alicuota_iva")
            otros_imp = (it or {}).get("otros_impuestos") or (it or {}).get("otros_tributos") or ""
            #etiqueta = (it or {}).get("etiqueta") or (it or {}).get("unidad_medida") or ""

            mismo_comprobante = i > 0  # para una misma factura, repetir solo líneas
            otros_imp_n = _normalize(otros_imp)
            iva_str = "" if iva is None else _normalize_iva_pct_value(str(iva).strip())

            # Si "otros_imp" contiene un IVA especial, lo migramos a IVA cuando no venga iva_pct.
            if (not iva_str) and otros_imp_n in IVA_SPECIAL_OPTIONS:
                iva_str = otros_imp_n
                otros_imp_n = ""

            # Default: Factura C => IVA No Corresponde (si no viene IVA).
            if (not iva_str) and doc_type_label == "FACTURAS C":
                iva_str = "IVA No Corresponde"

            row_out = {
                    "l10n_latam_document_number": "" if mismo_comprobante else nro,
                    "partner_id": "" if mismo_comprobante else partner_id,
                    "l10n_latam_document_type_id": "" if mismo_comprobante else doc_type_id,
                    "invoice_date": "" if mismo_comprobante else fecha,
                    "invoice_date_due": "" if mismo_comprobante else venc,
                    "x_studio_category": "" if mismo_comprobante else rubro_id,
                    "invoice_line_ids/name": desc,
                    "journal_id": "" if mismo_comprobante else journal_id,
                    "invoice_line_ids/account_id": "" if mismo_comprobante else account_id,
                    "invoice_line_ids/quantity": "" if qty is None else str(qty),
                    "invoice_line_ids/price_unit": "" if price is None else str(price),
                    "iva_pct": iva_str,
                    "iva_monto": fac_iva_monto_hdr if i == 0 else "",
                    "otros_impuestos": otros_imp_n,
                    "otros_impuestos_monto": "",
                    "Nombre de Proveedor": prov_nombre,
                    "CUIT": prov_cuit,
                    "Nombre de producto": desc,
                    "_match_score_proveedor": score,
                    "__comprobante_idx": comprobante_idx,
                    "__fac_subtotal": fac_subtotal_hdr if i == 0 else "",
                    "__fac_iva_monto": fac_iva_monto_hdr if i == 0 else "",
                }
            if i == 0:
                if fac_iva_monto_hdr:
                    row_out["__iva_monto_manual"] = True
                _apply_fac_percepciones_to_row(fac, row_out)
            apply_padron_taxes_to_row(row_out, prov_nombre, prov_cuit)
            out_rows.append(row_out)

    product_opts = sorted({p for p in product_opts if p})
    return (out_rows, product_opts)


def _build_output_rows(
    filas: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return filas


app = FastAPI(title="FacturIA matching UI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static UI
_html_dir = os.path.join(os.path.dirname(__file__), "html")
if os.path.isdir(_html_dir):
    app.mount("/static", StaticFiles(directory=_html_dir), name="static")

_css_dir = os.path.join(os.path.dirname(__file__), "css")
if os.path.isdir(_css_dir):
    app.mount("/css", StaticFiles(directory=_css_dir), name="css")

_js_dir = os.path.join(os.path.dirname(__file__), "js")
if os.path.isdir(_js_dir):
    app.mount("/js", StaticFiles(directory=_js_dir), name="js")


@app.get("/", response_class=HTMLResponse)
def root():
    index_path = os.path.join(_html_dir, "index.html")
    if not os.path.exists(index_path):
        return HTMLResponse("<h3>Falta html/index.html</h3>", status_code=500)
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/api/metadata")
def get_metadata():
    # UI se basa en estas columnas (output Odoo)
    columns = []
    dropdown_cols = {
        "partner_id": "proveedores",
        "l10n_latam_document_type_id": "document_types",
        "x_studio_category": "rubros",
        "journal_id": "journals",
        "invoice_line_ids/account_id": "cuentas",
        "iva_pct": "iva_options",
        "otros_impuestos": "otros_impuestos_options",
    }
    numeric_cols = {"invoice_line_ids/quantity", "invoice_line_ids/price_unit", "iva_monto", "otros_impuestos_monto"}
    # Solo CUIT no editable (pedido)
    readonly_cols = {"CUIT"}

    for key in [*_ui_header_keys(), *UI_COLUMNS]:
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

    csv_headers = _csv_export_headers(
        list(OUTPUT_HEADERS)
    )
    return {
        "columns": columns,
        "output_headers": OUTPUT_HEADERS,
        "csv_export_headers": csv_headers,
    }


def _build_metadata_payload() -> Dict[str, Any]:
    columns = []
    dropdown_cols = {
        "partner_id": "proveedores",
        "l10n_latam_document_type_id": "document_types",
        "x_studio_category": "rubros",
        "journal_id": "journals",
        "invoice_line_ids/account_id": "cuentas",
        "iva_pct": "iva_options",
        "otros_impuestos": "otros_impuestos_options",
    }
    numeric_cols = {"invoice_line_ids/quantity", "invoice_line_ids/price_unit", "iva_monto", "otros_impuestos_monto"}
    readonly_cols = {"CUIT"}
    for key in [*_ui_header_keys(), *UI_COLUMNS]:
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
    csv_headers = _csv_export_headers(
        list(OUTPUT_HEADERS)
    )
    return {
        "columns": columns,
        "output_headers": OUTPUT_HEADERS,
        "csv_export_headers": csv_headers,
    }


@app.get("/api/bootstrap")
def get_bootstrap():
    """
    Endpoint para carga inicial del frontend.
    Devuelve metadata + opciones rápidas en una sola llamada (sin padron).
    """
    meta = _build_metadata_payload()
    opts = get_options(padron=False)
    return {"metadata": meta, "options": opts}


def _options_base_payload() -> Dict[str, Any]:
    return {
        "iva_options": IVA_OPTIONS,
        "otros_impuestos_options": OTROS_IMPUESTOS_OPTIONS,
        "productos": [],
        "proveedores": [],
        "proveedores_cuit_map": {},
        "rubros": [],
        "journals": [],
        "cuentas": [],
        "document_types": [],
        "facturas_c_type_ids": [],
        "catalog_source": "none",
    }


def _options_from_odoo_catalog(catalog: Dict[str, Any]) -> Dict[str, Any]:
    out = _options_base_payload()
    out.update(
        {
            "proveedores": catalog.get("proveedores") or [],
            "proveedores_cuit_map": catalog.get("proveedores_cuit_map") or {},
            "rubros": catalog.get("rubros") or [],
            "journals": catalog.get("journals") or [],
            "cuentas": catalog.get("cuentas") or [],
            "document_types": catalog.get("document_types") or [],
            "facturas_c_type_ids": catalog.get("facturas_c_type_ids") or [],
            "catalog_source": "odoo",
        }
    )
    return out


def _pg_sample_strings(col: Optional[str], limit: int = 5000) -> List[str]:
    if not col:
        return []
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            q = SQL(
                "SELECT {c} "
                "FROM {t} "
                "WHERE {c} IS NOT NULL AND trim(CAST({c} AS text)) <> '' "
                "LIMIT {lim}"
            ).format(c=Identifier(col), t=_table_ident(), lim=SQL(str(int(limit))))
            cur.execute(q)
            return sorted({_normalize(r[0]) for r in cur.fetchall() if _normalize(r[0])})


def _strings_to_legacy_options(names: List[str]) -> List[Dict[str, Any]]:
    """Fallback PG: id = nombre (solo para UI si Odoo no respondió)."""
    return [{"id": n, "name": n} for n in names if n]


def _options_from_postgres(padron: bool) -> Dict[str, Any]:
    out = _options_base_payload()
    out["catalog_source"] = "postgres"
    try:
        with _pg_conn() as conn:
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
                    sid = str(pid) if pid is not None else _normalize(n)
                    provs.append({"id": int(pid) if pid is not None else sid, "name": _normalize(n)})
                    vv = _normalize(v)
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
                out["journals"] = [{"id": r[0], "name": _normalize(r[1])} for r in cur.fetchall() if r[1]]

                cur.execute(
                    """
                    SELECT id, name FROM public.account_account
                    WHERE name IS NOT NULL AND trim(name) <> '' LIMIT 5000
                    """
                )
                out["cuentas"] = [{"id": r[0], "name": _normalize(r[1])} for r in cur.fetchall() if r[1]]
    except Exception:
        pass

    out["document_types"] = _strings_to_legacy_options(DOCUMENT_TYPES_OPTIONS)

    if padron:
        try:
            cols = _get_table_columns()
            fields = _detect_padron_fields(cols)
            rubros = _pg_sample_strings(fields.get("rubro"), 5000)
            if rubros:
                out["rubros"] = _strings_to_legacy_options(rubros)
            line_name_col = fields.get("invoice_line_ids_name") or fields.get("etiqueta")
            out["productos"] = _pg_sample_strings(line_name_col, 5000)
        except Exception:
            pass
    return out


@app.get("/api/options")
def get_options(padron: bool = Query(False, description="Si true, carga opciones grandes desde DB (puede tardar).")):
    catalog, from_odoo = get_catalog()
    if from_odoo and catalog:
        out = _options_from_odoo_catalog(catalog)
    else:
        out = _options_from_postgres(padron)

    if padron:
        etiquetas_db: List[str] = []
        try:
            cols = _get_table_columns()
            fields = _detect_padron_fields(cols)
            line_name_col = fields.get("invoice_line_ids_name") or fields.get("etiqueta")
            etiquetas_db = _pg_sample_strings(line_name_col, 5000)
        except Exception:
            etiquetas_db = []
        if etiquetas_db:
            out["productos"] = etiquetas_db

    return out


@app.get("/api/odoo/health")
def odoo_health():
    if not is_odoo_configured():
        return {"ok": False, "error": "ODOO_* no configurado en .env"}
    uid = get_odoo_uid()
    version = odoo_xmlrpc_version()
    return {
        "ok": uid is not None,
        "uid": uid,
        "uid_source": "ODOO_USER_ID" if ODOO_CONFIG.get("uid") is not None else "ODOO_USER",
        "db": ODOO_CONFIG.get("db"),
        "base_url": ODOO_CONFIG.get("base_url"),
        "jsonrpc_url": _jsonrpc_url(),
        "version": version,
    }


@app.get("/api/odoo/health/test")
def odoo_health_test():
    """
    Healthcheck para credenciales Odoo de prueba.
    Ejecuta execute_kw real (no solo uid fijo en .env).
    """
    config = get_odoo_test_config()
    if not is_odoo_config_ready(config):
        return {
            "ok": False,
            "error": "Faltan ODOO_*_TEST en .env (ODOO_API_TEST/ODOO_DB_TEST/ODOO_PASSWORD_TEST y ODOO_USER_ID_TEST u ODOO_USER_TEST).",
        }
    return verify_odoo_config_connection(config)


@app.post("/api/odoo/import/test")
def odoo_import_test(payload: Dict[str, Any]):
    """
    Crea facturas de proveedor (account.move, borrador) en Odoo TEST
    usando ODOO_*_TEST del .env y las filas editadas en la UI.

    Si el comprobante ya existe (mismo proveedor + número), por defecto
    relee la factura y sobreescribe montos en líneas display_type=tax.
    """
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="payload.rows debe ser una lista")
    skip_duplicates = payload.get("skip_duplicates", True)
    update_taxes_if_exists = payload.get("update_taxes_if_exists", True)
    return import_rows_to_odoo_test(
        rows,
        skip_duplicates=bool(skip_duplicates),
        update_taxes_if_exists=bool(update_taxes_if_exists),
    )


@app.get("/api/padron/schema")
def get_padron_schema():
    cols = _get_table_columns()
    detected = _detect_padron_fields(cols)
    return {
        "schema": DB_SCHEMA,
        "table": DB_TABLE_NAME,
        "columns": cols,
        "detected_fields": detected,
        "has_invoice_line_ids_name_column": bool(detected.get("invoice_line_ids_name")),
        "has_etiqueta_column": bool(detected.get("etiqueta")),
    }


@app.get("/api/proceso/{process_number}")
def get_proceso(process_number: str, empresa: Optional[str] = None):
    try:
        filas, product_options = _parse_process_json(process_number, empresa=empresa)
    except MySQLUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ProcessTableError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    if not filas:
        return {
            "ok": True,
            "process_number": process_number,
            "empresa": empresa,
            "rows": [],
            "message": "Sin filas para ese proceso.",
        }
    out_rows = _build_output_rows(filas)

    return {
        "ok": True,
        "process_number": process_number,
        "empresa": empresa,
        "rows": out_rows,
        "product_options": product_options,
        "debug": {
            "filas": len(out_rows),
        },
    }


@app.post("/api/csv")
def post_csv(payload: Dict[str, Any]):
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="payload.rows debe ser una lista")

    # Columnas dinámicas para otros impuestos extra agregados en la UI
    dyn_otro_monto: List[str] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        for k in r.keys():
            if not isinstance(k, str):
                continue
            # Solo montos dinámicos N>=2 (evita duplicar "otros_impuestos_monto" que ya está en OUTPUT_HEADERS)
            if k.startswith("otros_impuestos_") and k.endswith("_monto"):
                if k == "otros_impuestos_monto":
                    continue
                # otros_impuestos_<N>_monto
                parts = k.split("_")
                if len(parts) >= 4:
                    try:
                        n = int(parts[2])
                    except Exception:
                        n = None
                    if n is not None and n >= 2:
                        dyn_otro_monto.append(k)
    # orden estable: por N, luego por nombre
    def _otro_sort_key(s: str):
        try:
            n = int(s.split("_")[2])
        except Exception:
            n = 10**9
        return (n, s)

    dyn_otro_monto = sorted(set(dyn_otro_monto), key=_otro_sort_key)

    def _otros_name_key_for_monto_monto(monto_key: str) -> Optional[str]:
        parts = monto_key.split("_")
        if len(parts) < 4 or parts[-1] != "monto":
            return None
        try:
            n = int(parts[2])
        except Exception:
            return None
        if n < 2:
            return None
        return f"otros_impuestos_{n}"

    def _dyn_monto_used(monto_key: str) -> bool:
        nk = _otros_name_key_for_monto_monto(monto_key)
        if nk is None:
            return False
        for row in rows:
            if not isinstance(row, dict):
                continue
            if _normalize(row.get(monto_key)) or _normalize(row.get(nk)):
                return True
        return False

    dyn_otro_monto = [k for k in dyn_otro_monto if _dyn_monto_used(k)]

    base_headers = list(OUTPUT_HEADERS)
    csv_base_headers = _csv_export_headers(base_headers)
    headers = [*csv_base_headers, *dyn_otro_monto, CSV_EXPORT_TAX_IDS_HEADER]

    export_rows = _rows_prepared_for_odoo_csv(rows)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in export_rows:
        if not isinstance(r, dict):
            continue
        base_row = [_csv_export_cell(r, h) for h in base_headers]
        dyn_monto_row = [_csv_export_cell(r, h) for h in dyn_otro_monto]
        tax_ids_cell = build_csv_tax_ids_dot_id(r)
        w.writerow([*base_row, *dyn_monto_row, tax_ids_cell])
    buf.seek(0)

    content = buf.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="resultado.csv"'},
    )

