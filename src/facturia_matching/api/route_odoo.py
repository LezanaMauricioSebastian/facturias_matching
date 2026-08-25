"""Rutas de health Odoo e import."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from facturia_matching.api.profile import (
    _public_health_payload,
    _resolve_request_odoo_profile,
    _with_odoo_profile,
)
from facturia_matching.odoo.api import (
    _jsonrpc_url,
    get_active_odoo_config,
    get_odoo_import_config,
    is_odoo_config_ready,
    odoo_xmlrpc_version,
    verify_odoo_config_connection,
)
from facturia_matching.odoo.env import (
    current_odoo_profile,
    is_odoo_aliare_profile,
    is_odoo_sudata_profile,
)
from facturia_matching.odoo.import_ import import_rows_to_odoo

router = APIRouter()


@router.get("/api/odoo/health")
def odoo_health(
    empresa: Optional[str] = Query(None),
    perfil: Optional[str] = Query(None),
    odoo_profile_q: Optional[str] = Query(None, alias="odoo_profile_test"),
    odoo_cloud: Optional[str] = Query(None),
):
    odoo_profile = _resolve_request_odoo_profile(
        perfil, odoo_profile_q, odoo_cloud, empresa=empresa
    )

    def _health():
        cfg = get_active_odoo_config()
        if not is_odoo_config_ready(cfg):
            return {
                "ok": False,
                "error": "Odoo no configurado (ni company_erp_credentials ni ODOO_* en .env)",
                "credential_source": cfg.get("credential_source") or "none",
                "odoo_profile": current_odoo_profile(),
            }
        verified = verify_odoo_config_connection(cfg)
        if not verified.get("ok"):
            return _public_health_payload(
                {
                    **verified,
                    "jsonrpc_url": _jsonrpc_url(),
                    "odoo_profile": current_odoo_profile(),
                    "credential_source": cfg.get("credential_source"),
                }
            )
        return {
            "ok": True,
            "db": cfg.get("db"),
            "base_url": cfg.get("base_url"),
            "jsonrpc_url": _jsonrpc_url(),
            "odoo_profile": current_odoo_profile(),
            "credential_source": cfg.get("credential_source"),
            "version": verified.get("version") or odoo_xmlrpc_version(),
        }

    return _with_odoo_profile(odoo_profile, _health, empresa=empresa)


@router.get("/api/odoo/health/import")
def odoo_health_import(
    empresa: Optional[str] = Query(None),
    perfil: Optional[str] = Query(None),
    odoo_profile_q: Optional[str] = Query(None, alias="odoo_profile_test"),
    odoo_cloud: Optional[str] = Query(None),
):
    odoo_profile = _resolve_request_odoo_profile(
        perfil, odoo_profile_q, odoo_cloud, empresa=empresa
    )

    def _health_import():
        from facturia_matching.odoo.env import _aliare_secret, _sudata_secret

        config = get_odoo_import_config()
        if not is_odoo_config_ready(config):
            if is_odoo_sudata_profile():
                err = (
                    "Faltan variables Odoo Sudata (ODOO_BASE_URL_SUDATA o URL_SUDATA, "
                    "ODOO_USER_SUDATA o USERNAME_SUDATA, y ODOO_API_KEY_SUDATA u ODOO_PASSWORD_SUDATA; "
                    "ODOO_DB_SUDATA o DB_SUDATA opcional) "
                    "o credenciales en company_erp_credentials para la empresa."
                )
            elif is_odoo_aliare_profile():
                err = (
                    "Faltan variables Odoo Aliare (ODOO_BASE_URL_ALIARE, "
                    "ODOO_USER_ALIARE u ODOO_USER_ID_ALIARE con email, y ODOO_API_KEY_ALIARE u ODOO_PASSWORD_ALIARE; "
                    "ODOO_DB_ALIARE opcional si hay una sola base o coincide con el host) "
                    "o credenciales en company_erp_credentials para la empresa."
                )
            else:
                err = (
                    "Faltan variables Odoo Dinner (ODOO_BASE_URL, "
                    "ODOO_USER_ID u ODOO_USER, y ODOO_PASSWORD u ODOO_API_KEY; "
                    "ODOO_DB opcional si hay una sola base) "
                    "o credenciales en company_erp_credentials para la empresa."
                )
            return {"ok": False, "error": err}
        credential_source = config.get("credential_source") or "env"
        if credential_source == "env":
            if is_odoo_sudata_profile():
                _, credential_source = _sudata_secret()
            elif is_odoo_aliare_profile():
                _, credential_source = _aliare_secret()
            else:
                from facturia_matching.infra.env import env_strip

                if env_strip("ODOO_API_KEY"):
                    credential_source = "ODOO_API_KEY"
                elif env_strip("ODOO_PASSWORD"):
                    credential_source = "ODOO_PASSWORD"
                else:
                    credential_source = "none"
        result = verify_odoo_config_connection(config)
        result["credential_source"] = credential_source
        result["profile"] = current_odoo_profile()
        if config.get("company_id") is not None:
            result["company_id"] = config.get("company_id")
        return _public_health_payload(result)

    return _with_odoo_profile(odoo_profile, _health_import, empresa=empresa)


@router.get("/api/odoo/health/credenciales_db")
def odoo_health_credenciales_db(
    empresa: Optional[str] = Query(
        None,
        description="Si se omite, prueba todas las credenciales activas del PROCESS_SCHEMA.",
    ),
):
    """
    Health solo contra `company_erp_credentials` (+ configs). No usa .env.
    Errores: respuesta mínima `{"ok": false, "error": "..."}`.
    """
    from facturia_matching.infra.config import PROCESS_SCHEMA
    from facturia_matching.odoo.env import _config_from_credential_map
    from facturia_matching.persistence.company_erp_credentials import (
        list_active_company_odoo_credentials,
    )

    def _err(msg: str) -> Dict[str, Any]:
        return {"ok": False, "error": msg}

    def _missing_fields(cfg: Dict[str, Any], kv: Dict[str, str]) -> list:
        missing = []
        if not (cfg.get("base_url") or kv.get("ODOO_BASE_URL")):
            missing.append("ODOO_BASE_URL")
        if not (kv.get("ODOO_PASSWORD") or kv.get("ODOO_API_KEY")):
            missing.append("ODOO_PASSWORD|ODOO_API_KEY")
        if not (cfg.get("login") or cfg.get("uid") is not None):
            missing.append("ODOO_USER_ID|ODOO_USER")
        if not cfg.get("db"):
            missing.append("ODOO_DB (no se pudo deducir)")
        return missing

    rows = list_active_company_odoo_credentials(company_id=empresa)
    if not rows:
        scope = f" para empresa={empresa}" if empresa else ""
        return _err(
            f"No hay credenciales activas en company_erp_credentials{scope} "
            f"(schema={PROCESS_SCHEMA})."
        )

    results: list = []
    errors: list = []
    for row in rows:
        company_id = row.get("company_id")
        label = row.get("company_name") or f"company_id={company_id}"
        kv = row.get("config") or {}
        cfg = _config_from_credential_map(kv, company_id=company_id)
        if not is_odoo_config_ready(cfg):
            missing = _missing_fields(cfg, kv)
            msg = (
                f"{label}: falta {', '.join(missing)}"
                if missing
                else f"{label}: credencial incompleta en tablas"
            )
            errors.append(msg)
            continue
        verified = verify_odoo_config_connection(cfg)
        if not verified.get("ok"):
            detail = verified.get("error") or verified.get("hint") or "conexión fallida"
            errors.append(f"{label}: {detail}")
            continue
        results.append(
            {
                "ok": True,
                "company_id": company_id,
                "company_name": row.get("company_name"),
            }
        )

    if errors:
        return _err("; ".join(errors))

    if len(results) == 1:
        return results[0]
    return {"ok": True, "count": len(results), "results": results}


@router.post("/api/odoo/health/credenciales")
def odoo_health_credenciales(payload: Dict[str, Any]):
    """
    Valida credenciales Odoo del body **antes de guardar** en MySQL.
    No lee `company_erp_credentials` ni `.env`.

    Body: keys `ODOO_*` (planas o en `config`), mismas que `company_erp_credential_configs`.
    Errores: `{"ok": false, "error": "..."}`.
    """
    from facturia_matching.odoo.env import _config_from_credential_map
    from facturia_matching.persistence.company_erp_credentials import ODOO_CONFIG_KEYS

    def _err(msg: str) -> Dict[str, Any]:
        return {"ok": False, "error": msg}

    if not isinstance(payload, dict):
        return _err("Body JSON inválido.")

    raw = payload.get("config") if isinstance(payload.get("config"), dict) else payload
    kv: Dict[str, str] = {}
    for key in ODOO_CONFIG_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if s:
            kv[key] = s

    if not kv:
        return _err(
            "Faltan credenciales en el body "
            "(ODOO_BASE_URL, ODOO_USER_ID|ODOO_USER, ODOO_PASSWORD|ODOO_API_KEY; ODOO_DB opcional)."
        )

    company_id = payload.get("company_id") or payload.get("empresa") or raw.get("company_id")
    cfg = _config_from_credential_map(kv, company_id=company_id if company_id is not None else 0)

    missing = []
    if not (cfg.get("base_url") or kv.get("ODOO_BASE_URL")):
        missing.append("ODOO_BASE_URL")
    if not (kv.get("ODOO_PASSWORD") or kv.get("ODOO_API_KEY")):
        missing.append("ODOO_PASSWORD|ODOO_API_KEY")
    if not (cfg.get("login") or cfg.get("uid") is not None):
        missing.append("ODOO_USER_ID|ODOO_USER")
    if not cfg.get("db"):
        missing.append("ODOO_DB (no se pudo deducir)")
    if missing:
        return _err(f"Falta {', '.join(missing)}")

    if not is_odoo_config_ready(cfg):
        return _err("Credencial incompleta.")

    verified = verify_odoo_config_connection(cfg)
    if not verified.get("ok"):
        detail = verified.get("error") or verified.get("hint") or "conexión fallida"
        return _err(detail)

    out: Dict[str, Any] = {"ok": True}
    if company_id is not None and str(company_id).strip() != "":
        out["company_id"] = (
            int(company_id) if str(company_id).strip().isdigit() else company_id
        )
    if verified.get("db"):
        out["db"] = verified.get("db")
    return out


@router.post("/api/odoo/import")
def odoo_import(
    payload: Dict[str, Any],
    perfil: Optional[str] = Query(None),
    odoo_profile_q: Optional[str] = Query(None, alias="odoo_profile_test"),
    odoo_cloud: Optional[str] = Query(None),
):
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="payload.rows debe ser una lista")
    skip_duplicates = payload.get("skip_duplicates", True)
    update_taxes_if_exists = payload.get("update_taxes_if_exists", True)
    empresa = payload.get("empresa")
    odoo_profile = _resolve_request_odoo_profile(perfil, odoo_profile_q, odoo_cloud, payload)

    def _import():
        return import_rows_to_odoo(
            rows,
            skip_duplicates=bool(skip_duplicates),
            update_taxes_if_exists=bool(update_taxes_if_exists),
        )

    return _with_odoo_profile(odoo_profile, _import, empresa=empresa)
