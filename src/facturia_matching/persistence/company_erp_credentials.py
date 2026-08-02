"""Credenciales Odoo por empresa desde `company_erp_credentials` + configs.

Fuente preferida frente a variables `ODOO_*` del .env cuando hay fila activa
para el `company_id` (FacturIA) en el schema `PROCESS_SCHEMA`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Keys que guarda FacturIA en company_erp_credential_configs (ver erp_providers_config_data).
ODOO_CONFIG_KEYS = (
    "ODOO_BASE_URL",
    "ODOO_ENDPOINT",
    "ODOO_DB",
    "ODOO_USER_ID",
    "ODOO_USER",
    "ODOO_PASSWORD",
    "ODOO_API_KEY",
)


def _parse_company_id(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def fetch_company_odoo_credential_map(
    company_id: Any,
    *,
    schema: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """
    Devuelve mapa config_key → config_value para la credencial Odoo activa de la empresa.
    None si no hay fila / error (el caller hace fallback a .env).
    """
    # Lazy imports: evita ciclo config → env → persistence → config.
    from facturia_matching.infra.config import (
        PROCESS_SCHEMA,
        _mysql_table_ref,
        get_mysql_connection,
    )

    cid = _parse_company_id(company_id)
    if cid is None:
        return None
    resolved = (schema or PROCESS_SCHEMA or "").strip() or "sudataco_facturia"
    cred_ref = _mysql_table_ref(resolved, "company_erp_credentials")
    cfg_ref = _mysql_table_ref(resolved, "company_erp_credential_configs")
    prov_ref = _mysql_table_ref(resolved, "erp_providers")
    try:
        conn = get_mysql_connection()
    except Exception as e:
        logger.debug("fetch_company_odoo_credential_map connect: %s", e)
        return None
    try:
        cur = conn.cursor(dictionary=True)
        try:
            # Preferir provider cuyo nombre mencione Odoo; si no, cualquier credencial activa.
            cur.execute(
                f"""
                SELECT c.id AS credential_id
                FROM {cred_ref} c
                LEFT JOIN {prov_ref} p ON p.id = c.erp_provider_id
                WHERE c.company_id = %s
                  AND c.deleted_at IS NULL
                ORDER BY
                  CASE WHEN LOWER(COALESCE(p.name, '')) LIKE '%odoo%' THEN 0 ELSE 1 END,
                  c.id ASC
                LIMIT 1
                """,
                (cid,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cred_id = int(row["credential_id"])
            cur.execute(
                f"""
                SELECT config_key, config_value
                FROM {cfg_ref}
                WHERE company_erp_credential_id = %s
                """,
                (cred_id,),
            )
            out: Dict[str, str] = {}
            for cfg in cur.fetchall() or []:
                key = str(cfg.get("config_key") or "").strip()
                if not key:
                    continue
                val = cfg.get("config_value")
                out[key] = "" if val is None else str(val).strip()
            return out or None
        finally:
            cur.close()
    except Exception as e:
        logger.warning(
            "fetch_company_odoo_credential_map(company_id=%s, schema=%s): %s",
            cid,
            resolved,
            e,
        )
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def list_active_company_odoo_credentials(
    *,
    schema: Optional[str] = None,
    company_id: Optional[Any] = None,
) -> list[Dict[str, Any]]:
    """
    Lista credenciales Odoo activas (sin soft-delete).
    Cada item: credential_id, company_id, company_name, provider_name, name, config (map).
    """
    from facturia_matching.infra.config import (
        PROCESS_SCHEMA,
        _mysql_table_ref,
        get_mysql_connection,
    )

    resolved = (schema or PROCESS_SCHEMA or "").strip() or "sudataco_facturia"
    cred_ref = _mysql_table_ref(resolved, "company_erp_credentials")
    cfg_ref = _mysql_table_ref(resolved, "company_erp_credential_configs")
    prov_ref = _mysql_table_ref(resolved, "erp_providers")
    co_ref = _mysql_table_ref(resolved, "companies")
    cid = _parse_company_id(company_id)

    try:
        conn = get_mysql_connection()
    except Exception as e:
        logger.warning("list_active_company_odoo_credentials connect: %s", e)
        return []
    try:
        cur = conn.cursor(dictionary=True)
        try:
            params: list[Any] = []
            where = "c.deleted_at IS NULL"
            if cid is not None:
                where += " AND c.company_id = %s"
                params.append(cid)
            cur.execute(
                f"""
                SELECT
                  c.id AS credential_id,
                  c.company_id,
                  c.name AS credential_name,
                  co.name AS company_name,
                  p.name AS provider_name
                FROM {cred_ref} c
                LEFT JOIN {co_ref} co ON co.id = c.company_id
                LEFT JOIN {prov_ref} p ON p.id = c.erp_provider_id
                WHERE {where}
                ORDER BY
                  CASE WHEN LOWER(COALESCE(p.name, '')) LIKE '%odoo%' THEN 0 ELSE 1 END,
                  c.company_id ASC,
                  c.id ASC
                """,
                tuple(params),
            )
            rows = cur.fetchall() or []
            out: list[Dict[str, Any]] = []
            for row in rows:
                cred_id = int(row["credential_id"])
                cur.execute(
                    f"""
                    SELECT config_key, config_value
                    FROM {cfg_ref}
                    WHERE company_erp_credential_id = %s
                    """,
                    (cred_id,),
                )
                config: Dict[str, str] = {}
                for cfg in cur.fetchall() or []:
                    key = str(cfg.get("config_key") or "").strip()
                    if not key:
                        continue
                    val = cfg.get("config_value")
                    config[key] = "" if val is None else str(val).strip()
                out.append(
                    {
                        "credential_id": cred_id,
                        "company_id": int(row["company_id"]),
                        "company_name": (row.get("company_name") or "").strip() or None,
                        "provider_name": (row.get("provider_name") or "").strip() or None,
                        "name": (row.get("credential_name") or "").strip() or None,
                        "config": config,
                    }
                )
            return out
        finally:
            cur.close()
    except Exception as e:
        logger.warning("list_active_company_odoo_credentials(%s): %s", resolved, e)
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass
