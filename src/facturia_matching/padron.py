"""Padrón Postgres: column detection, cache and proveedor matching."""

from typing import Any, Dict, List, Optional, Tuple

from psycopg2 import connect
from psycopg2.extras import RealDictCursor
from psycopg2.sql import Identifier, SQL
from rapidfuzz import fuzz, process as rf_process

from facturia_matching.config import (
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_SCHEMA,
    DB_TABLE_NAME,
    DB_TABLE_NAME_FALLBACK,
    DB_USER,
    PADRON_FUZZY_MIN_SCORE,
    PADRON_LIMIT,
    get_table_columns as cfg_get_table_columns,
)
from facturia_matching.utils import normalize

PADRON_FIELD_COLUMNS = {
    "name": "nombre_contacto",
    "doc": "numero_documento",
    "rubro": "rubro",
    "diario": "diario",
    "cuenta": "cuenta_contable_completo",
    "cuenta_codigo": "codigo_cuenta_contable",
    "cuenta_nombre": "cuenta_contable",
    "tipo_documento": "tipo_documento",
    "etiqueta": "etiqueta",
    "invoice_line_ids_name": "invoice_line_ids_name",
}

_LINE_LABEL_COLUMN_CANDIDATES = (
    "etiqueta",
    "invoice_line_ids_name",
    "nombre_linea",
    "linea_factura",
)

_PADRON_CACHE: Optional[List[Dict[str, Any]]] = None
_PADRON_FALLBACK_CACHE: Optional[List[Dict[str, Any]]] = None


def reset_padron_cache() -> None:
    global _PADRON_CACHE, _PADRON_FALLBACK_CACHE
    _PADRON_CACHE = None
    _PADRON_FALLBACK_CACHE = None


def pg_conn():
    if not (DB_HOST and DB_USER and DB_PASSWORD and DB_NAME):
        raise ValueError("Faltan variables de entorno de Postgres (DB_HOST/DB_USER/DB_PASSWORD/DB_NAME).")
    return connect(
        host=DB_HOST,
        port=int(DB_PORT),
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
    )


def table_ident(table_name: Optional[str] = None) -> SQL:
    return SQL("{}.{}").format(Identifier(DB_SCHEMA), Identifier((table_name or DB_TABLE_NAME).strip()))


def odoo_table_ident(table: str, schema: str = "public") -> SQL:
    schema = (schema or "public").strip() or "public"
    table = (table or "").strip()
    return SQL("{}.{}").format(Identifier(schema), Identifier(table))


def get_table_columns() -> List[str]:
    if DB_SCHEMA.lower() == "public":
        cols = cfg_get_table_columns(DB_TABLE_NAME) or []
        out = []
        for c in cols:
            if isinstance(c, (list, tuple)) and c:
                out.append(str(c[0]))
            elif c:
                out.append(str(c))
        if out:
            return out
    with pg_conn() as conn:
        with conn.cursor() as cur:
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


def detect_padron_fields(cols: List[str]) -> Dict[str, Optional[str]]:
    cols_set = set(cols)
    return {
        key: col_name if col_name in cols_set else None
        for key, col_name in PADRON_FIELD_COLUMNS.items()
    }


def detect_line_label_column(cols: List[str]) -> Optional[str]:
    fields = detect_padron_fields(cols)
    for key in _LINE_LABEL_COLUMN_CANDIDATES:
        col = fields.get(key)
        if col:
            return col
    return None


def get_table_columns_for(table_name: str) -> List[str]:
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
    with pg_conn() as conn:
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


def padron_rows(table_name: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    table_name = (table_name or DB_TABLE_NAME).strip()
    if limit is None:
        limit = PADRON_LIMIT
    cols = get_table_columns_for(table_name) if table_name != DB_TABLE_NAME else get_table_columns()
    fields = detect_padron_fields(cols)
    name_col = fields.get("name")
    if not name_col:
        try:
            with pg_conn() as conn:
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
                    ).format(t=odoo_table_ident("res_partner", "public"), lim=SQL(str(int(limit))))
                    cur.execute(q)
                    return list(cur.fetchall())
        except Exception:
            return []

    table_ident_sql = table_ident(table_name)
    select_items: List[SQL] = [SQL("{} AS {}").format(Identifier(name_col), Identifier("name"))]
    for key in ["doc", "rubro", "diario", "tipo_documento"]:
        col = fields.get(key)
        if col:
            select_items.append(SQL("{} AS {}").format(Identifier(col), Identifier(key)))
    codigo_col = fields.get("cuenta_codigo")
    nombre_col = fields.get("cuenta_nombre")
    cuenta_col = fields.get("cuenta")
    if codigo_col and nombre_col:
        select_items.append(
            SQL(
                "trim(CAST({} AS text)) || ' ' || trim(CAST({} AS text)) AS cuenta"
            ).format(Identifier(codigo_col), Identifier(nombre_col))
        )
    elif cuenta_col:
        select_items.append(SQL("{} AS cuenta").format(Identifier(cuenta_col)))

    with pg_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            select_sql = SQL(", ").join(select_items)
            q = SQL("SELECT {} FROM {} WHERE {} IS NOT NULL AND trim({}) <> '' LIMIT {}").format(
                select_sql,
                table_ident_sql,
                Identifier(name_col),
                Identifier(name_col),
                SQL(str(int(limit))),
            )
            cur.execute(q)
            return list(cur.fetchall())


def get_padron_cached() -> List[Dict[str, Any]]:
    global _PADRON_CACHE
    if _PADRON_CACHE is None:
        try:
            _PADRON_CACHE = padron_rows()
        except Exception:
            _PADRON_CACHE = []
    return _PADRON_CACHE


def get_padron_fallback_cached() -> List[Dict[str, Any]]:
    global _PADRON_FALLBACK_CACHE
    if _PADRON_FALLBACK_CACHE is None:
        if not DB_TABLE_NAME_FALLBACK or DB_TABLE_NAME_FALLBACK == DB_TABLE_NAME:
            _PADRON_FALLBACK_CACHE = []
        else:
            try:
                _PADRON_FALLBACK_CACHE = padron_rows(DB_TABLE_NAME_FALLBACK)
            except Exception:
                _PADRON_FALLBACK_CACHE = []
    return _PADRON_FALLBACK_CACHE


def padron_row_from_cuit(padron: List[Dict[str, Any]], cuit_n: str) -> Optional[Dict[str, Any]]:
    if not cuit_n:
        return None
    for r in padron:
        doc = "".join(ch for ch in normalize(r.get("doc")) if ch.isdigit())
        if doc and doc == cuit_n:
            return r
    return None


def tuple_from_padron_row(r: Dict[str, Any], score: float) -> Tuple[str, str, str, str, float]:
    return (
        normalize(r.get("name")),
        normalize(r.get("rubro")),
        normalize(r.get("diario")),
        normalize(r.get("cuenta")),
        score,
    )


def padron_name_score(query: str, choice: str, **_: Any) -> float:
    q = normalize(query).upper()
    c = normalize(choice).upper()
    if not q or not c:
        return 0.0
    ts = float(fuzz.token_set_ratio(q, c))
    pr = float(fuzz.partial_ratio(q, c))
    return max(ts, 0.55 * ts + 0.45 * pr)


def match_proveedor(nombre: str, cuit: str) -> Tuple[str, str, str, str, float]:
    nombre_n = normalize(nombre)
    cuit_n = "".join(ch for ch in normalize(cuit) if ch.isdigit())

    for padron in (get_padron_cached(), get_padron_fallback_cached()):
        hit = padron_row_from_cuit(padron, cuit_n)
        if hit:
            return tuple_from_padron_row(hit, 100.0)

    padron = get_padron_cached()
    names = [(normalize(r.get("name")), r) for r in padron]
    choices = [n for n, _ in names]
    if not nombre_n or not choices:
        return ("", "", "", "", 0.0)

    best = rf_process.extractOne(nombre_n, choices, scorer=padron_name_score)
    if not best:
        return ("", "", "", "", 0.0)
    score = float(best[1])
    idx = int(best[2])
    if score < PADRON_FUZZY_MIN_SCORE:
        return ("", "", "", "", 0.0)
    return tuple_from_padron_row(names[idx][1], score)
