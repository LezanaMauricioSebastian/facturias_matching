"""Map FacturIA company_id (?empresa=N) → Odoo profile según PROCESS_SCHEMA."""

import logging
from typing import Any, Dict, Optional

from facturia_matching.infra.config import resolve_process_schema
from facturia_matching.infra.env import env_strip as _env_strip

logger = logging.getLogger(__name__)

# sudataco_facturia (prod) — companies.id en MySQL
_PROD_EMPRESA_ODOO_PROFILE: Dict[str, str] = {
    "1": "default",  # Dinner
    "4": "aliare",  # Aliare
    "5": "aliare",  # Central Ticket
    "6": "aliare",  # Decastillo
    "7": "sudata",  # Sudata
}

# sudataco_staging (dev)
_STAGING_EMPRESA_ODOO_PROFILE: Dict[str, str] = {
    "1": "default",  # Dinner
    "3": "sudata",  # Sudata
}


def _parse_env_map(raw: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for part in raw.split(","):
        piece = part.strip()
        if not piece:
            continue
        if "=" in piece:
            k, v = piece.split("=", 1)
        elif ":" in piece:
            k, v = piece.split(":", 1)
        else:
            continue
        k = k.strip()
        v = v.strip().lower()
        if k and v in ("default", "aliare", "sudata"):
            out[k] = v
    return out


def empresa_odoo_profile_map(schema: Optional[str] = None) -> Dict[str, str]:
    """empresa (str) → odoo profile. Override opcional: EMPRESA_ODOO_PROFILE_MAP=1=default,4=aliare."""
    override = _env_strip("EMPRESA_ODOO_PROFILE_MAP")
    if override:
        return _parse_env_map(override)
    resolved = resolve_process_schema(schema)
    if resolved == "sudataco_staging":
        return dict(_STAGING_EMPRESA_ODOO_PROFILE)
    return dict(_PROD_EMPRESA_ODOO_PROFILE)


def resolve_odoo_profile_from_empresa(
    empresa: Optional[Any],
    schema: Optional[str] = None,
) -> Optional[str]:
    if empresa is None or str(empresa).strip() == "":
        return None
    return empresa_odoo_profile_map(schema).get(str(empresa).strip())


_FALLBACK_EMPRESA_LABELS: Dict[str, str] = {
    "1": "Odoo Dinner",
    "3": "Odoo Sudata",
    "4": "Odoo Aliare",
    "5": "Odoo Central Ticket",
    "6": "Odoo Decastillo",
    "7": "Odoo Sudata",
}


def _profile_display_label(profile: str) -> str:
    if profile == "aliare":
        return "Odoo Aliare"
    if profile == "sudata":
        return "Odoo Sudata"
    return "Odoo Dinner"


def empresa_odoo_display_labels(schema: Optional[str] = None) -> Dict[str, str]:
    """empresa id → etiqueta UI (ej. Odoo Central Ticket). Lee companies en MySQL."""
    resolved = resolve_process_schema(schema)
    try:
        from facturia_matching.infra.config import (
            _mysql_table_ref,
            get_mysql_connection,
        )

        table_ref = _mysql_table_ref(resolved, "companies")
        conn = get_mysql_connection()
        try:
            cur = conn.cursor(dictionary=True)
            try:
                cur.execute(
                    f"""
                    SELECT id, name, fantasy_name
                    FROM {table_ref}
                    WHERE deleted_at IS NULL
                    ORDER BY id
                    """
                )
                rows = cur.fetchall() or []
            finally:
                cur.close()
        finally:
            conn.close()
        out: Dict[str, str] = {}
        for row in rows:
            cid = row.get("id")
            if cid is None:
                continue
            label = (row.get("fantasy_name") or row.get("name") or "").strip()
            if label:
                out[str(int(cid))] = f"Odoo {label}"
        if out:
            return out
    except Exception as e:
        logger.debug("empresa_odoo_display_labels(%s): %s", resolved, e)
    return dict(_FALLBACK_EMPRESA_LABELS)


def resolve_odoo_display_label(
    empresa: Optional[Any],
    profile: Optional[str] = None,
    schema: Optional[str] = None,
) -> str:
    key = str(empresa or "").strip()
    if key:
        label = empresa_odoo_display_labels(schema).get(key)
        if label:
            return label
    return _profile_display_label(profile or "default")

