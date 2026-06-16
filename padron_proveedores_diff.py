#!/usr/bin/env python3
"""Proveedores en vista vieja que no están en la nueva (por nombre_contacto)."""
import os

import dotenv
from psycopg2 import connect

_here = os.path.dirname(__file__)
dotenv.load_dotenv(os.path.join(_here, ".env"))

DB_SCHEMA = os.getenv("DB_SCHEMA", "public").strip() or "public"
OLD = "view_padron_facturia"
NEW = "view_padron_facturia_actualizado"
NAME_COL = "nombre_contacto"


def _pg_conn():
    return connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", "5432"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dbname=os.getenv("DB_NAME"),
    )


def distinct_names(view: str) -> set:
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'''
                SELECT DISTINCT trim(CAST("{NAME_COL}" AS text))
                FROM "{DB_SCHEMA}"."{view}"
                WHERE "{NAME_COL}" IS NOT NULL AND trim(CAST("{NAME_COL}" AS text)) <> ''
                '''
            )
            return {r[0] for r in cur.fetchall()}


if __name__ == "__main__":
    old = distinct_names(OLD)
    new = distinct_names(NEW)
    only_old = sorted(old - new)
    only_new = sorted(new - old)
    print(f"old={len(old)} new={len(new)} only_in_old={len(only_old)} only_in_new={len(only_new)}")
    print("\n--- Solo en vista vieja (primeros 30) ---")
    for n in only_old[:30]:
        print(n)
    print("\n--- Solo en vista nueva (primeros 30) ---")
    for n in only_new[:30]:
        print(n)
