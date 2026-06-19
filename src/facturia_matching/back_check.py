"""Consulta procesos FacturIA en MySQL (sudataco_facturia.process)."""

from typing import Any, Dict, List, Optional

from facturia_matching.config import get_mysql_connection, get_mysql_table_columns, _mysql_table_ref

PROCESS_TABLE = "process"
PROCESS_SCHEMA = "sudataco_facturia"
PROCESS_NUMBER_COL = "process_number"
EMPRESA_COL_CANDIDATES = (
    "empresa_id",
    "company_id",
    "nro_empresa",
    "numero_empresa",
    "company_number",
    "empresa",
    "id_empresa",
)


class MySQLUnavailableError(RuntimeError):
    """MySQL inaccesible o sin credenciales configuradas."""


class ProcessTableError(RuntimeError):
    """Tabla/columnas de proceso no encontradas en MySQL."""


def _find_empresa_column(cols: List[str]) -> Optional[str]:
    lower_map = {c.lower(): c for c in cols}
    for candidate in EMPRESA_COL_CANDIDATES:
        if candidate in lower_map:
            return lower_map[candidate]
    return None


def get_process(
    process_number,
    empresa: Optional[Any] = None,
    table: str = PROCESS_TABLE,
    schema: str = PROCESS_SCHEMA,
) -> Optional[Dict[str, Any]]:
    """Devuelve la fila del proceso como dict (columnas según information_schema)."""
    cols = get_mysql_table_columns(table, schema)
    if not cols:
        try:
            conn = get_mysql_connection()
            conn.close()
        except Exception as e:
            raise MySQLUnavailableError(
                "No se pudo conectar a MySQL. Configurá DB_HOST_MYSQL, DB_USER_MYSQL, "
                "DB_PASSWORD_MYSQL y DB_NAME_MYSQL en .env."
            ) from e
        raise ProcessTableError(f"No se encontró la tabla {schema}.{table} en MySQL.")
    if PROCESS_NUMBER_COL not in cols:
        raise ProcessTableError(
            f"Columna {PROCESS_NUMBER_COL} no existe en {schema}.{table}: {cols}"
        )

    conditions = [f"`{PROCESS_NUMBER_COL}` = %s"]
    params: List[Any] = [process_number]

    if empresa is not None and str(empresa).strip() != "":
        empresa_col = _find_empresa_column(cols)
        if empresa_col:
            conditions.append(f"`{empresa_col}` = %s")
            params.append(empresa)

    table_ref = _mysql_table_ref(schema, table)
    conn = get_mysql_connection()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                f"SELECT * FROM {table_ref} WHERE {' AND '.join(conditions)}",
                tuple(params),
            )
            row = cur.fetchone()
            return row if row else None
        finally:
            cur.close()
    finally:
        conn.close()


if __name__ == "__main__":
    print(get_process(185))
