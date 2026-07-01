"""Tests: rubro (x_studio_category) solo en perfil Dinner."""
import unittest

from facturia_matching.core.options import build_metadata_payload
from facturia_matching.odoo.env import supports_rubro_field
from facturia_matching.odoo.request_context import odoo_profile_context
from facturia_matching.persistence.saved_row_remap import remap_saved_rows_to_catalog
from unittest.mock import patch


class TestRubroProfile(unittest.TestCase):
    def test_supports_rubro_only_on_dinner(self):
        with odoo_profile_context("default"):
            self.assertTrue(supports_rubro_field())
        with odoo_profile_context("aliare"):
            self.assertFalse(supports_rubro_field())
        with odoo_profile_context("sudata"):
            self.assertFalse(supports_rubro_field())

    def test_metadata_hides_rubro_on_aliare(self):
        with odoo_profile_context("aliare"):
            meta = build_metadata_payload()
        keys = [c["key"] for c in meta["columns"]]
        self.assertNotIn("x_studio_category", keys)
        self.assertNotIn("x_studio_category", meta["output_headers"])

    def test_metadata_shows_rubro_on_dinner(self):
        with odoo_profile_context("default"):
            meta = build_metadata_payload()
        keys = [c["key"] for c in meta["columns"]]
        self.assertIn("x_studio_category", keys)

    @patch("facturia_matching.persistence.saved_row_remap.get_catalog")
    @patch("facturia_matching.persistence.saved_row_remap.match_proveedor")
    def test_remap_clears_rubro_on_aliare(self, mock_match, mock_catalog):
        catalog = {
            "proveedores": [{"id": 22, "name": "LA MADRID SRL", "vat": "30710552602"}],
            "partner_cuit_to_id": {"30710552602": 22},
            "journals": [{"id": 5, "name": "FP CUP NEA"}],
            "rubros": [{"id": 3, "name": "Rubro test"}],
            "cuentas": [{"id": 100, "name": "Purchase", "code": "5.1.1.01.030"}],
            "document_types": [{"id": 11, "name": "FACTURAS C"}],
            "productos": [],
            "maps": {"document_type_labels": {}, "accounts": {}},
        }
        mock_catalog.return_value = (catalog, True)
        mock_match.return_value = ("LA MADRID SRL", "Rubro test", "FP CUP NEA", "Purchase", 100.0)
        rows = [
            {
                "__comprobante_idx": 1,
                "partner_id": "1419",
                "Nombre de Proveedor": "LA MADRID",
                "CUIT": "30-71055260-2",
                "x_studio_category": "888",
            }
        ]
        with odoo_profile_context("aliare"):
            out = remap_saved_rows_to_catalog(rows)
        self.assertEqual(out[0]["x_studio_category"], "")


if __name__ == "__main__":
    unittest.main()
