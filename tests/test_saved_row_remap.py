"""Tests for saved_row_remap (cross-tenant Odoo ID remapping)."""

import unittest
from unittest.mock import patch

from facturia_matching.odoo.request_context import odoo_profile_context
from facturia_matching.persistence.saved_row_remap import remap_saved_rows_to_catalog


def _aliare_catalog():
    return {
        "proveedores": [
            {"id": 22, "name": "LA MADRID SRL", "vat": "30710552602"},
            {"id": 10, "name": "Alicia Vazquez"},
        ],
        "partner_cuit_to_id": {"30710552602": 22},
        "proveedores_cuit_map": {"22": "30710552602"},
        "journals": [{"id": 5, "name": "FP CUP NEA"}],
        "rubros": [{"id": 3, "name": "Rubro test"}],
        "cuentas": [{"id": 100, "name": "Purchase of merchandise", "code": "5.1.1.01.030"}],
        "document_types": [{"id": 11, "name": "FACTURAS C"}],
        "productos": [{"id": 50, "name": "Producto X", "code": "PX01"}],
        "maps": {
            "document_type_labels": {"FACTURAS C": 11},
            "accounts": {
                "by_code": {"5.1.1.01.030": 100},
                "by_name": {"PURCHASE OF MERCHANDISE": 100},
                "by_full": {"5.1.1.01.030 PURCHASE OF MERCHANDISE": 100},
            },
        },
    }


class TestRemapSavedRowsToCatalog(unittest.TestCase):
    @patch("facturia_matching.persistence.saved_row_remap.get_catalog")
    @patch("facturia_matching.persistence.saved_row_remap.match_proveedor")
    def test_remaps_partner_id_by_cuit_from_other_tenant(self, mock_match, mock_catalog):
        mock_catalog.return_value = (_aliare_catalog(), True)
        mock_match.return_value = (
            "LA MADRID SRL",
            "Rubro test",
            "FP CUP NEA",
            "5.1.1.01.030 Purchase of merchandise",
            100.0,
        )
        rows = [
            {
                "__comprobante_idx": 1,
                "partner_id": "1419",
                "Nombre de Proveedor": "LA MADRID",
                "CUIT": "30-71055260-2",
                "journal_id": "999",
                "x_studio_category": "888",
                "invoice_line_ids/account_id": "777",
                "invoice_line_ids/name": "Item",
            }
        ]
        with odoo_profile_context("default"):
            out = remap_saved_rows_to_catalog(rows)
        self.assertEqual(out[0]["partner_id"], "22")
        self.assertEqual(out[0]["journal_id"], "5")
        self.assertEqual(out[0]["x_studio_category"], "3")
        self.assertEqual(out[0]["invoice_line_ids/account_id"], "100")

    @patch("facturia_matching.persistence.saved_row_remap.get_catalog")
    def test_keeps_valid_partner_id(self, mock_catalog):
        mock_catalog.return_value = (_aliare_catalog(), True)
        rows = [
            {
                "__comprobante_idx": 1,
                "partner_id": "22",
                "Nombre de Proveedor": "LA MADRID SRL",
                "CUIT": "30710552602",
            }
        ]
        out = remap_saved_rows_to_catalog(rows)
        self.assertEqual(out[0]["partner_id"], "22")

    @patch("facturia_matching.persistence.saved_row_remap.get_catalog")
    def test_noop_when_odoo_unavailable(self, mock_catalog):
        mock_catalog.return_value = (None, False)
        rows = [{"partner_id": "1419", "CUIT": "30710552602"}]
        out = remap_saved_rows_to_catalog(rows)
        self.assertEqual(out[0]["partner_id"], "1419")

    @patch("facturia_matching.persistence.saved_row_remap.get_catalog")
    @patch("facturia_matching.persistence.saved_row_remap.match_proveedor")
    def test_remaps_stale_partner_on_continuation_rows(self, mock_match, mock_catalog):
        mock_catalog.return_value = (_aliare_catalog(), True)
        mock_match.return_value = (
            "LA MADRID SRL",
            "Rubro test",
            "FP CUP NEA",
            "5.1.1.01.030 Purchase of merchandise",
            100.0,
        )
        rows = [
            {
                "__comprobante_idx": 1,
                "partner_id": "1419",
                "Nombre de Proveedor": "LA MADRID",
                "CUIT": "30710552602",
                "invoice_line_ids/name": "Linea 1",
            },
            {
                "__comprobante_idx": 1,
                "partner_id": "1419",
                "invoice_line_ids/name": "Linea 2",
            },
        ]
        out = remap_saved_rows_to_catalog(rows)
        self.assertEqual(out[0]["partner_id"], "22")
        self.assertEqual(out[1]["partner_id"], "22")

    @patch("facturia_matching.persistence.saved_row_remap.get_catalog")
    @patch("facturia_matching.persistence.saved_row_remap.match_proveedor")
    def test_propagates_partner_to_line_rows(self, mock_match, mock_catalog):
        mock_catalog.return_value = (_aliare_catalog(), True)
        mock_match.return_value = ("", "", "", "", 0.0)
        rows = [
            {
                "__comprobante_idx": 1,
                "partner_id": "1419",
                "Nombre de Proveedor": "LA MADRID",
                "CUIT": "30710552602",
            },
            {
                "__comprobante_idx": 1,
                "partner_id": "",
                "invoice_line_ids/name": "Linea 2",
            },
        ]
        out = remap_saved_rows_to_catalog(rows)
        self.assertEqual(out[0]["partner_id"], "22")
        self.assertEqual(out[1]["partner_id"], "22")

    @patch("facturia_matching.persistence.saved_row_remap.get_catalog")
    def test_remaps_product_by_code(self, mock_catalog):
        mock_catalog.return_value = (_aliare_catalog(), True)
        rows = [
            {
                "__comprobante_idx": 1,
                "invoice_line_ids/product_id": "9999",
                "__item_codigo": "PX01",
                "invoice_line_ids/name": "Producto X",
            }
        ]
        out = remap_saved_rows_to_catalog(rows)
        self.assertEqual(out[0]["invoice_line_ids/product_id"], "50")


if __name__ == "__main__":
    unittest.main()
