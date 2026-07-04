"""
Cliente para la API de Odoo (XML-RPC y JSON-RPC).

Con ODOO_USER_ID + ODOO_PASSWORD se llama execute_kw directamente (uid numérico),
sin pasar por common.authenticate — patrón estándar de la API externa de Odoo.

Con ODOO_USER (login/email) se obtiene el uid vía authenticate/login.
"""

import logging
import random
import xmlrpc.client
from typing import Any, Dict, List, Optional, Tuple

import requests

from facturia_matching.infra.config import ODOO_CONFIG
from facturia_matching.odoo.env import (
    build_odoo_import_config,
    current_odoo_profile,
    get_odoo_main_config,
    resolve_odoo_lang,
)

logger = logging.getLogger(__name__)


def get_active_odoo_config() -> Dict[str, Any]:
    return get_odoo_main_config(current_odoo_profile())


def get_odoo_import_config() -> Dict[str, Any]:
    """Credenciales Odoo para import según perfil activo (misma instancia que health/catálogo)."""
    return build_odoo_import_config(current_odoo_profile())


def _db_missing_message(config: Dict[str, Any]) -> str:
    db = config.get("db") or ""
    base = (config.get("base_url") or "").rstrip("/")
    return (
        f'La base "{db}" no existe en {base}. '
        "El staging de Odoo cambió: pedí el nuevo valor de ODOO_DB (o ODOO_DB_ALIARE)."
    )


def _jsonrpc_url_for(config: Dict[str, Any]) -> str:
    base = (config.get("base_url") or "").rstrip("/")
    endpoint = (config.get("endpoint") or "jsonrpc").lstrip("/")
    return f"{base}/{endpoint}" if endpoint else f"{base}/jsonrpc"


def _jsonrpc_url() -> str:
    return _jsonrpc_url_for(get_active_odoo_config())


def _xmlrpc_url(service: str, config: Optional[Dict[str, Any]] = None) -> str:
    cfg = config or get_active_odoo_config()
    base = (cfg.get("base_url") or "").rstrip("/")
    return f"{base}/xmlrpc/2/{service}"


def is_odoo_config_ready(config: Dict[str, Any]) -> bool:
    if not (config.get("base_url") and config.get("db") and config.get("password")):
        return False
    return config.get("uid") is not None or bool(config.get("login"))


def probe_odoo_db_exists(config: Dict[str, Any]) -> Tuple[Optional[bool], Optional[List[str]], Optional[str]]:
    """db_exist + list (si el host lo permite)."""
    base = (config.get("base_url") or "").rstrip("/")
    db = config.get("db") or ""
    if not base or not db:
        return None, None, "Falta base_url o db"
    try:
        dbsvc = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/db", allow_none=True)
        db_exists: Optional[bool] = None
        try:
            db_exists = bool(dbsvc.db_exist(db))
        except Exception:
            try:
                db_exists = bool(dbsvc.exists(db))
            except Exception:
                db_exists = None
        db_list: Optional[List[str]] = None
        db_list_error: Optional[str] = None
        try:
            db_list = dbsvc.list()
        except Exception as le:
            db_list_error = str(le)
        return db_exists, db_list, db_list_error
    except Exception as e:
        return None, None, str(e)


def verify_odoo_config_connection(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Verifica conexión real (no solo uid configurado): authenticate opcional + execute_kw.
    """
    base_url = (config.get("base_url") or "").rstrip("/")
    db = config.get("db")
    password = config.get("password")
    login = config.get("login") or ""
    uid_cfg = config.get("uid")

    if not (base_url and db and password and (uid_cfg is not None or login)):
        return {
            "ok": False,
            "error": "Config Odoo incompleta (base_url/db/password y uid o login).",
        }

    db_exists, db_list, db_list_error = probe_odoo_db_exists(config)
    if db_exists is False:
        hint = _db_missing_message(config)
        return {
            "ok": False,
            "error": hint,
            "hint": hint,
            "base_url": base_url,
            "db": db,
            "db_exists": False,
            "db_list": db_list,
            "db_list_error": db_list_error,
        }

    version: Optional[dict] = None
    auth_uid: Optional[int] = None
    try:
        common = xmlrpc.client.ServerProxy(_xmlrpc_url("common", config), allow_none=True)
        version = common.version()
        if login:
            auth_uid = common.authenticate(db, login, password, {})
            auth_uid = int(auth_uid) if auth_uid else None
    except Exception as e:
        err = str(e)
        db_missing = "does not exist" in err.lower() or "keyerror" in err.lower()
        hint = _db_missing_message(config) if db_missing else None
        return {
            "ok": False,
            "error": hint or err,
            "hint": hint,
            "base_url": base_url,
            "db": db,
            "db_exists": db_exists,
            "db_list": db_list,
            "db_list_error": db_list_error,
        }

    uid = int(uid_cfg) if uid_cfg is not None else auth_uid
    if uid is None:
        return {
            "ok": False,
            "error": "No se pudo obtener uid (authenticate falló y no hay uid fijo).",
            "base_url": base_url,
            "db": db,
            "db_exists": db_exists,
            "db_list": db_list,
            "db_list_error": db_list_error,
            "version": version,
        }

    try:
        odoo_execute_kw_with_config(config, "res.users", "search_count", [[("id", "=", uid)]])
    except Exception as e:
        err = str(e)
        hint = None
        if "does not exist" in err.lower() or "keyerror" in err.lower():
            hint = (
                f'La base "{db}" no existe en {base_url}. '
                "Pedí el nombre exacto de ODOO_DB (o ODOO_DB_ALIARE) a quien administra Odoo."
            )
        return {
            "ok": False,
            "error": err,
            "hint": hint,
            "base_url": base_url,
            "db": db,
            "db_exists": db_exists,
            "db_list": db_list,
            "db_list_error": db_list_error,
            "uid": uid,
            "auth_uid": auth_uid,
            "uid_source": "ODOO_USER_ID" if uid_cfg is not None else "ODOO_USER",
            "version": version,
        }

    return {
        "ok": True,
        "uid": uid,
        "auth_uid": auth_uid,
        "uid_source": "ODOO_USER_ID" if uid_cfg is not None else "ODOO_USER",
        "db": db,
        "base_url": base_url,
        "common_url": _xmlrpc_url("common", config),
        "db_exists": db_exists,
        "db_list": db_list,
        "db_list_error": db_list_error,
        "version": version,
    }


def get_odoo_uid_from_config(config: Dict[str, Any]) -> Optional[int]:
    uid_cfg = config.get("uid")
    if uid_cfg is not None:
        return int(uid_cfg)

    login = config.get("login") or ""
    db = config["db"]
    password = config["password"]
    base = config.get("base_url")
    if not login or not db or not password or not base:
        return None

    try:
        common = xmlrpc.client.ServerProxy(_xmlrpc_url("common", config), allow_none=True)
        uid = common.authenticate(db, login, password, {})
        if uid:
            return int(uid)
        uid = common.login(db, login, password)
        if uid:
            return int(uid)
    except Exception as e:
        logger.debug("XML-RPC authenticate (config) falló: %s", e)

    for method_name in ("authenticate", "login"):
        try:
            uid = _jsonrpc_call(
                config,
                "call",
                {"service": "common", "method": method_name, "args": [db, login, password, {}]},
            )
            if uid:
                return int(uid)
        except Exception as e:
            logger.debug("common.%s (config) falló: %s", method_name, e)
    return None


def get_odoo_uid() -> Optional[int]:
    """uid para execute_kw del tenant activo (según empresa / perfil)."""
    return get_odoo_uid_from_config(get_active_odoo_config())


def is_odoo_configured() -> bool:
    return is_odoo_config_ready(get_active_odoo_config())


def _jsonrpc_call(config: Dict[str, Any], method: str, params: Dict[str, Any]) -> Any:
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": random.randint(1, 1_000_000),
    }
    resp = requests.post(
        _jsonrpc_url_for(config),
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(f"Odoo JSON-RPC error: {data['error']}")
    return data.get("result")


def _jsonrpc(method: str, params: Dict[str, Any]) -> Any:
    return _jsonrpc_call(get_active_odoo_config(), method, params)


def _is_invalid_lang_error(exc: BaseException) -> bool:
    return "invalid language code" in str(exc).lower()


def _kwargs_without_lang(kwargs: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(kwargs or {})
    ctx = dict(merged.get("context") or {})
    if "lang" not in ctx:
        return merged
    ctx.pop("lang", None)
    if ctx:
        merged["context"] = ctx
    else:
        merged.pop("context", None)
    return merged


def _merge_odoo_call_kwargs(
    kwargs: Optional[Dict[str, Any]],
    profile: Optional[str] = None,
) -> Dict[str, Any]:
    """Inyecta context.lang según perfil (Sudata: sin lang por defecto)."""
    merged = dict(kwargs or {})
    lang = resolve_odoo_lang(profile or current_odoo_profile())
    if not lang:
        return merged
    ctx = dict(merged.get("context") or {})
    if "lang" not in ctx:
        ctx["lang"] = lang
    merged["context"] = ctx
    return merged


def odoo_execute_kw_with_config(
    config: Dict[str, Any],
    model: str,
    method: str,
    args: Optional[List[Any]] = None,
    kwargs: Optional[Dict[str, Any]] = None,
) -> Any:
    """execute_kw vía JSON-RPC con credenciales arbitrarias."""
    db = config["db"]
    password = config["password"]
    uid = get_odoo_uid_from_config(config)
    if uid is None:
        raise RuntimeError("No hay uid Odoo (login/password o uid en config)")
    args = args if args is not None else []
    profile = current_odoo_profile()
    kwargs = _merge_odoo_call_kwargs(kwargs, profile)

    def _call(call_kwargs: Dict[str, Any]) -> Any:
        try:
            return _jsonrpc_call(
                config,
                "call",
                {
                    "service": "object",
                    "method": "execute_kw",
                    "args": [db, uid, password, model, method, args, call_kwargs],
                },
            )
        except Exception as e:
            logger.debug("execute_kw JSON-RPC %s.%s: %s", model, method, e)
            if _is_invalid_lang_error(e) and (call_kwargs.get("context") or {}).get("lang"):
                return _jsonrpc_call(
                    config,
                    "call",
                    {
                        "service": "object",
                        "method": "execute_kw",
                        "args": [
                            db,
                            uid,
                            password,
                            model,
                            method,
                            args,
                            _kwargs_without_lang(call_kwargs),
                        ],
                    },
                )
            raise

    try:
        return _call(kwargs)
    except Exception:
        models = xmlrpc.client.ServerProxy(_xmlrpc_url("object", config), allow_none=True)
        try:
            return models.execute_kw(db, uid, password, model, method, args, kwargs)
        except Exception as e:
            if _is_invalid_lang_error(e) and (kwargs.get("context") or {}).get("lang"):
                return models.execute_kw(
                    db, uid, password, model, method, args, _kwargs_without_lang(kwargs)
                )
            raise


def odoo_execute_kw(
    model: str,
    method: str,
    args: Optional[List[Any]] = None,
    kwargs: Optional[Dict[str, Any]] = None,
) -> Any:
    """execute_kw vía JSON-RPC (mismo orden de args que la doc de Odoo / Gemini)."""
    return odoo_execute_kw_with_config(get_active_odoo_config(), model, method, args, kwargs)


def odoo_execute_kw_xmlrpc(
    model: str,
    method: str,
    args: Optional[List[Any]] = None,
    kwargs: Optional[Dict[str, Any]] = None,
) -> Any:
    return odoo_execute_kw_with_config(get_active_odoo_config(), model, method, args, kwargs)


def odoo_search_read(
    model: str,
    domain: Optional[List[Any]] = None,
    fields: Optional[List[str]] = None,
    limit: int = 500,
    order: Optional[str] = None,
    *,
    config: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    cfg = config or get_active_odoo_config()
    domain = domain if domain is not None else []
    kwargs: Dict[str, Any] = {"fields": fields or ["id", "name"], "limit": limit}
    if order:
        kwargs["order"] = order
    if context:
        kwargs["context"] = {**(kwargs.get("context") or {}), **context}
    kwargs = _merge_odoo_call_kwargs(kwargs, current_odoo_profile())
    try:
        rows = odoo_execute_kw_with_config(cfg, model, "search_read", [domain], kwargs)
        return rows or []
    except Exception as e:
        logger.debug("search_read JSON-RPC %s: %s", model, e)
    try:
        models = xmlrpc.client.ServerProxy(_xmlrpc_url("object", cfg), allow_none=True)
        uid = get_odoo_uid_from_config(cfg)
        if uid is None:
            return []
        rows = models.execute_kw(
            cfg["db"], uid, cfg["password"], model, "search_read", [domain], kwargs
        )
        return rows or []
    except Exception as e:
        logger.warning("search_read XML-RPC %s falló: %s", model, e)
        return []


def odoo_xmlrpc_version() -> Optional[dict]:
    base = get_active_odoo_config()["base_url"]
    if not base:
        return None
    try:
        common = xmlrpc.client.ServerProxy(_xmlrpc_url("common"), allow_none=True)
        return common.version()
    except Exception as e:
        logger.warning("XML-RPC version() falló: %s", e)
    return None


def get_odoo_document_types(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Tipos de comprobante LATAM (nombres en español vía context lang en execute_kw)."""
    fields = ["id", "name", "code"]
    rows = odoo_search_read("l10n_latam.document.type", [], fields, limit=500, config=config)
    if not rows:
        rows = odoo_search_read(
            "l10n_latam.document.type", [], ["id", "name"], limit=500, config=config
        )
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for r in rows:
        id_val = r.get("id")
        if id_val is None:
            continue
        id_int = int(id_val)
        name_str = str(r.get("name") or "").strip()
        code_str = str(r.get("code") or "").strip().upper() if r.get("code") else ""
        if name_str:
            key = (id_int, name_str)
            if key not in seen:
                seen.add(key)
                row: Dict[str, Any] = {"id": id_int, "name": name_str}
                if code_str:
                    row["code"] = code_str
                out.append(row)
        if code_str in ("OC-X", "99"):
            key = (id_int, "OC-X")
            if key not in seen:
                seen.add(key)
                out.append({"id": id_int, "name": "OC-X"})
    return out
