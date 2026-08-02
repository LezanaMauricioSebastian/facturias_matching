"""Contexto de perfil Odoo y empresa FacturIA por request."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

_request_odoo_profile: ContextVar[Optional[str]] = ContextVar("request_odoo_profile", default=None)
_request_empresa: ContextVar[Optional[str]] = ContextVar("request_empresa", default=None)


def get_request_odoo_profile() -> Optional[str]:
    return _request_odoo_profile.get()


def get_request_empresa() -> Optional[str]:
    return _request_empresa.get()


@contextmanager
def odoo_profile_context(
    odoo_profile: Optional[str],
    empresa: Optional[str] = None,
) -> Iterator[None]:
    from facturia_matching.padron.taxes import clear_odoo_tax_catalog_cache

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
    clear_odoo_tax_catalog_cache()
    token_p = _request_odoo_profile.set(profile)
    token_e = _request_empresa.set(emp)
    try:
        yield
    finally:
        _request_odoo_profile.reset(token_p)
        _request_empresa.reset(token_e)
        clear_odoo_tax_catalog_cache()
