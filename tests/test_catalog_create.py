"""Alta de proveedor/producto: vals y elección de UM Unidades."""
import unittest
from unittest.mock import patch

from facturia_matching.odoo.catalog_create import (
    CatalogCreateError,
    create_supplier_partner,
    pick_unidades_uom,
    product_create_vals,
    supplier_partner_vals,
)
from facturia_matching.odoo.request_context import odoo_profile_context


class TestSupplierPartnerVals(unittest.TestCase):
    def test_name_and_cuit(self):
        vals = supplier_partner_vals("  Proveedor   Nuevo  ", "  20-12345678-9  ")
        self.assertEqual(vals["name"], "Proveedor Nuevo")
        self.assertEqual(vals["supplier_rank"], 1)
        self.assertEqual(vals["vat"], "20-12345678-9")

    def test_without_cuit(self):
        vals = supplier_partner_vals("ACME")
        self.assertEqual(vals, {"name": "ACME", "supplier_rank": 1})

    def test_short_name_rejected(self):
        with self.assertRaises(CatalogCreateError):
            supplier_partner_vals("A")


class TestProductVals(unittest.TestCase):
    def test_purchase_product_uses_uom(self):
        vals = product_create_vals("Entrada show", 7)
        self.assertEqual(vals["name"], "Entrada show")
        self.assertTrue(vals["purchase_ok"])
        self.assertEqual(vals["uom_id"], 7)
        self.assertEqual(vals["uom_po_id"], 7)

    def test_pick_unidades_prefers_exact_name(self):
        rows = [
            {"id": 3, "name": "Unidad"},
            {"id": 9, "name": "Units"},
            {"id": 4, "name": "Unidades"},
        ]
        self.assertEqual(pick_unidades_uom(rows), 4)

    def test_pick_unidades_none(self):
        self.assertIsNone(pick_unidades_uom([{"id": 1, "name": "Horas"}]))


class TestCreateSupplierPartner(unittest.TestCase):
    @patch(
        "facturia_matching.odoo.catalog_create.odoo_execute_kw_with_config",
        return_value=55,
    )
    @patch(
        "facturia_matching.odoo.catalog_create.odoo_available_fields",
        side_effect=lambda _model, fields, _config: list(fields),
    )
    @patch("facturia_matching.odoo.catalog_create.is_odoo_config_ready", return_value=True)
    @patch(
        "facturia_matching.odoo.catalog_create.get_odoo_import_config",
        return_value={"db": "aliare", "base_url": "https://odoo.example"},
    )
    def test_create_sends_name_and_cuit(self, _cfg, _ready, _fields, mock_rpc):
        with odoo_profile_context("aliare"):
            out = create_supplier_partner("RAMASSOTTO", "20-11111111-1")
        self.assertEqual(out, {"id": 55, "name": "RAMASSOTTO", "vat": "20-11111111-1"})
        vals = mock_rpc.call_args.args[3][0]
        self.assertEqual(vals["name"], "RAMASSOTTO")
        self.assertEqual(vals["vat"], "20-11111111-1")
        self.assertEqual(vals["supplier_rank"], 1)

    def test_rejects_non_aliare(self):
        with odoo_profile_context("default"):
            with self.assertRaises(CatalogCreateError):
                create_supplier_partner("ACME", "20111111111")


if __name__ == "__main__":
    unittest.main()
