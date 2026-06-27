"""Tests unitarios para agrupación/validación de import Odoo (sin llamar a la API)."""
import unittest

from facturia_matching.odoo_import import (
    _build_line_command,
    _build_move_vals,
    _document_numbers_match,
    collect_expected_tax_amounts_from_group,
    group_rows_into_invoices,
    plan_invoice_origin_update,
    plan_line_tax_updates,
    plan_purchase_line_updates,
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

    def test_build_line_command_links_purchase_line(self):
        _cmd, _zero, vals = _build_line_command(
            {
                "invoice_line_ids/name": "Item OC",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "100",
                "invoice_line_ids/account_id": "10",
                "__oc_line_id": "456",
            }
        )
        self.assertEqual(vals["purchase_line_id"], 456)

    def test_build_line_command_without_oc_line(self):
        _cmd, _zero, vals = _build_line_command(
            {
                "invoice_line_ids/name": "Item suelto",
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "50",
                "invoice_line_ids/account_id": "10",
            }
        )
        self.assertNotIn("purchase_line_id", vals)

    def test_build_move_vals_sets_invoice_origin_from_selected_oc(self):
        group = [
            {
                "partner_id": "5",
                "journal_id": "2",
                "l10n_latam_document_number": "00001-00000001",
                "invoice_date": "01/06/2026",
                "__selected_oc_name": "P06345",
                "invoice_line_ids/name": "Linea 1",
                "invoice_line_ids/account_id": "10",
                "invoice_line_ids/price_unit": "100",
                "__oc_line_id": "100",
            },
            {
                "invoice_line_ids/name": "Linea 2",
                "invoice_line_ids/account_id": "10",
                "invoice_line_ids/price_unit": "50",
                "__oc_name": "P99999",
            },
        ]
        vals = _build_move_vals(group)
        self.assertEqual(vals["invoice_origin"], "P06345")
        self.assertEqual(vals["invoice_line_ids"][0][2]["purchase_line_id"], 100)
        self.assertNotIn("purchase_line_id", vals["invoice_line_ids"][1][2])

    def test_build_move_vals_invoice_origin_from_oc_names(self):
        group = [
            {
                "partner_id": "5",
                "journal_id": "2",
                "l10n_latam_document_number": "00001-00000001",
                "invoice_date": "01/06/2026",
                "invoice_line_ids/name": "A",
                "invoice_line_ids/account_id": "10",
                "invoice_line_ids/price_unit": "1",
                "__oc_name": "P001",
            },
            {
                "invoice_line_ids/name": "B",
                "invoice_line_ids/account_id": "10",
                "invoice_line_ids/price_unit": "2",
                "__oc_name": "P002",
            },
        ]
        vals = _build_move_vals(group)
        self.assertEqual(vals["invoice_origin"], "P001, P002")

    def test_plan_purchase_line_updates_changes_oc(self):
        product_lines = [
            {"id": 10, "name": "A", "purchase_line_id": [100, "PO/100"]},
            {"id": 11, "name": "B", "purchase_line_id": False},
        ]
        rows = [
            {
                "invoice_line_ids/name": "A",
                "invoice_line_ids/price_unit": "1",
                "__oc_line_id": "200",
            },
            {
                "invoice_line_ids/name": "B",
                "invoice_line_ids/price_unit": "2",
                "__oc_line_id": "300",
            },
        ]
        updates, warnings = plan_purchase_line_updates(product_lines, rows)
        self.assertEqual(len(updates), 2)
        self.assertEqual(updates[0]["new_purchase_line_id"], 200)
        self.assertEqual(updates[1]["new_purchase_line_id"], 300)
        self.assertEqual(warnings, [])

    def test_plan_purchase_line_updates_clears_oc(self):
        product_lines = [{"id": 10, "name": "A", "purchase_line_id": [100, "PO/100"]}]
        rows = [{"invoice_line_ids/name": "A", "invoice_line_ids/price_unit": "1"}]
        updates, _ = plan_purchase_line_updates(product_lines, rows)
        self.assertEqual(len(updates), 1)
        self.assertIsNone(updates[0]["new_purchase_line_id"])

    def test_plan_invoice_origin_update(self):
        group = [
            {
                "invoice_line_ids/name": "x",
                "invoice_line_ids/price_unit": "1",
                "__selected_oc_name": "PNEW",
            }
        ]
        plan = plan_invoice_origin_update("POLD", group)
        self.assertEqual(plan["new_invoice_origin"], "PNEW")
        self.assertIsNone(plan_invoice_origin_update("PNEW", group))


if __name__ == "__main__":
    unittest.main()
