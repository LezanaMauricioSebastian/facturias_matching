"""Tests unitarios para agrupación/validación de import Odoo (sin llamar a la API)."""
import unittest

from facturia_matching.odoo_import import (
    _document_numbers_match,
    collect_expected_tax_amounts_from_group,
    group_rows_into_invoices,
    plan_line_tax_updates,
    plan_tax_line_amount_overwrites,
    propagate_invoice_headers,
    validate_rows_for_import,
)


class TestOdooImport(unittest.TestCase):
    def test_group_by_comprobante_idx(self):
        rows = [
            {"__comprobante_idx": 0, "l10n_latam_document_number": "00001-00000001"},
            {"__comprobante_idx": 0, "l10n_latam_document_number": ""},
            {"__comprobante_idx": 1, "l10n_latam_document_number": "00002-00000002"},
        ]
        groups = group_rows_into_invoices(rows)
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups[0]), 2)

    def test_validate_requires_partner(self):
        rows = [
            {
                "partner_id": "",
                "journal_id": "1",
                "l10n_latam_document_number": "00001-00000001",
                "invoice_date": "01/06/2026",
                "invoice_line_ids/name": "x",
                "invoice_line_ids/account_id": "10",
                "invoice_line_ids/price_unit": "100",
            }
        ]
        err = validate_rows_for_import(rows)
        self.assertIn("proveedor", err or "")

    def test_propagate_header(self):
        rows = [
            {
                "partner_id": "5",
                "journal_id": "2",
                "l10n_latam_document_number": "00001-00000001",
                "invoice_date": "01/06/2026",
            },
            {"invoice_line_ids/name": "linea 2"},
        ]
        out = propagate_invoice_headers(rows)
        self.assertEqual(out[1].get("partner_id"), "5")

    def test_document_numbers_match(self):
        self.assertTrue(_document_numbers_match("00008-00051348", "0008-00051348"))
        self.assertFalse(_document_numbers_match("99999-00051348", "00008-00051348"))

    def test_plan_line_tax_updates_by_order(self):
        product_lines = [
            {"id": 10, "name": "Producto A", "tax_ids": [53]},
            {"id": 11, "name": "Producto B", "tax_ids": [53]},
        ]
        rows = [
            {"iva_pct": "21%", "invoice_line_ids/name": "A", "invoice_line_ids/price_unit": "100"},
            {"iva_pct": "10.5%", "invoice_line_ids/name": "B", "invoice_line_ids/price_unit": "50"},
        ]
        updates, warnings = plan_line_tax_updates(product_lines, rows)
        self.assertEqual(len(updates), 2)
        self.assertEqual(updates[0]["line_id"], 10)
        self.assertEqual(updates[0]["new_tax_ids"], [63])
        self.assertEqual(updates[1]["new_tax_ids"], [61])
        self.assertEqual(warnings, [])

    def test_plan_line_tax_updates_skips_unchanged(self):
        product_lines = [{"id": 10, "name": "X", "tax_ids": [63]}]
        rows = [{"iva_pct": "21%", "invoice_line_ids/name": "X", "invoice_line_ids/price_unit": "1"}]
        updates, _ = plan_line_tax_updates(product_lines, rows)
        self.assertEqual(updates, [])

    def test_collect_expected_tax_amounts(self):
        rows = [
            {
                "iva_pct": "21%",
                "iva_monto": "2100,50",
                "otros_impuestos": "Percepción IIBB CABA Sufrida",
                "otros_impuestos_monto": "150,25",
                "_padron_other_tax_ids": ["1"],
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/price_unit": "10000",
            }
        ]
        amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertEqual(amounts.get(63), 2100.5)
        self.assertIn(1, amounts)
        self.assertEqual(amounts[1], 150.25)

    def test_plan_tax_line_amount_overwrites(self):
        tax_lines = [
            {
                "id": 100,
                "name": "IVA 21%",
                "tax_line_id": 63,
                "balance": 1000.0,
                "debit": 1000.0,
                "credit": 0.0,
            },
            {
                "id": 101,
                "name": "Percepción IIBB",
                "tax_line_id": 1,
                "balance": 50.0,
                "debit": 50.0,
                "credit": 0.0,
            },
        ]
        expected = {63: 2100.5, 1: 150.25}
        updates, warnings = plan_tax_line_amount_overwrites(tax_lines, expected)
        self.assertEqual(len(updates), 2)
        self.assertEqual(updates[0]["new_amount"], 2100.5)
        self.assertEqual(updates[1]["new_amount"], 150.25)
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
