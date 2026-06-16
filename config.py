import os
from psycopg2 import connect
from mysql.connector import connect as connect_mysql
from mysql.connector.errors import Error
import dotenv

_here = os.path.dirname(__file__)
dotenv.load_dotenv(os.path.join(_here, ".env"))


def _env_strip(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    if not val:
        return ""
    s = str(val).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        s = s[1:-1].strip()
    return s


DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
DB_TABLE_NAME = os.getenv("DB_TABLE_NAME")

DB_HOST_MYSQL = os.getenv("DB_HOST_MYSQL")
DB_USER_MYSQL = os.getenv("DB_USER_MYSQL")
DB_PASSWORD_MYSQL = os.getenv("DB_PASSWORD_MYSQL")
DB_NAME_MYSQL = os.getenv("DB_NAME_MYSQL")

# Backwards-compatible with existing `.env` keys used in this repo
DB_HOST_MYSQL = (DB_HOST_MYSQL or os.getenv("DB_HOST_mysql") or "").strip() or None
DB_USER_MYSQL = (DB_USER_MYSQL or os.getenv("DB_USER_mysql") or "").strip() or None
DB_PASSWORD_MYSQL = (DB_PASSWORD_MYSQL or os.getenv("DB_PASSWORD_mysql") or "").strip() or None
DB_NAME_MYSQL = (DB_NAME_MYSQL or os.getenv("DB_NAME_mysql") or "").strip() or None
DB_PORT_MYSQL = (os.getenv("DB_PORT_MYSQL") or os.getenv("DB_PORT_mysql") or "3306").strip()
try:
    DB_PORT_MYSQL = int(DB_PORT_MYSQL)
except ValueError:
    DB_PORT_MYSQL = 3306
DB_URL_MYSQL = f"mysql://{DB_USER_MYSQL}:{DB_PASSWORD_MYSQL}@{DB_HOST_MYSQL}:{DB_PORT_MYSQL}/{DB_NAME_MYSQL}"


def get_mysql_connection():
    return connect_mysql(
        host=DB_HOST_MYSQL,
        user=DB_USER_MYSQL,
        password=DB_PASSWORD_MYSQL,
        database=DB_NAME_MYSQL,
        port=DB_PORT_MYSQL,
    )


def _mysql_table_ref(schema: str, table: str) -> str:
    schema = (schema or "").replace("`", "")
    table = (table or "").replace("`", "")
    return f"`{schema}`.`{table}`" if schema else f"`{table}`"


def mysql_fetchall(query: str, params=None):
    conn = get_mysql_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(query, params or ())
            return cur.fetchall()
        finally:
            cur.close()
    finally:
        conn.close()
def check_db_connection_mysql():
    """ function that checks the connection to the database """
    try:
        conn = get_mysql_connection()
        conn.close()
        return True
    except Error as e:
        print(e)
        return False
    except Exception as e:
        print(e)
        return False
# Odoo API (JSON-RPC / XML-RPC) — catálogos del tenant del cliente
# uid: ODOO_USER_ID numérico → se usa directo en execute_kw (sin authenticate).
# login: ODOO_USER (email) → solo si no hay uid, vía common.authenticate.
_odo_uid_raw = _env_strip("ODOO_USER_ID")
try:
    ODOO_UID = int(_odo_uid_raw) if _odo_uid_raw else None
except ValueError:
    ODOO_UID = None

ODOO_CONFIG = {
    "base_url": _env_strip("ODOO_BASE_URL", "https://dinner.odoo.com").rstrip("/"),
    "endpoint": (_env_strip("ODOO_ENDPOINT", "/jsonrpc").lstrip("/") or "jsonrpc"),
    "db": _env_strip("ODOO_DB"),
    "uid": ODOO_UID,
    "login": _env_strip("ODOO_USER"),
    "password": _env_strip("ODOO_PASSWORD"),
}

ODOO_CATALOG_CACHE_TTL = int(_env_strip("ODOO_CATALOG_CACHE_TTL", "600") or "600")
# Opcionales: solo se usan si están definidos en .env (sin valor por defecto en código)
DEFAULT_JOURNAL_NAME = _env_strip("DEFAULT_JOURNAL_NAME")
DEFAULT_RUBRO_NAME = _env_strip("DEFAULT_RUBRO_NAME")

def check_db_connection():
    """ function that checks the connection to the database """
    try:
        conn = connect(DB_URL)
        conn.close()
        print("Connection to the database successful")
        return True
    except Exception as e:
        print(e)
        return False

def get_tables():
    """ function that gets the tables in the database """
    try:
        conn = connect(DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        tables = cur.fetchall()
        return tables
    except Exception as e:
        print(e)
        return None

def check_table_exists(table):
    """ function that checks if the table exists in the database """
    try:

        conn = connect(DB_URL)
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM information_schema.tables WHERE table_schema = 'public' AND table_name = '{table}'")
        table_exists = cur.fetchall()
        return table_exists
    except Exception as e:
        print(e)
        return None

def get_table_columns(table, schema=None):
    """Columnas de una tabla/vista Postgres (incluye materialized views vía pg_catalog)."""
    schema = (schema or os.getenv("DB_SCHEMA", "public") or "public").strip()
    table = (table or "").strip()
    if not table:
        return None
    try:
        conn = connect(DB_URL)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (schema, table),
        )
        cols = [r[0] for r in cur.fetchall()]
        if cols:
            return [(c,) for c in cols]
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
            (schema, table),
        )
        return [(r[0],) for r in cur.fetchall()]
    except Exception as e:
        print(e)
        return None
def get_table_data(table,max=5):
    """ function that gets the data in the table """
    try:
        conn = connect(DB_URL)
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM public.{table} LIMIT {max}")
        data = cur.fetchall()
        return data
    except Exception as e:
        print(e)
        return None
def get_mysql_table_columns(table="process", schema="sudataco_facturia") -> list[str]:
    """Nombres de columnas de una tabla MySQL (information_schema)."""
    try:
        rows = mysql_fetchall(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (schema, table),
        )
        return [r[0] for r in (rows or [])]
    except Exception as e:
        print(e)
        return []


if __name__ == "__main__":
    print(get_mysql_table_columns())