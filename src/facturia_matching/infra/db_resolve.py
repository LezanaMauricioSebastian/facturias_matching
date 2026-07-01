"""Resolución de nombres de base cuando el cliente solo entrega host + credenciales."""

from __future__ import annotations

import logging
from typing import List, Optional

from psycopg2 import connect

logger = logging.getLogger(__name__)


def resolved_pg_dbname(
    configured: Optional[str],
    user: Optional[str],
    *,
    host: Optional[str] = None,
    port: Optional[str] = None,
    password: Optional[str] = None,
) -> Optional[str]:
    """
    DB_NAME explícito, única base no-template accesible,
    o el usuario Postgres (convención habitual).
    """
    explicit = (configured or "").strip()
    if explicit:
        return explicit
    if host and user and password:
        discovered = _discover_single_pg_database(host, port or "5432", user, password)
        if discovered:
            return discovered
    user_db = (user or "").strip()
    if user_db:
        return user_db
    return None


def _discover_single_pg_database(
    host: str,
    port: str,
    user: str,
    password: str,
) -> Optional[str]:
    try:
        conn = connect(
            host=host,
            port=int(port),
            user=user,
            password=password,
            dbname="postgres",
        )
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT datname
                FROM pg_database
                WHERE datistemplate = false
                  AND datallowconn
                ORDER BY datname
                """
            )
            names = [str(r[0]) for r in cur.fetchall() if r and r[0]]
            if len(names) == 1:
                return names[0]
        finally:
            conn.close()
    except Exception as e:
        logger.debug("No se pudo listar bases Postgres en %s: %s", host, e)
    return None


def mysql_connect_kwargs(
    host: Optional[str],
    user: Optional[str],
    password: Optional[str],
    port: int,
    database: Optional[str],
) -> dict:
    """MySQL sin `database` si no está configurado (queries con schema.tabla calificado)."""
    kwargs = {
        "host": host,
        "user": user,
        "password": password,
        "port": port,
    }
    db = (database or "").strip()
    if db:
        kwargs["database"] = db
    return kwargs
