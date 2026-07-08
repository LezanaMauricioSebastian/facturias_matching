"""Catálogo Odoo: dominio de partners por perfil."""

import unittest

from facturia_matching.odoo.catalog import _partner_catalog_domain


class TestPartnerCatalogDomain(unittest.TestCase):
    def test_aliare_loads_all_contacts(self):
        self.assertEqual(_partner_catalog_domain("aliare"), [])

    def test_default_filters_suppliers(self):
        self.assertEqual(_partner_catalog_domain("default"), [("supplier_rank", ">", 0)])

    def test_sudata_filters_suppliers(self):
        self.assertEqual(_partner_catalog_domain("sudata"), [("supplier_rank", ">", 0)])


if __name__ == "__main__":
    unittest.main()
