"""Consulta procesos FacturIA en MySQL (sudataco_facturia.process)."""

from typing import Any, Dict, List, Optional

from config import get_mysql_connection, get_mysql_table_columns, _mysql_table_ref

PROCESS_TABLE = "process"
PROCESS_SCHEMA = "sudataco_facturia"
PROCESS_NUMBER_COL = "process_number"


def get_process(
    process_number,
    table: str = PROCESS_TABLE,
    schema: str = PROCESS_SCHEMA,
) -> Optional[Dict[str, Any]]:
    """Devuelve la fila del proceso como dict (columnas según information_schema)."""
    cols = get_mysql_table_columns(table, schema)
    if PROCESS_NUMBER_COL not in cols:
        raise ValueError(
            f"Columna {PROCESS_NUMBER_COL} no existe en {schema}.{table}: {cols}"
        )

    table_ref = _mysql_table_ref(schema, table)
    conn = get_mysql_connection()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                f"SELECT * FROM {table_ref} WHERE `{PROCESS_NUMBER_COL}` = %s",
                (process_number,),
            )
            row = cur.fetchone()
            return row if row else None
        finally:
            cur.close()
    finally:
        conn.close()


if __name__ == "__main__":
    print(get_process(185))
