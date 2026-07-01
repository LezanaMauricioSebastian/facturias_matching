"""Contexto de perfil Odoo por request (default, aliare, sudata)."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

_request_odoo_profile: ContextVar[Optional[str]] = ContextVar("request_odoo_profile", default=None)


def get_request_odoo_profile() -> Optional[str]:
    return _request_odoo_profile.get()


@contextmanager
def odoo_profile_context(odoo_profile: Optional[str]) -> Iterator[None]:
    from facturia_matching.padron.taxes import clear_odoo_tax_catalog_cache

    profile = str(odoo_profile).strip() if odoo_profile is not None and str(odoo_profile).strip() != "" else None
    clear_odoo_tax_catalog_cache()
    token = _request_odoo_profile.set(profile)
    try:
        yield
    finally:
        _request_odoo_profile.reset(token)
        clear_odoo_tax_catalog_cache()
