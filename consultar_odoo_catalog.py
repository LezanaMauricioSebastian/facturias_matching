#!/usr/bin/env python3
"""Smoke test: catálogo Odoo (diarios, tipos de comprobante, etc.)."""

import json
import sys

from odoo_api import get_odoo_uid, is_odoo_configured, odoo_xmlrpc_version
from odoo_catalog import get_catalog, invalidate_catalog_cache


def main() -> int:
    if not is_odoo_configured():
        print("ODOO_* no configurado en .env")
        return 1
    invalidate_catalog_cache()
    uid = get_odoo_uid()
    print("uid:", uid)
    print("version:", odoo_xmlrpc_version())
    catalog, ok = get_catalog(force=True)
    if not ok or not catalog:
        print("No se pudo cargar catálogo Odoo")
        return 2
    for key in ("journals", "document_types", "proveedores", "cuentas", "rubros"):
        items = catalog.get(key) or []
        print(f"\n{key}: {len(items)}")
        for row in items[:5]:
            print(" ", row)
    print("\nproveedores_cuit_map (sample):", json.dumps(dict(list((catalog.get("proveedores_cuit_map") or {}).items())[:3])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
