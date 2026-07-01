"""Tests unitarios para agrupación/validación de import Odoo (sin llamar a la API)."""
import unittest

from unittest.mock import patch

from facturia_matching.core.comprobante_tax import classify_comprobante_tax_mode
from facturia_matching.odoo.import_ import (
    _build_line_command,
    _build_move_vals,
    _document_numbers_match,
    _find_existing_move,
    _move_line_supports_purchase_link,
    _move_matches_document_number,
    _move_product_line_fields,
    _MOVE_LINE_PURCHASE_LINK_CACHE,
    _tax_ids_for_odoo_line,
    collect_expected_tax_amounts_from_group,
    group_rows_into_invoices,
    plan_invoice_origin_update,
    plan_move_header_updates,
    _invoice_due_date_from_group,
    _account_requires_maturity,
    _tax_line_amount_write_vals,
    plan_line_tax_updates,
    plan_product_line_content_updates,
    plan_purchase_line_updates,
    plan_tax_line_amount_overwrites,
    propagate_invoice_headers,
    sanitize_group_purchase_lines,
    _dedupe_group_oc_line_ids,
    _prepare_rows_for_import,
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

    def test_move_matches_document_number_by_ref(self):
        move = {"ref": "00001-00000089", "l10n_latam_document_number": False}
        self.assertTrue(_move_matches_document_number(move, "00001-00000089"))

    def test_move_matches_document_number_by_name_suffix(self):
        move = {"name": "FC 00001-00000089", "ref": ""}
        self.assertTrue(_move_matches_document_number(move, "00001-00000089"))

    @patch("facturia_matching.odoo.import_.odoo_execute_kw_with_config")
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

    @patch("facturia_matching.odoo.import_.odoo_execute_kw_with_config")
    def test_move_product_line_fields_omits_purchase_when_unsupported(self, mock_rpc):
        _MOVE_LINE_PURCHASE_LINK_CACHE.clear()
        mock_rpc.return_value = {"id": {}, "name": {}, "tax_ids": {}}
        cfg = {"base_url": "https://sudata.odoo.com", "db": "sudata"}
        self.assertFalse(_move_line_supports_purchase_link(cfg))
        self.assertNotIn("purchase_line_id", _move_product_line_fields(cfg))

    @patch("facturia_matching.odoo.import_.odoo_execute_kw_with_config")
    def test_plan_purchase_line_updates_skips_without_purchase_field(self, mock_rpc):
        _MOVE_LINE_PURCHASE_LINK_CACHE.clear()
        mock_rpc.return_value = {"id": {}}
        cfg = {"base_url": "https://x.odoo.com", "db": "x"}
        updates, warnings = plan_purchase_line_updates(
            [{"id": 1, "purchase_line_id": False}],
            [{"invoice_line_ids/name": "a", "__oc_line_id": "9"}],
            config=cfg,
        )
        self.assertEqual(updates, [])
        self.assertEqual(warnings, [])

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

    def test_plan_line_tax_updates_clears_when_iva_zero(self):
        product_lines = [
            {"id": 10, "name": "A", "tax_ids": [63]},
            {"id": 11, "name": "B", "tax_ids": [61]},
        ]
        rows = [
            {"iva_pct": "21%", "invoice_line_ids/name": "A", "invoice_line_ids/price_unit": "100"},
            {"iva_pct": "0", "invoice_line_ids/name": "B", "invoice_line_ids/price_unit": "50"},
        ]
        updates, warnings = plan_line_tax_updates(product_lines, rows)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["line_id"], 11)
        self.assertEqual(updates[0]["new_tax_ids"], [])
        self.assertEqual(warnings, [])

    def test_tax_ids_for_odoo_line_header_mode_strips_iva(self):
        group = [
            {
                "iva_pct": "0",
                "invoice_line_ids/name": "A",
                "invoice_line_ids/price_unit": "100",
                "__fac_iva_monto": "500",
            },
            {"iva_pct": "0", "invoice_line_ids/name": "B", "invoice_line_ids/price_unit": "50"},
        ]
        self.assertEqual(classify_comprobante_tax_mode(group), "header")
        self.assertEqual(_tax_ids_for_odoo_line(group[0], group), [])
        self.assertEqual(_tax_ids_for_odoo_line(group[1], group), [])

    def test_tax_ids_for_odoo_line_mixed_mode_only_lines_with_rate(self):
        group = [
            {
                "iva_pct": "21",
                "otros_impuestos": "Percepción Ganancias Sufrida",
                "_padron_other_tax_ids": ["27"],
                "invoice_line_ids/name": "A",
                "invoice_line_ids/price_unit": "100",
                "__fac_iva_monto": "500",
            },
            {"iva_pct": "0", "invoice_line_ids/name": "B", "invoice_line_ids/price_unit": "50"},
        ]
        with patch("facturia_matching.padron.taxes.resolve_tax_label_to_id", return_value=27):
            line_a = _tax_ids_for_odoo_line(group[0], group)
            line_b = _tax_ids_for_odoo_line(group[1], group)
        self.assertEqual(line_a, [63, 27])
        self.assertEqual(line_b, [])

    def test_build_line_command_clears_taxes_when_iva_zero(self):
        _cmd, _zero, vals = _build_line_command(
            {
                "invoice_line_ids/name": "Sin IVA",
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "50",
                "invoice_line_ids/account_id": "10",
                "iva_pct": "0",
            }
        )
        self.assertEqual(vals["tax_ids"], [(6, 0, [])])

    def test_plan_line_tax_updates_skips_unchanged(self):
        product_lines = [{"id": 10, "name": "X", "tax_ids": [63]}]
        rows = [{"iva_pct": "21%", "invoice_line_ids/name": "X", "invoice_line_ids/price_unit": "1"}]
        updates, _ = plan_line_tax_updates(product_lines, rows)
        self.assertEqual(updates, [])

    def test_collect_expected_tax_amounts_splits_iva_by_rate(self):
        rows = [
            {
                "iva_pct": "21",
                "invoice_line_ids/name": "A",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "33019.55",
            },
            {
                "iva_pct": "10.5",
                "invoice_line_ids/name": "B",
                "invoice_line_ids/quantity": "10",
                "invoice_line_ids/price_unit": "964.37",
            },
            {
                "iva_pct": "21",
                "invoice_line_ids/name": "C",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "13489.27",
            },
        ]
        amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertIn(63, amounts)
        self.assertIn(61, amounts)
        self.assertAlmostEqual(amounts[61], 1012.59, places=2)
        self.assertAlmostEqual(amounts[63], 19533.7, places=1)

    def test_collect_expected_tax_amounts_header_mode(self):
        rows = [
            {
                "iva_pct": "21",
                "__fac_iva_monto": "57255,38",
                "otros_impuestos": "Percepción IIBB CABA Sufrida",
                "otros_impuestos_monto": "150,25",
                "_padron_other_tax_ids": ["1"],
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/price_unit": "10000",
            }
        ]
        amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertEqual(amounts.get(63), 57255.38)
        self.assertIn(1, amounts)
        self.assertEqual(amounts[1], 150.25)

    def test_collect_expected_tax_amounts_line_mode(self):
        rows = [
            {
                "iva_pct": "21",
                "__fac_iva_monto": "2100",
                "invoice_line_ids/name": "A",
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "5000",
            },
            {
                "iva_pct": "21",
                "invoice_line_ids/name": "B",
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "5000",
            },
        ]
        amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertEqual(amounts.get(63), 2100.0)

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

    def test_tax_ids_for_odoo_line_pure_line_mode(self):
        group = [
            {
                "iva_pct": "21",
                "invoice_line_ids/name": "A",
                "invoice_line_ids/price_unit": "1000",
                "invoice_line_ids/quantity": "1",
                "__fac_iva_monto": "315",
            },
            {
                "iva_pct": "10.5",
                "invoice_line_ids/name": "B",
                "invoice_line_ids/price_unit": "1000",
                "invoice_line_ids/quantity": "1",
            },
        ]
        self.assertEqual(classify_comprobante_tax_mode(group), "line")
        self.assertEqual(_tax_ids_for_odoo_line(group[0], group), [63])
        self.assertEqual(_tax_ids_for_odoo_line(group[1], group), [61])

    def test_collect_expected_header_mode_uses_explicit_montos(self):
        rows = [
            {
                "iva_pct": "0",
                "__fac_iva_montos": '{"21": "210"}',
                "__fac_iva_monto": "210",
                "invoice_line_ids/name": "x",
                "invoice_line_ids/price_unit": "1000",
                "invoice_line_ids/quantity": "1",
            }
        ]
        self.assertEqual(classify_comprobante_tax_mode(rows), "header")
        amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertEqual(amounts.get(63), 210.0)

    def test_collect_expected_mixed_mode_uses_explicit_json(self):
        rows = [
            {
                "iva_pct": "21",
                "__fac_iva_montos": '{"21": "500"}',
                "__fac_iva_monto": "500",
                "invoice_line_ids/name": "A",
                "invoice_line_ids/price_unit": "100",
                "invoice_line_ids/quantity": "1",
            },
            {
                "iva_pct": "0",
                "invoice_line_ids/name": "B",
                "invoice_line_ids/price_unit": "50",
                "invoice_line_ids/quantity": "1",
            },
        ]
        self.assertEqual(classify_comprobante_tax_mode(rows), "mixed")
        amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertEqual(amounts.get(63), 500.0)

    def test_plan_tax_line_overwrites_multi_iva_rates(self):
        tax_lines = [
            {
                "id": 100,
                "name": "IVA 21%",
                "tax_line_id": 63,
                "balance": 100.0,
                "debit": 100.0,
                "credit": 0.0,
            },
            {
                "id": 101,
                "name": "IVA 10.5%",
                "tax_line_id": 61,
                "balance": 50.0,
                "debit": 50.0,
                "credit": 0.0,
            },
        ]
        expected = {63: 18726.13, 61: 1012.59}
        updates, warnings = plan_tax_line_amount_overwrites(tax_lines, expected)
        self.assertEqual(len(updates), 2)
        self.assertEqual(updates[0]["new_amount"], 18726.13)
        self.assertEqual(updates[1]["new_amount"], 1012.59)
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

    def test_plan_purchase_line_updates_skips_unchanged(self):
        product_lines = [{"id": 10, "name": "A", "purchase_line_id": False}]
        rows = [{"invoice_line_ids/name": "A", "invoice_line_ids/price_unit": "1"}]
        updates, _ = plan_purchase_line_updates(product_lines, rows)
        self.assertEqual(updates, [])

    def test_sanitize_group_purchase_lines_clears_missing_ids(self):
        group = [
            {
                "invoice_line_ids/name": "Item",
                "__oc_line_id": "99999",
                "__oc_name": "P09999",
            }
        ]
        with patch(
            "facturia_matching.odoo.import_.odoo_execute_kw_with_config",
            return_value=[],
        ):
            warnings = sanitize_group_purchase_lines({}, group)
        self.assertEqual(len(warnings), 1)
        self.assertIn("99999", warnings[0])
        self.assertEqual(group[0].get("__oc_line_id"), "")

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
        self.assertEqual(updates, [])

    def test_dedupe_group_oc_line_ids_keeps_first_only(self):
        group = [
            {
                "invoice_line_ids/name": "A",
                "invoice_line_ids/price_unit": "1",
                "__oc_line_id": "100",
            },
            {
                "invoice_line_ids/name": "B",
                "invoice_line_ids/price_unit": "2",
                "__oc_line_id": "100",
            },
        ]
        warnings = _dedupe_group_oc_line_ids(group)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(group[0]["__oc_line_id"], "100")
        self.assertEqual(group[1]["__oc_line_id"], "")

    @patch("facturia_matching.odoo.import_._move_line_supports_purchase_link", return_value=True)
    @patch("facturia_matching.odoo.import_.sanitize_group_purchase_lines", return_value=[])
    @patch("facturia_matching.odoo.import_._refresh_purchase_links", return_value=[])
    def test_prepare_rows_for_import_refreshes_oc_before_grouping(
        self, mock_refresh, _mock_sanitize, _mock_po
    ):
        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "1",
                "journal_id": "2",
                "l10n_latam_document_number": "0001",
                "invoice_date": "01/06/2026",
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/account_id": "10",
                "invoice_line_ids/price_unit": "1",
            }
        ]

        def refresh_side_effect(target_rows):
            target_rows[0]["__oc_line_id"] = "501"
            return []

        mock_refresh.side_effect = refresh_side_effect
        groups, warnings = _prepare_rows_for_import({}, rows)
        self.assertEqual(mock_refresh.call_count, 1)
        self.assertEqual(groups[0][0]["__oc_line_id"], "501")
        self.assertEqual(warnings, [])

    def test_plan_product_line_content_updates_qty_and_product(self):
        product_lines = [
            {
                "id": 10,
                "name": "Viejo",
                "product_id": [5, "Prod A"],
                "quantity": 1.0,
                "price_unit": 100.0,
                "account_id": [10, "Cuenta"],
            }
        ]
        rows = [
            {
                "invoice_line_ids/name": "Nuevo",
                "invoice_line_ids/product_id": "99",
                "invoice_line_ids/quantity": "3",
                "invoice_line_ids/price_unit": "150",
                "invoice_line_ids/account_id": "10",
            }
        ]
        updates, warnings = plan_product_line_content_updates(product_lines, rows)
        self.assertEqual(warnings, [])
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["line_id"], 10)
        vals = updates[0]["write_vals"]
        self.assertEqual(vals["product_id"], 99)
        self.assertEqual(vals["quantity"], 3.0)
        self.assertEqual(vals["price_unit"], 150.0)
        self.assertEqual(vals["name"], "Nuevo")

    def test_plan_product_line_content_updates_skips_unchanged(self):
        product_lines = [
            {
                "id": 10,
                "name": "Item",
                "product_id": [5, "Prod"],
                "quantity": 2.0,
                "price_unit": 50.0,
                "account_id": [10, "Cuenta"],
            }
        ]
        rows = [
            {
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/product_id": "5",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "50",
                "invoice_line_ids/account_id": "10",
            }
        ]
        updates, _ = plan_product_line_content_updates(product_lines, rows)
        self.assertEqual(updates, [])

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
