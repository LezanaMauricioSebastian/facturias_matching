"""Contexto de perfil Odoo y empresa FacturIA por request."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional, Tuple

_request_odoo_profile: ContextVar[Optional[str]] = ContextVar("request_odoo_profile", default=None)
_request_empresa: ContextVar[Optional[str]] = ContextVar("request_empresa", default=None)

# Scope del cache de impuestos Odoo (process-wide). Se limpia solo al cambiar.
_tax_cache_scope: Optional[Tuple[Optional[str], Optional[str]]] = None


def get_request_odoo_profile() -> Optional[str]:
    return _request_odoo_profile.get()


def get_request_empresa() -> Optional[str]:
    return _request_empresa.get()


def _ensure_tax_cache_scope(profile: Optional[str], empresa: Optional[str]) -> None:
    """Invalida catálogo de taxes solo si cambió profile/empresa (no en cada request)."""
    global _tax_cache_scope
    scope = (profile, empresa)
    if _tax_cache_scope == scope:
        return
    from facturia_matching.padron.taxes import clear_odoo_tax_catalog_cache

    clear_odoo_tax_catalog_cache()
    _tax_cache_scope = scope


def reset_tax_cache_scope() -> None:
    """Tests / invalidación explícita del scope de taxes."""
    global _tax_cache_scope
    _tax_cache_scope = None


@contextmanager
def odoo_profile_context(
    odoo_profile: Optional[str],
    empresa: Optional[str] = None,
) -> Iterator[None]:
    profile = (
        str(odoo_profile).strip()
        if odoo_profile is not None and str(odoo_profile).strip() != ""
        else None
    )
    emp = (
        str(empresa).strip()
        if empresa is not None and str(empresa).strip() != ""
        else None
    )
    _ensure_tax_cache_scope(profile, emp)
    token_p = _request_odoo_profile.set(profile)
    token_e = _request_empresa.set(emp)
    try:
        yield
    finally:
        _request_odoo_profile.reset(token_p)
        _request_empresa.reset(token_e)
