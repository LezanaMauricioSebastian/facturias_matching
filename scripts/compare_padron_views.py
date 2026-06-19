#!/usr/bin/env python3
"""Compare view_padron_facturia vs view_padron_facturia_actualizado (schema + metrics)."""
import json
from typing import Any, Dict, List, Optional

from psycopg2 import connect

from facturia_matching.config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_SCHEMA, DB_USER

VIEWS = ["view_padron_facturia", "view_padron_facturia_actualizado"]

PADRON_FIELD_COLUMNS = {
    "name": "nombre_contacto",
    "doc": "numero_documento",
    "rubro": "rubro",
    "diario": "diario",
    "cuenta": "cuenta_contable_completo",
    "tipo_documento": "tipo_documento",
}


def _pg_conn():
    return connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
    )


def _detect_padron_fields(cols: List[str]) -> Dict[str, Optional[str]]:
    cols_set = set(cols)
    return {
        key: col_name if col_name in cols_set else None
        for key, col_name in PADRON_FIELD_COLUMNS.items()
    }


def get_columns(view_name: str):
    with _pg_conn() as conn:
        with conn.cursor() as cur:
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
                (DB_SCHEMA, view_name),
            )
            return [r[0] for r in cur.fetchall()]


def get_metrics(view_name: str, name_col: Optional[str]):
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT COUNT(*) FROM "{DB_SCHEMA}"."{view_name}"'
            )
            total = cur.fetchone()[0]
            distinct_names = None
            if name_col:
                cur.execute(
                    f'''
                    SELECT COUNT(DISTINCT trim(CAST("{name_col}" AS text)))
                    FROM "{DB_SCHEMA}"."{view_name}"
                    WHERE "{name_col}" IS NOT NULL AND trim(CAST("{name_col}" AS text)) <> ''
                    '''
                )
                distinct_names = cur.fetchone()[0]
            return {"row_count": total, "distinct_proveedores": distinct_names}


def compare():
    results = {}
    for view in VIEWS:
        try:
            cols = get_columns(view)
        except Exception as e:
            results[view] = {"error": str(e)}
            continue
        detected = _detect_padron_fields(cols)
        name_col = detected.get("name")

        try:
            metrics = get_metrics(view, name_col)
        except Exception as e:
            metrics = {"error": str(e)}

        results[view] = {
            "columns": cols,
            "column_count": len(cols),
            "detected_fields": detected,
            "name_column_used": name_col,
            "metrics": metrics,
        }

    if len(results) == 2 and "columns" in results.get(VIEWS[0], {}) and "columns" in results.get(VIEWS[1], {}):
        c0 = set(results[VIEWS[0]]["columns"])
        c1 = set(results[VIEWS[1]]["columns"])
        results["diff"] = {
            "only_in_old": sorted(c0 - c1),
            "only_in_new": sorted(c1 - c0),
            "shared": sorted(c0 & c1),
        }

    return results


if __name__ == "__main__":
    out = compare()
    print(json.dumps(out, indent=2, ensure_ascii=False))
