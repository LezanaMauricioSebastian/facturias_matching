"""Tests de agrupación, validación, build_move_vals, NC, find_existing y vencimientos (import Odoo)."""
import unittest

from unittest.mock import patch

from facturia_matching.odoo.import_ import (
    _DOC_TYPE_INFO_CACHE,
    _account_requires_maturity,
    _build_move_vals,
    _document_numbers_match,
    _find_existing_move,
    _invoice_due_date_from_group,
    _move_matches_document_number,
    _tax_line_amount_write_vals,
    _vendor_move_type_for_header,
    group_rows_into_invoices,
    plan_invoice_origin_update,
    plan_move_header_updates,
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
                "invoice_line_ids/account_id": "10",
            },
            {"invoice_line_ids/name": "linea 2"},
            {"invoice_line_ids/name": "linea 3"},
        ]
        out = propagate_invoice_headers(rows)
        self.assertEqual(out[1].get("partner_id"), "5")
        self.assertEqual(out[2].get("invoice_line_ids/account_id"), "10")

    def test_validate_propagates_account_to_all_lines(self):
        rows = [
            {
                "partner_id": "5",
                "journal_id": "2",
                "l10n_latam_document_number": "00001-00000001",
                "invoice_date": "01/06/2026",
                "invoice_line_ids/name": "linea 1",
                "invoice_line_ids/account_id": "10",
                "invoice_line_ids/price_unit": "100",
                "__comprobante_idx": 0,
            },
            {
                "invoice_line_ids/name": "linea 2",
                "invoice_line_ids/price_unit": "50",
                "__comprobante_idx": 0,
            },
            {
                "invoice_line_ids/name": "linea 3",
                "invoice_line_ids/price_unit": "25",
                "__comprobante_idx": 0,
            },
        ]
        self.assertIsNone(validate_rows_for_import(rows))

    def test_document_numbers_match(self):
        self.assertTrue(_document_numbers_match("00008-00051348", "0008-00051348"))
        self.assertFalse(_document_numbers_match("99999-00051348", "00008-00051348"))

    def test_move_matches_document_number_by_ref(self):
        move = {"ref": "00001-00000089", "l10n_latam_document_number": False}
        self.assertTrue(_move_matches_document_number(move, "00001-00000089"))

    def test_move_matches_document_number_by_name_suffix(self):
        move = {"name": "FC 00001-00000089", "ref": ""}
        self.assertTrue(_move_matches_document_number(move, "00001-00000089"))

    @patch("facturia_matching.odoo.import_.create.odoo_execute_kw_with_config")
    def test_find_existing_move_uses_ref_domain_not_latam_field(self, mock_rpc):
        mock_rpc.return_value = [
            {"id": 7, "name": "BILL/1", "state": "draft", "ref": "00001-00000089", "l10n_latam_document_number": "00001-00000089"}
        ]
        found = _find_existing_move({}, 5, "00001-00000089")
        self.assertEqual(found["id"], 7)
        first_domain = mock_rpc.call_args_list[0][0][3][0]
        self.assertNotIn("l10n_latam_document_number", str(first_domain))
        self.assertIn(("ref", "=", "00001-00000089"), first_domain)

    def test_build_move_vals_sets_ref_with_document_number(self):
        group = [
            {
                "partner_id": "5",
                "journal_id": "2",
                "l10n_latam_document_number": "00001-00000001",
                "invoice_date": "01/06/2026",
                "invoice_line_ids/name": "Linea 1",
                "invoice_line_ids/account_id": "10",
                "invoice_line_ids/price_unit": "100",
            },
        ]
        vals = _build_move_vals(group)
        self.assertEqual(vals["l10n_latam_document_number"], "00001-00000001")
        self.assertEqual(vals["ref"], "00001-00000001")
        self.assertEqual(vals["move_type"], "in_invoice")

    def test_build_move_vals_credit_note_uses_in_refund(self):
        group = [
            {
                "partner_id": "52",
                "journal_id": "2",
                "l10n_latam_document_number": "00066-00012394",
                "l10n_latam_document_type_id": "3",
                "__doc_type_label": "NOTAS DE CRÉDITO A",
                "invoice_date": "08/08/2026",
                "invoice_line_ids/name": "Linea 1",
                "invoice_line_ids/account_id": "10",
                "invoice_line_ids/price_unit": "100",
            },
        ]
        vals = _build_move_vals(group)
        self.assertEqual(vals["move_type"], "in_refund")
        self.assertEqual(vals["l10n_latam_document_type_id"], 3)

    def test_build_move_vals_fce_invoice_stays_in_invoice(self):
        group = [
            {
                "partner_id": "5",
                "journal_id": "2",
                "l10n_latam_document_number": "00001-00000002",
                "__doc_type_label": "FACTURA DE CRÉDITO ELECTRÓNICA MiPyMEs (FCE) A",
                "invoice_date": "01/06/2026",
                "invoice_line_ids/name": "Linea 1",
                "invoice_line_ids/account_id": "10",
                "invoice_line_ids/price_unit": "100",
            },
        ]
        vals = _build_move_vals(group)
        self.assertEqual(vals["move_type"], "in_invoice")

    @patch("facturia_matching.odoo.import_.create.odoo_execute_kw_with_config")
    def test_vendor_move_type_uses_odoo_internal_type(self, mock_rpc):
        _DOC_TYPE_INFO_CACHE.clear()
        mock_rpc.return_value = [{"id": 9, "internal_type": "credit_note", "name": "CREDIT NOTES A"}]
        header = {"l10n_latam_document_type_id": "9"}
        cfg = {"base_url": "https://odoo.example", "db": "prod"}
        self.assertEqual(_vendor_move_type_for_header(header, cfg), "in_refund")
        vals = _build_move_vals(
            [
                {
                    **header,
                    "partner_id": "1",
                    "journal_id": "2",
                    "invoice_date": "08/08/2026",
                    "invoice_line_ids/name": "x",
                    "invoice_line_ids/account_id": "10",
                    "invoice_line_ids/price_unit": "1",
                }
            ],
            cfg,
        )
        self.assertEqual(vals["move_type"], "in_refund")

    @patch("facturia_matching.odoo.import_.create.odoo_execute_kw_with_config")
    def test_find_existing_move_credit_note_searches_in_refund(self, mock_rpc):
        mock_rpc.return_value = [
            {
                "id": 88,
                "name": "NC/1",
                "state": "draft",
                "ref": "00066-00012394",
                "l10n_latam_document_number": "00066-00012394",
            }
        ]
        found = _find_existing_move({}, 52, "00066-00012394", move_type="in_refund")
        self.assertEqual(found["id"], 88)
        first_domain = mock_rpc.call_args_list[0][0][3][0]
        self.assertIn(("move_type", "=", "in_refund"), first_domain)
        self.assertIn(("ref", "=", "00066-00012394"), first_domain)

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
        self.assertNotIn("purchase_line_id", vals["invoice_line_ids"][0][2])
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

    def test_invoice_due_date_falls_back_to_invoice_date(self):
        group = [
            {
                "invoice_date": "01/04/2026",
                "invoice_date_due": "",
            }
        ]
        self.assertEqual(_invoice_due_date_from_group(group), "2026-04-01")

    def test_build_move_vals_sets_due_from_invoice_date_when_missing(self):
        group = [
            {
                "partner_id": "5",
                "journal_id": "2",
                "l10n_latam_document_number": "00001-00000001",
                "invoice_date": "01/04/2026",
                "invoice_line_ids/name": "Linea 1",
                "invoice_line_ids/account_id": "10",
                "invoice_line_ids/price_unit": "100",
            },
        ]
        vals = _build_move_vals(group)
        self.assertEqual(vals["invoice_date_due"], "2026-04-01")

    def test_plan_move_header_updates_sets_missing_due_date(self):
        move = {"invoice_date": "2026-04-01", "invoice_date_due": False}
        group = [
            {
                "invoice_date": "01/04/2026",
                "invoice_date_due": "16/04/2026",
            }
        ]
        plan = plan_move_header_updates(move, group)
        self.assertEqual(plan, {"invoice_date_due": "2026-04-16"})

    def test_tax_line_write_includes_maturity_on_payable_account(self):
        vals = _tax_line_amount_write_vals(
            3544.38,
            {"debit": 1.0, "credit": 0.0, "balance": 1.0},
            due_date_iso="2026-04-16",
            account_row={"id": 10, "account_type": "liability_payable"},
        )
        self.assertEqual(vals["date_maturity"], "2026-04-16")
        self.assertEqual(vals["debit"], 3544.38)

    def test_tax_line_write_skips_maturity_on_non_payable_account(self):
        vals = _tax_line_amount_write_vals(
            6000.0,
            {"debit": 1.0, "credit": 0.0, "balance": 1.0},
            due_date_iso="2026-04-16",
            account_row={"id": 11, "account_type": "liability_current"},
        )
        self.assertNotIn("date_maturity", vals)

    def test_account_requires_maturity(self):
        self.assertTrue(_account_requires_maturity({"account_type": "liability_payable"}))
        self.assertFalse(_account_requires_maturity({"account_type": "liability_current"}))

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
