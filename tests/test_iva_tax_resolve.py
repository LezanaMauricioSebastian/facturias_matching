"""Tests: resolución dinámica de IVA por tenant Odoo (Dinner vs Aliare)."""
import unittest
from unittest.mock import patch

from facturia_matching.odoo.import_ import (
    _tax_ids_for_odoo_line,
    collect_expected_tax_amounts_from_group,
    propagate_invoice_headers,
    group_rows_into_invoices,
)
from facturia_matching.padron.taxes import (
    build_csv_tax_ids_dot_id,
    clear_tax_padron_cache,
    _build_iva_semantics_from_taxes,
    resolve_iva_tax_id_for_pct,
    tax_id_for_csv_export,
)

DINNER_IVA_TAXES = [
    {"id": 55, "name": "IVA No Corresp", "amount": 0.0},
    {"id": 57, "name": "IVA No Grav", "amount": 0.0},
    {"id": 59, "name": "IVA Exen", "amount": 0.0},
    {"id": 61, "name": "IVA 10.5%", "amount": 10.5},
    {"id": 63, "name": "IVA 21%", "amount": 21.0},
    {"id": 65, "name": "IVA 27%", "amount": 27.0},
]

ALIARE_IVA_TAXES = [
    {"id": 55, "name": "IVA No Corresp", "amount": 0.0},
    {"id": 57, "name": "IVA No Grav", "amount": 0.0},
    {"id": 59, "name": "IVA Exen", "amount": 0.0},
    {"id": 61, "name": "IVA 0%", "amount": 0.0},
    {"id": 63, "name": "IVA 10.5%", "amount": 10.5},
    {"id": 65, "name": "IVA 21%", "amount": 21.0},
    {"id": 67, "name": "IVA 27%", "amount": 27.0},
]


class TestIvaTaxResolve(unittest.TestCase):
    def setUp(self):
        clear_tax_padron_cache()

    def tearDown(self):
        clear_tax_padron_cache()

    def test_dinner_21_maps_to_63(self):
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=DINNER_IVA_TAXES):
            self.assertEqual(resolve_iva_tax_id_for_pct("21"), 63)
            self.assertEqual(tax_id_for_csv_export({"iva_pct": "21"}), "63")

    def test_aliare_21_maps_to_65_not_63(self):
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES):
            self.assertEqual(resolve_iva_tax_id_for_pct("21"), 65)
            self.assertEqual(tax_id_for_csv_export({"iva_pct": "21"}), "65")

    def test_aliare_10_5_maps_to_63(self):
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES):
            self.assertEqual(resolve_iva_tax_id_for_pct("10,5"), 63)
            self.assertEqual(resolve_iva_tax_id_for_pct("10.5"), 63)

    def test_legacy_fallback_without_odoo(self):
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=[]):
            self.assertEqual(resolve_iva_tax_id_for_pct("21"), 63)
            self.assertEqual(resolve_iva_tax_id_for_pct("10,5"), 61)

    def test_padron_primary_remaps_dinner_27_on_aliare(self):
        dinner_semantics = _build_iva_semantics_from_taxes(DINNER_IVA_TAXES)
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES), patch(
            "facturia_matching.padron.taxes._padron_source_iva_semantics_by_id",
            return_value=dinner_semantics,
        ):
            row = {"_padron_tax_id_primary": "65"}
            self.assertEqual(tax_id_for_csv_export(row), "67")

    def test_padron_primary_remaps_dinner_id_on_aliare(self):
        dinner_semantics = _build_iva_semantics_from_taxes(DINNER_IVA_TAXES)
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES), patch(
            "facturia_matching.padron.taxes._padron_source_iva_semantics_by_id",
            return_value=dinner_semantics,
        ):
            row = {"_padron_tax_id_primary": "63"}
            self.assertEqual(tax_id_for_csv_export(row), "65")

    def test_dynamic_semantics_from_odoo_tax_rows(self):
        semantics = _build_iva_semantics_from_taxes(ALIARE_IVA_TAXES)
        self.assertEqual(semantics[65], "21")
        self.assertEqual(semantics[63], "10,5")
        self.assertEqual(semantics[67], "27")

    def test_iva_pct_wins_over_padron_primary(self):
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES):
            row = {"iva_pct": "21", "_padron_tax_id_primary": "63"}
            self.assertEqual(tax_id_for_csv_export(row), "65")

    def test_iva_pct_requires_line_tax(self):
        from facturia_matching.padron.taxes import iva_pct_requires_line_tax

        self.assertTrue(iva_pct_requires_line_tax("IVA Exento"))
        self.assertTrue(iva_pct_requires_line_tax("IVA No Gravado"))
        self.assertFalse(iva_pct_requires_line_tax("IVA No Corresponde"))
        self.assertFalse(iva_pct_requires_line_tax("0"))
        self.assertTrue(iva_pct_requires_line_tax("21"))

    def test_exento_single_line_includes_tax_id(self):
        row = {
            "iva_pct": "IVA Exento",
            "invoice_line_ids/name": "Producto",
            "invoice_line_ids/price_unit": "100",
            "invoice_line_ids/quantity": "1",
        }
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=DINNER_IVA_TAXES):
            groups = [propagate_invoice_headers(g) for g in group_rows_into_invoices([row])]
            group = groups[0]
            tax_ids = _tax_ids_for_odoo_line(group[0], group)
        self.assertEqual(tax_ids, [59])

    def test_meriti_import_assigns_aliare_21_tax(self):
        row = {
            "iva_pct": "21",
            "__fac_iva_montos": '{"21": "57255.38"}',
            "invoice_line_ids/name": "Consumos",
            "invoice_line_ids/price_unit": "272644.68",
            "invoice_line_ids/quantity": "1",
        }
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES):
            groups = [propagate_invoice_headers(g) for g in group_rows_into_invoices([row])]
            group = groups[0]
            tax_ids = _tax_ids_for_odoo_line(group[0], group)
            amounts = collect_expected_tax_amounts_from_group(group)
            csv_tax = build_csv_tax_ids_dot_id(row)
        self.assertEqual(tax_ids, [65])
        self.assertEqual(amounts, {65: 57255.38})
        self.assertEqual(csv_tax, "65")


if __name__ == "__main__":
    unittest.main()
