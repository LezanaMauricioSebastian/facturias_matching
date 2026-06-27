"""Resolución de variables Odoo según perfil (default vs aliare)."""

from typing import Any, Dict, Optional, Tuple

from facturia_matching.env_utils import env_strip as _env_strip

FACTURIA_ODOO_PROFILE = _env_strip("FACTURIA_ODOO_PROFILE").lower()


def is_odoo_aliare_profile() -> bool:
    return FACTURIA_ODOO_PROFILE == "aliare"


def current_odoo_profile() -> str:
    """Perfil activo para catálogo, matching y persistencia de conversiones."""
    return "aliare" if is_odoo_aliare_profile() else "default"


# template_id en process_conversions: una conversión guardada por proceso y perfil Odoo.
ODOO_TEMPLATE_ID_DEFAULT = 99
ODOO_TEMPLATE_ID_ALIARE = 100


def get_conversion_template_id() -> int:
    return ODOO_TEMPLATE_ID_ALIARE if is_odoo_aliare_profile() else ODOO_TEMPLATE_ID_DEFAULT


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


def build_odoo_main_config() -> Dict[str, Any]:
    if not is_odoo_aliare_profile():
        uid_raw = _env_strip("ODOO_USER_ID")
        uid = _parse_odoo_uid(uid_raw)
        password = _env_strip("ODOO_PASSWORD") or _env_strip("ODOO_API_KEY")
        return {
            "base_url": _env_strip("ODOO_BASE_URL", "https://dinner.odoo.com").rstrip("/"),
            "endpoint": (_env_strip("ODOO_ENDPOINT", "/jsonrpc").lstrip("/") or "jsonrpc"),
            "db": _env_strip("ODOO_DB"),
            "uid": uid,
            "login": _env_strip("ODOO_USER"),
            "password": password,
        }

    secret, _ = _aliare_secret()
    uid = _parse_odoo_uid(_env_strip("ODOO_USER_ID_ALIARE"))
    return {
        "base_url": _env_strip("ODOO_BASE_URL_ALIARE").rstrip("/"),
        "endpoint": _aliare_endpoint(),
        "db": _env_strip("ODOO_DB_ALIARE"),
        "uid": uid,
        "login": _aliare_login(),
        "password": secret,
    }


def _default_test_secret() -> Tuple[str, str]:
    api_test = _env_strip("ODOO_API_KEY_TEST")
    if api_test:
        return api_test, "ODOO_API_KEY_TEST"
    password = _env_strip("ODOO_PASSWORD_TEST")
    if password:
        return password, "ODOO_PASSWORD_TEST"
    api_global = _env_strip("ODOO_API_KEY")
    if api_global:
        return api_global, "ODOO_API_KEY"
    return "", "none"


def build_odoo_test_config() -> Dict[str, Any]:
    """TEST / import: en perfil aliare usa el mismo tenant (una sola instancia Odoo)."""
    if not is_odoo_aliare_profile():
        uid = _parse_odoo_uid(_env_strip("ODOO_USER_ID_TEST"))
        password_test, _ = _default_test_secret()
        return {
            "base_url": _env_strip("ODOO_API_TEST").rstrip("/"),
            "endpoint": (
                _env_strip("ODOO_ENDPOINT_TEST", _env_strip("ODOO_ENDPOINT", "/jsonrpc")).lstrip("/")
                or "jsonrpc"
            ),
            "db": _env_strip("ODOO_DB_TEST"),
            "uid": uid,
            "login": _env_strip("ODOO_USER_TEST"),
            "password": password_test,
        }

    return dict(build_odoo_main_config())
