"""Resolución de variables Odoo según perfil (default/Dinner, aliare, sudata)."""

import logging
import xmlrpc.client
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from facturia_matching.infra.env import env_strip as _env_strip
from facturia_matching.odoo.request_context import get_request_odoo_profile

logger = logging.getLogger(__name__)

FACTURIA_ODOO_PROFILE = _env_strip("FACTURIA_ODOO_PROFILE").lower()


def _normalize_odoo_profile(raw: Optional[Any]) -> str:
    p = str(raw or "").strip().lower()
    if p in ("aliare", "default", "sudata"):
        return p
    return ""


def is_odoo_cloud_flag(raw: Optional[Any]) -> bool:
    """True si odoo_cloud=1 / true / yes (query o body)."""
    p = str(raw or "").strip().lower()
    return p in ("1", "true", "yes", "on")


def resolve_odoo_profile(odoo_profile: Optional[Any] = None) -> str:
    """
    odoo_profile=sudata → tenant Odoo Cloud Sudata.
    odoo_profile=aliare → tenant Aliare.
    odoo_profile=default u omitido → Dinner (salvo FACTURIA_ODOO_PROFILE en deploy).
    """
    if odoo_profile is None:
        odoo_profile = get_request_odoo_profile()
    explicit = _normalize_odoo_profile(odoo_profile)
    if explicit == "sudata":
        return "sudata"
    if explicit == "aliare":
        return "aliare"
    if explicit == "default":
        return "default"
    if FACTURIA_ODOO_PROFILE == "sudata":
        return "sudata"
    if FACTURIA_ODOO_PROFILE == "aliare":
        return "aliare"
    return "default"


def is_odoo_aliare_profile(odoo_profile: Optional[Any] = None) -> bool:
    return resolve_odoo_profile(odoo_profile) == "aliare"


def supports_rubro_field(odoo_profile: Optional[Any] = None) -> bool:
    """x_rubros / x_studio_category es custom de Dinner; otros tenants no lo usan."""
    return resolve_odoo_profile(odoo_profile) == "default"


def is_odoo_sudata_profile(odoo_profile: Optional[Any] = None) -> bool:
    return resolve_odoo_profile(odoo_profile) == "sudata"


def uses_odoo_padron_first(odoo_profile: Optional[Any] = None) -> bool:
    """Padrón: Odoo histórico antes que Postgres (Aliare y Sudata)."""
    profile = resolve_odoo_profile(odoo_profile)
    return profile in ("aliare", "sudata")


def current_odoo_profile(odoo_profile: Optional[Any] = None) -> str:
    return resolve_odoo_profile(odoo_profile)


def _odoo_db_from_url(base_url: str) -> str:
    raw = (base_url or "").strip().rstrip("/")
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    host = (urlparse(raw).hostname or "").strip()
    return host


def list_odoo_databases(base_url: str) -> Optional[List[str]]:
    base = (base_url or "").rstrip("/")
    if not base:
        return None
    try:
        dbsvc = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/db", allow_none=True)
        rows = dbsvc.list()
        return list(rows) if rows else []
    except Exception as e:
        logger.debug("db.list() falló en %s: %s", base, e)
        return None


def _odoo_db_exists(base_url: str, db_name: str) -> Optional[bool]:
    base = (base_url or "").rstrip("/")
    db_name = (db_name or "").strip()
    if not base or not db_name:
        return None
    try:
        dbsvc = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/db", allow_none=True)
        try:
            return bool(dbsvc.db_exist(db_name))
        except Exception:
            return bool(dbsvc.exists(db_name))
    except Exception as e:
        logger.debug("db_exist(%s) falló en %s: %s", db_name, base, e)
        return None


def resolve_odoo_db_name(
    base_url: str,
    configured: str,
    *,
    login: str = "",
    password: str = "",
) -> str:
    """
    Nombre explícito, única base en db.list(), auth contra candidatos,
    o hostname solo si db_exist / authenticate confirman.
    """
    explicit = (configured or "").strip()
    if explicit:
        return explicit
    base = (base_url or "").rstrip("/")
    if not base:
        return ""

    dbs: List[str] = list_odoo_databases(base) or []
    if len(dbs) == 1:
        return dbs[0]
    if dbs and login and password:
        for db in dbs:
            if _odoo_auth_ok(base, db, login, password):
                return db

    host_db = _odoo_db_from_url(base)
    if host_db:
        if _odoo_db_exists(base, host_db) is True:
            return host_db
        if login and password and _odoo_auth_ok(base, host_db, login, password):
            return host_db
    return ""


def _odoo_auth_ok(base_url: str, db_name: str, login: str, password: str) -> bool:
    base = (base_url or "").rstrip("/")
    db_name = (db_name or "").strip()
    login = (login or "").strip()
    if not (base and db_name and login and password):
        return False
    try:
        common = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/common", allow_none=True)
        uid = common.authenticate(db_name, login, password, {})
        if uid:
            return True
        uid = common.login(db_name, login, password)
        return bool(uid)
    except Exception as e:
        logger.debug("authenticate(%s) falló en %s: %s", db_name, base, e)
        return False


# template_id en process_conversions: una conversión guardada por proceso y perfil Odoo.
ODOO_TEMPLATE_ID_DEFAULT = 99
ODOO_TEMPLATE_ID_ALIARE = 100
ODOO_TEMPLATE_ID_SUDATA = 101


def get_conversion_template_id(odoo_profile: Optional[Any] = None) -> int:
    profile = resolve_odoo_profile(odoo_profile)
    if profile == "aliare":
        return ODOO_TEMPLATE_ID_ALIARE
    if profile == "sudata":
        return ODOO_TEMPLATE_ID_SUDATA
    return ODOO_TEMPLATE_ID_DEFAULT


def _parse_odoo_uid(raw: str) -> Optional[int]:
    s = (raw or "").strip()
    if not s or "@" in s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _aliare_login() -> str:
    login = _env_strip("ODOO_USER_ALIARE")
    if login:
        return login
    raw = _env_strip("ODOO_USER_ID_ALIARE")
    if "@" in raw:
        return raw
    return ""


def _aliare_endpoint() -> str:
    """JSON-RPC path; ignorar si copiaron la URL XML-RPC /xmlrpc/2/common por error."""
    ep = _env_strip("ODOO_ENDPOINT_ALIARE") or _env_strip("ODOO_ENDPOINT", "/jsonrpc")
    if "xmlrpc" in ep.lower():
        return "jsonrpc"
    return (ep.lstrip("/") or "jsonrpc")


def _aliare_secret() -> Tuple[str, str]:
    api = _env_strip("ODOO_API_KEY_ALIARE")
    if api:
        return api, "ODOO_API_KEY_ALIARE"
    pwd = _env_strip("ODOO_PASSWORD_ALIARE")
    if pwd:
        return pwd, "ODOO_PASSWORD_ALIARE"
    return "", "none"


def _sudata_base_url() -> str:
    return (_env_strip("ODOO_BASE_URL_SUDATA") or _env_strip("URL_SUDATA")).rstrip("/")


def _sudata_db() -> str:
    return _env_strip("ODOO_DB_SUDATA") or _env_strip("DB_SUDATA")


def _sudata_login() -> str:
    login = _env_strip("ODOO_USER_SUDATA") or _env_strip("USERNAME_SUDATA")
    if login:
        return login
    raw = _env_strip("ODOO_USER_ID_SUDATA")
    if "@" in raw:
        return raw
    return ""


def _sudata_endpoint() -> str:
    ep = _env_strip("ODOO_ENDPOINT_SUDATA") or _env_strip("ODOO_ENDPOINT", "/jsonrpc")
    if "xmlrpc" in ep.lower():
        return "jsonrpc"
    return (ep.lstrip("/") or "jsonrpc")


def _sudata_secret() -> Tuple[str, str]:
    api = _env_strip("ODOO_API_KEY_SUDATA") or _env_strip("API_KEY_SUDATA")
    if api:
        return api, "ODOO_API_KEY_SUDATA"
    pwd = _env_strip("ODOO_PASSWORD_SUDATA") or _env_strip("PASSWORD_SUDATA")
    if pwd:
        return pwd, "ODOO_PASSWORD_SUDATA"
    return "", "none"


def _build_dinner_config() -> Dict[str, Any]:
    uid_raw = _env_strip("ODOO_USER_ID")
    uid = _parse_odoo_uid(uid_raw)
    password = _env_strip("ODOO_PASSWORD") or _env_strip("ODOO_API_KEY")
    base_url = _env_strip("ODOO_BASE_URL", "https://dinner.odoo.com").rstrip("/")
    login = _env_strip("ODOO_USER")
    return {
        "base_url": base_url,
        "endpoint": (_env_strip("ODOO_ENDPOINT", "/jsonrpc").lstrip("/") or "jsonrpc"),
        "db": resolve_odoo_db_name(
            base_url,
            _env_strip("ODOO_DB"),
            login=login,
            password=password,
        ),
        "uid": uid,
        "login": login,
        "password": password,
    }


def _build_aliare_config() -> Dict[str, Any]:
    secret, _ = _aliare_secret()
    uid = _parse_odoo_uid(_env_strip("ODOO_USER_ID_ALIARE"))
    base_url = _env_strip("ODOO_BASE_URL_ALIARE").rstrip("/")
    login = _aliare_login()
    return {
        "base_url": base_url,
        "endpoint": _aliare_endpoint(),
        "db": resolve_odoo_db_name(
            base_url,
            _env_strip("ODOO_DB_ALIARE"),
            login=login,
            password=secret,
        ),
        "uid": uid,
        "login": login,
        "password": secret,
    }


def _build_sudata_config() -> Dict[str, Any]:
    secret, _ = _sudata_secret()
    uid = _parse_odoo_uid(_env_strip("ODOO_USER_ID_SUDATA"))
    base_url = _sudata_base_url()
    login = _sudata_login()
    return {
        "base_url": base_url,
        "endpoint": _sudata_endpoint(),
        "db": resolve_odoo_db_name(
            base_url,
            _sudata_db(),
            login=login,
            password=secret,
        ),
        "uid": uid,
        "login": login,
        "password": secret,
    }


def build_odoo_main_config(profile: Optional[str] = None) -> Dict[str, Any]:
    profile = profile or resolve_odoo_profile()
    if profile == "aliare":
        return _build_aliare_config()
    if profile == "sudata":
        return _build_sudata_config()
    return _build_dinner_config()


@lru_cache(maxsize=4)
def get_odoo_main_config(profile: str) -> Dict[str, Any]:
    return build_odoo_main_config(profile)


def build_odoo_import_config(profile: Optional[str] = None) -> Dict[str, Any]:
    """Import de facturas: misma instancia Odoo que catálogos/health del perfil activo."""
    return dict(build_odoo_main_config(profile or resolve_odoo_profile()))
