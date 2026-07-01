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

    def test_padron_primary_remaps_dinner_id_on_aliare(self):
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES):
            row = {"_padron_tax_id_primary": "63"}
            self.assertEqual(tax_id_for_csv_export(row), "65")

    def test_iva_pct_wins_over_padron_primary(self):
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES):
            row = {"iva_pct": "21", "_padron_tax_id_primary": "63"}
            self.assertEqual(tax_id_for_csv_export(row), "65")

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
