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

from facturia_matching.config import ODOO_CONFIG, _env_strip

logger = logging.getLogger(__name__)


def _jsonrpc_url_for(config: Dict[str, Any]) -> str:
    base = (config.get("base_url") or "").rstrip("/")
    endpoint = (config.get("endpoint") or "jsonrpc").lstrip("/")
    return f"{base}/{endpoint}" if endpoint else f"{base}/jsonrpc"


def _jsonrpc_url() -> str:
    return _jsonrpc_url_for(ODOO_CONFIG)


def _xmlrpc_url(service: str, config: Optional[Dict[str, Any]] = None) -> str:
    cfg = config or ODOO_CONFIG
    base = (cfg.get("base_url") or "").rstrip("/")
    return f"{base}/xmlrpc/2/{service}"


def get_odoo_test_config() -> Dict[str, Any]:
    """Credenciales Odoo TEST desde .env (ODOO_*_TEST)."""
    uid_raw = _env_strip("ODOO_USER_ID_TEST")
    try:
        uid = int(uid_raw) if uid_raw else None
    except ValueError:
        uid = None

    return {
        "base_url": _env_strip("ODOO_API_TEST").rstrip("/"),
        "endpoint": (_env_strip("ODOO_ENDPOINT_TEST", _env_strip("ODOO_ENDPOINT", "/jsonrpc")).lstrip("/") or "jsonrpc"),
        "db": _env_strip("ODOO_DB_TEST"),
        "uid": uid,
        "login": _env_strip("ODOO_USER_TEST"),
        "password": _env_strip("ODOO_PASSWORD_TEST"),
    }


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

    version: Optional[dict] = None
    auth_uid: Optional[int] = None
    try:
        common = xmlrpc.client.ServerProxy(_xmlrpc_url("common", config), allow_none=True)
        version = common.version()
        if login:
            auth_uid = common.authenticate(db, login, password, {})
            auth_uid = int(auth_uid) if auth_uid else None
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
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
                "Pedí el nombre exacto de ODOO_DB_TEST a quien administra Odoo TEST."
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
            "uid_source": "ODOO_USER_ID_TEST" if uid_cfg is not None else "ODOO_USER_TEST",
            "version": version,
        }

    return {
        "ok": True,
        "uid": uid,
        "auth_uid": auth_uid,
        "uid_source": "ODOO_USER_ID_TEST" if uid_cfg is not None else "ODOO_USER_TEST",
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
    """
    uid para execute_kw:
    1) ODOO_USER_ID si está definido (entero)
    2) common.authenticate / login con ODOO_USER (email)
    """
    uid_cfg = ODOO_CONFIG.get("uid")
    if uid_cfg is not None:
        return int(uid_cfg)

    login = ODOO_CONFIG.get("login") or ""
    db = ODOO_CONFIG["db"]
    password = ODOO_CONFIG["password"]
    base = ODOO_CONFIG["base_url"]
    if not login or not db or not password or not base:
        return None

    # XML-RPC
    try:
        common = xmlrpc.client.ServerProxy(_xmlrpc_url("common"), allow_none=True)
        uid = common.authenticate(db, login, password, {})
        if uid:
            return int(uid)
        uid = common.login(db, login, password)
        if uid:
            return int(uid)
    except Exception as e:
        logger.debug("XML-RPC authenticate falló: %s", e)

    # JSON-RPC
    for method_name in ("authenticate", "login"):
        try:
            uid = _jsonrpc(
                "call",
                {"service": "common", "method": method_name, "args": [db, login, password, {}]},
            )
            if uid:
                return int(uid)
        except Exception as e:
            logger.debug("common.%s falló: %s", method_name, e)
    return None


def is_odoo_configured() -> bool:
    return is_odoo_config_ready(ODOO_CONFIG)


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
    return _jsonrpc_call(ODOO_CONFIG, method, params)


def odoo_execute_kw_with_config(
    config: Dict[str, Any],
    model: str,
    method: str,
    args: Optional[List[Any]] = None,
    kwargs: Optional[Dict[str, Any]] = None,
) -> Any:
    """execute_kw vía JSON-RPC con credenciales arbitrarias (p. ej. ODOO_*_TEST)."""
    db = config["db"]
    password = config["password"]
    uid = get_odoo_uid_from_config(config)
    if uid is None:
        raise RuntimeError("No hay uid Odoo (login/password o uid en config)")
    args = args if args is not None else []
    kwargs = kwargs if kwargs is not None else {}
    try:
        return _jsonrpc_call(
            config,
            "call",
            {
                "service": "object",
                "method": "execute_kw",
                "args": [db, uid, password, model, method, args, kwargs],
            },
        )
    except Exception as e:
        logger.debug("execute_kw JSON-RPC %s.%s: %s", model, method, e)
    models = xmlrpc.client.ServerProxy(_xmlrpc_url("object", config), allow_none=True)
    return models.execute_kw(db, uid, password, model, method, args, kwargs)


def odoo_execute_kw(
    model: str,
    method: str,
    args: Optional[List[Any]] = None,
    kwargs: Optional[Dict[str, Any]] = None,
) -> Any:
    """execute_kw vía JSON-RPC (mismo orden de args que la doc de Odoo / Gemini)."""
    return odoo_execute_kw_with_config(ODOO_CONFIG, model, method, args, kwargs)


def odoo_execute_kw_xmlrpc(
    model: str,
    method: str,
    args: Optional[List[Any]] = None,
    kwargs: Optional[Dict[str, Any]] = None,
) -> Any:
    return odoo_execute_kw_with_config(ODOO_CONFIG, model, method, args, kwargs)


def odoo_search_read(
    model: str,
    domain: Optional[List[Any]] = None,
    fields: Optional[List[str]] = None,
    limit: int = 500,
    order: Optional[str] = None,
) -> List[Dict[str, Any]]:
    domain = domain if domain is not None else []
    kwargs: Dict[str, Any] = {"fields": fields or ["id", "name"], "limit": limit}
    if order:
        kwargs["order"] = order
    try:
        rows = odoo_execute_kw(model, "search_read", [domain], kwargs)
        return rows or []
    except Exception as e:
        logger.debug("search_read JSON-RPC %s: %s", model, e)
    try:
        rows = odoo_execute_kw_xmlrpc(model, "search_read", [domain], kwargs)
        return rows or []
    except Exception as e:
        logger.warning("search_read XML-RPC %s falló: %s", model, e)
        return []


def odoo_xmlrpc_version() -> Optional[dict]:
    base = ODOO_CONFIG["base_url"]
    if not base:
        return None
    try:
        common = xmlrpc.client.ServerProxy(_xmlrpc_url("common"), allow_none=True)
        return common.version()
    except Exception as e:
        logger.warning("XML-RPC version() falló: %s", e)
    return None


def get_odoo_document_types() -> List[Dict[str, Any]]:
    fields = ["id", "name", "code"]
    rows = odoo_search_read("l10n_latam.document.type", [], fields, limit=500)
    if not rows:
        rows = odoo_search_read("l10n_latam.document.type", [], ["id", "name"], limit=500)
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
                out.append({"id": id_int, "name": name_str})
        if code_str in ("OC-X", "99"):
            key = (id_int, "OC-X")
            if key not in seen:
                seen.add(key)
                out.append({"id": id_int, "name": "OC-X"})
    return out
