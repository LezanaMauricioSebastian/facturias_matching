"""Tests de vínculo OC/purchase, plan_product/reapply, overwrite precio y batch_write (import Odoo)."""
import unittest

from unittest.mock import patch

from facturia_matching.odoo.import_ import (
    _MOVE_LINE_PURCHASE_LINK_CACHE,
    _batch_write_move_lines,
    _build_line_command,
    _dedupe_group_oc_line_ids,
    _move_line_supports_purchase_link,
    _move_product_line_fields,
    _prepare_rows_for_import,
    _should_refresh_purchase_links,
    apply_purchase_order_price_overwrites,
    group_wants_overwrite_oc_price,
    plan_product_line_content_updates,
    plan_product_price_quantity_reapply,
    plan_purchase_line_updates,
    sanitize_group_purchase_lines,
)


class TestOdooImport(unittest.TestCase):
    @patch("facturia_matching.odoo.import_._utils.odoo_execute_kw_with_config")
    def test_move_product_line_fields_omits_purchase_when_unsupported(self, mock_rpc):
        _MOVE_LINE_PURCHASE_LINK_CACHE.clear()
        mock_rpc.return_value = {"id": {}, "name": {}, "tax_ids": {}}
        cfg = {"base_url": "https://sudata.odoo.com", "db": "sudata"}
        self.assertFalse(_move_line_supports_purchase_link(cfg))
        self.assertNotIn("purchase_line_id", _move_product_line_fields(cfg))

    @patch("facturia_matching.odoo.import_._utils.odoo_execute_kw_with_config")
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

    def test_build_line_command_includes_matched_product_uom(self):
        _cmd, _zero, vals = _build_line_command(
            {
                "invoice_line_ids/name": "Item UM",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "100",
                "invoice_line_ids/account_id": "10",
                "invoice_line_ids/product_id": "575",
                "__um_empresa_id": "12",
            }
        )
        self.assertEqual(vals["product_uom_id"], 12)
        self.assertEqual(vals["product_id"], 575)

    def test_plan_product_line_content_updates_product_uom(self):
        product_lines = [
            {
                "id": 10,
                "name": "Item",
                "quantity": 2.0,
                "price_unit": 100.0,
                "product_id": [575, "X"],
                "product_uom_id": [1, "Units"],
                "account_id": [10, "A"],
            }
        ]
        rows = [
            {
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "100",
                "invoice_line_ids/product_id": "575",
                "invoice_line_ids/account_id": "10",
                "__um_empresa_id": "12",
            }
        ]
        updates, warnings = plan_product_line_content_updates(product_lines, rows)
        self.assertEqual(warnings, [])
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["write_vals"]["product_uom_id"], 12)

    def test_plan_product_price_quantity_reapply_restores_uom(self):
        product_lines = [
            {
                "id": 10,
                "name": "Item",
                "quantity": 2.0,
                "price_unit": 150.0,
                "product_id": [575, "X"],
                "product_uom_id": [1, "Units"],
                "purchase_line_id": [456, "PO/1"],
            }
        ]
        rows = [
            {
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "150",
                "invoice_line_ids/product_id": "575",
                "__oc_line_id": "456",
                "__um_empresa_id": "12",
            }
        ]
        updates, warnings = plan_product_price_quantity_reapply(product_lines, rows)
        self.assertEqual(warnings, [])
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["write_vals"], {"product_uom_id": 12})

    def test_uom_not_written_without_product(self):
        """UM huérfana (producto borrado por el usuario) no debe escribirse en Odoo."""
        _cmd, _zero, vals = _build_line_command(
            {
                "invoice_line_ids/name": "Item sin producto",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "100",
                "__um_empresa_id": "12",
            }
        )
        self.assertNotIn("product_uom_id", vals)

        product_lines = [
            {"id": 10, "name": "Item", "quantity": 2.0, "price_unit": 100.0, "product_uom_id": [1, "Units"]}
        ]
        rows = [
            {
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "100",
                "__um_empresa_id": "12",
            }
        ]
        updates, _ = plan_product_line_content_updates(product_lines, rows)
        self.assertEqual(updates, [])
        updates, _ = plan_product_price_quantity_reapply(product_lines, rows)
        self.assertEqual(updates, [])

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
            "facturia_matching.odoo.import_.purchase.odoo_execute_kw_with_config",
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

    @patch("facturia_matching.odoo.import_.purchase._move_line_supports_purchase_link", return_value=True)
    @patch("facturia_matching.odoo.import_.purchase.sanitize_group_purchase_lines", return_value=[])
    @patch("facturia_matching.odoo.import_.purchase._refresh_purchase_links", return_value=[])
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
                "__oc_name": "P0001",
            }
        ]

        def refresh_side_effect(target_rows, **_kwargs):
            target_rows[0]["__oc_line_id"] = "501"
            return []

        mock_refresh.side_effect = refresh_side_effect
        groups, warnings = _prepare_rows_for_import({"company_id": 1}, rows)
        self.assertEqual(mock_refresh.call_count, 1)
        mock_refresh.assert_called_with(rows, company_id=1)
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

    def test_plan_product_line_content_updates_writes_product_even_with_oc(self):
        """Con OC, igual escribir product_id (evita líneas vacías si el vínculo se omite)."""
        product_lines = [
            {
                "id": 10,
                "name": "Viejo",
                "product_id": False,
                "quantity": 1.0,
                "price_unit": 100.0,
                "account_id": [10, "Cuenta"],
            }
        ]
        rows = [
            {
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/product_id": "575",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "150",
                "invoice_line_ids/account_id": "10",
                "__oc_line_id": "456",
                "__um_empresa_id": "12",
            }
        ]
        updates, warnings = plan_product_line_content_updates(product_lines, rows)
        self.assertEqual(warnings, [])
        self.assertEqual(len(updates), 1)
        vals = updates[0]["write_vals"]
        self.assertEqual(vals["product_id"], 575)
        self.assertEqual(vals["product_uom_id"], 12)
        self.assertEqual(vals["quantity"], 2.0)

    def test_plan_product_price_quantity_reapply_po_price_differs(self):
        product_lines = [
            {
                "id": 10,
                "name": "Item",
                "quantity": 1.0,
                "price_unit": 100.0,
            }
        ]
        rows = [
            {
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "150",
                "__oc_line_id": "456",
            }
        ]
        updates, warnings = plan_product_price_quantity_reapply(product_lines, rows)
        self.assertEqual(warnings, [])
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["line_id"], 10)
        self.assertEqual(updates[0]["write_vals"]["price_unit"], 150.0)
        self.assertEqual(updates[0]["write_vals"]["quantity"], 2.0)

    def test_plan_product_price_quantity_reapply_non_oc_price_differs(self):
        product_lines = [
            {
                "id": 10,
                "name": "Item",
                "quantity": 1.0,
                "price_unit": 100.0,
            }
        ]
        rows = [
            {
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "150",
            }
        ]
        updates, _ = plan_product_price_quantity_reapply(product_lines, rows)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["write_vals"]["price_unit"], 150.0)

    def test_plan_product_price_quantity_reapply_matches_by_purchase_line_id(self):
        product_lines = [
            {
                "id": 10,
                "name": "A",
                "quantity": 1.0,
                "price_unit": 100.0,
                "purchase_line_id": [200, "PO/1"],
            },
            {
                "id": 11,
                "name": "B",
                "quantity": 1.0,
                "price_unit": 50.0,
                "purchase_line_id": [100, "PO/2"],
            },
        ]
        rows = [
            {
                "invoice_line_ids/name": "B",
                "invoice_line_ids/quantity": "3",
                "invoice_line_ids/price_unit": "999",
                "__oc_line_id": "100",
            },
            {
                "invoice_line_ids/name": "A",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "888",
                "__oc_line_id": "200",
            },
        ]
        updates, _ = plan_product_price_quantity_reapply(product_lines, rows)
        self.assertEqual(len(updates), 2)
        by_id = {u["line_id"]: u["write_vals"]["price_unit"] for u in updates}
        self.assertEqual(by_id[11], 999.0)
        self.assertEqual(by_id[10], 888.0)

    def test_plan_product_price_quantity_reapply_skips_unchanged(self):
        product_lines = [
            {
                "id": 10,
                "name": "Item",
                "quantity": 2.0,
                "price_unit": 150.0,
            }
        ]
        rows = [
            {
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "150",
                "__oc_line_id": "456",
            }
        ]
        updates, _ = plan_product_price_quantity_reapply(product_lines, rows)
        self.assertEqual(updates, [])

    def test_plan_product_price_quantity_reapply_salta_pack_lines_ui_vs_po(self):
        """Salta-like: 3 packs con precio UI ≠ PO; reapply escribe los 3 price_unit UI."""
        product_lines = [
            {
                "id": 101,
                "name": "COCA",
                "quantity": 5.0,
                "price_unit": 11058.03,
                "purchase_line_id": [501, "PO/coca"],
            },
            {
                "id": 102,
                "name": "BENEDICTINO",
                "quantity": 5.0,
                "price_unit": 8628.49,
                "purchase_line_id": [502, "PO/ben1"],
            },
            {
                "id": 103,
                "name": "BENEDICTINO 2",
                "quantity": 5.0,
                "price_unit": 8628.49,
                "purchase_line_id": [503, "PO/ben2"],
            },
        ]
        rows = [
            {
                "invoice_line_ids/name": "COCA-COLA 600*12 PET",
                "invoice_line_ids/quantity": "5",
                "invoice_line_ids/price_unit": "11658,03",
                "invoice_line_ids/product_id": "620",
                "__um_empresa_id": "100",
                "__oc_line_id": "501",
            },
            {
                "invoice_line_ids/name": "BENEDICTINO S/GAS",
                "invoice_line_ids/quantity": "5",
                "invoice_line_ids/price_unit": "10799,93",
                "invoice_line_ids/product_id": "621",
                "__um_empresa_id": "100",
                "__oc_line_id": "502",
            },
            {
                "invoice_line_ids/name": "BENEDICTINO C/GAS",
                "invoice_line_ids/quantity": "5",
                "invoice_line_ids/price_unit": "10799,93",
                "invoice_line_ids/product_id": "622",
                "__um_empresa_id": "100",
                "__oc_line_id": "503",
            },
        ]
        updates, warnings = plan_product_price_quantity_reapply(product_lines, rows)
        self.assertEqual(warnings, [])
        self.assertEqual(len(updates), 3)
        by_id = {u["line_id"]: u["write_vals"]["price_unit"] for u in updates}
        self.assertAlmostEqual(by_id[101], 11658.03, places=2)
        self.assertAlmostEqual(by_id[102], 10799.93, places=2)
        self.assertAlmostEqual(by_id[103], 10799.93, places=2)

    def test_plan_product_price_quantity_reapply_shared_oc_line_falls_back_to_index(self):
        """Si varias filas UI comparten el mismo __oc_line_id, no omitir reapply: usar índice."""
        product_lines = [
            {
                "id": 101,
                "name": "A",
                "quantity": 1.0,
                "price_unit": 10.0,
                "purchase_line_id": [999, "shared"],
            },
            {
                "id": 102,
                "name": "B",
                "quantity": 1.0,
                "price_unit": 20.0,
                "purchase_line_id": [999, "shared"],
            },
            {
                "id": 103,
                "name": "C",
                "quantity": 1.0,
                "price_unit": 30.0,
                "purchase_line_id": [999, "shared"],
            },
        ]
        rows = [
            {
                "invoice_line_ids/name": "A",
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "100",
                "__oc_line_id": "999",
            },
            {
                "invoice_line_ids/name": "B",
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "200",
                "__oc_line_id": "999",
            },
            {
                "invoice_line_ids/name": "C",
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "300",
                "__oc_line_id": "999",
            },
        ]
        updates, _ = plan_product_price_quantity_reapply(product_lines, rows)
        self.assertEqual(len(updates), 3)
        by_id = {u["line_id"]: u["write_vals"]["price_unit"] for u in updates}
        self.assertEqual(by_id[101], 100.0)
        self.assertEqual(by_id[102], 200.0)
        self.assertEqual(by_id[103], 300.0)

    def test_group_wants_overwrite_oc_price(self):
        self.assertFalse(group_wants_overwrite_oc_price([{"invoice_line_ids/name": "A"}]))
        self.assertTrue(
            group_wants_overwrite_oc_price(
                [{"invoice_line_ids/name": "A", "__overwrite_oc_price": "1"}]
            )
        )
        self.assertTrue(
            group_wants_overwrite_oc_price(
                [{"invoice_line_ids/name": "A", "__overwrite_oc_price": True}]
            )
        )

    @patch("facturia_matching.odoo.import_.purchase._move_line_supports_purchase_link", return_value=True)
    @patch("facturia_matching.odoo.import_.purchase.odoo_execute_kw_with_config")
    def test_apply_purchase_order_price_overwrites_writes_po_line(self, mock_rpc, _mock_ok):
        def rpc(_config, model, method, args, kwargs=None):
            if model == "purchase.order.line" and method == "search_read":
                return [{"id": 456, "price_unit": 100.0, "name": "PO line"}]
            if model == "purchase.order.line" and method == "write":
                return True
            raise AssertionError(f"unexpected {model}.{method}")

        mock_rpc.side_effect = rpc
        group = [
            {
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "150",
                "__oc_line_id": "456",
                "__overwrite_oc_price": "1",
            }
        ]
        updates, warnings = apply_purchase_order_price_overwrites({}, group)
        self.assertEqual(warnings, [])
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["po_line_id"], 456)
        self.assertEqual(updates[0]["old_price_unit"], 100.0)
        self.assertEqual(updates[0]["new_price_unit"], 150.0)
        write_calls = [
            c for c in mock_rpc.call_args_list if c.args[2] == "write"
        ]
        self.assertEqual(len(write_calls), 1)
        self.assertEqual(write_calls[0].args[3], [[456], {"price_unit": 150.0}])

    @patch("facturia_matching.odoo.import_.purchase._move_line_supports_purchase_link", return_value=True)
    @patch("facturia_matching.odoo.import_.purchase.odoo_execute_kw_with_config")
    def test_apply_purchase_order_price_overwrites_skips_without_flag(self, mock_rpc, _mock_ok):
        group = [
            {
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "150",
                "__oc_line_id": "456",
            }
        ]
        updates, warnings = apply_purchase_order_price_overwrites({}, group)
        self.assertEqual(updates, [])
        self.assertEqual(warnings, [])
        mock_rpc.assert_not_called()

    @patch("facturia_matching.odoo.import_.purchase._move_line_supports_purchase_link", return_value=True)
    @patch("facturia_matching.odoo.import_.purchase.odoo_execute_kw_with_config")
    def test_apply_purchase_order_price_overwrites_skips_unchanged(self, mock_rpc, _mock_ok):
        mock_rpc.return_value = [{"id": 456, "price_unit": 150.0, "name": "PO line"}]
        group = [
            {
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "150",
                "__oc_line_id": "456",
                "__overwrite_oc_price": "1",
            }
        ]
        updates, warnings = apply_purchase_order_price_overwrites({}, group)
        self.assertEqual(updates, [])
        self.assertEqual(warnings, [])
        self.assertEqual(mock_rpc.call_count, 1)
        self.assertEqual(mock_rpc.call_args.args[2], "search_read")

    def test_ui_invoice_price_overwrites_po_price_on_invoice_line(self):
        """Regresión: precio UI/FacturIA debe quedar en la línea de factura, no el de la OC."""
        product_lines = [
            {
                "id": 10,
                "name": "Producto Y",
                "quantity": 5.0,
                "price_unit": 80.0,
                "purchase_line_id": [456, "PO/99"],
            }
        ]
        rows = [
            {
                "invoice_line_ids/name": "Producto Y",
                "invoice_line_ids/quantity": "5",
                "invoice_line_ids/price_unit": "123.45",
                "__oc_line_id": "456",
            }
        ]
        updates, warnings = plan_product_price_quantity_reapply(product_lines, rows)
        self.assertEqual(warnings, [])
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["write_vals"]["price_unit"], 123.45)
        self.assertNotEqual(updates[0]["write_vals"]["price_unit"], 80.0)

    @patch("facturia_matching.odoo.import_.move_lines.odoo_execute_kw_with_config")
    def test_batch_write_move_lines_single_rpc(self, mock_rpc):
        _batch_write_move_lines(
            {},
            99,
            [
                {"line_id": 10, "write_vals": {"price_unit": 150.0}},
                {"line_id": 11, "write_vals": {"quantity": 2.0}},
            ],
        )
        mock_rpc.assert_called_once()
        self.assertEqual(mock_rpc.call_args[0][1], "account.move")
        self.assertEqual(mock_rpc.call_args[0][2], "write")
        write_vals = mock_rpc.call_args[0][3][1]
        self.assertEqual(write_vals["line_ids"][0], (1, 10, {"price_unit": 150.0}))

    @patch("facturia_matching.odoo.import_.move_lines.odoo_execute_kw_with_config")
    def test_batch_write_move_lines_fallback_on_access_denied(self, mock_rpc):
        updates = [
            {"line_id": 10, "write_vals": {"price_unit": 150.0}},
            {"line_id": 11, "write_vals": {"quantity": 2.0}},
        ]

        def side_effect(*args, **kwargs):
            if args[1] == "account.move":
                raise Exception("<Fault 3: 'Access Denied'>")
            return None

        mock_rpc.side_effect = side_effect
        warnings: list = []
        applied = _batch_write_move_lines({}, 99, updates, warnings, context="test")
        self.assertEqual(applied, updates)
        self.assertEqual(mock_rpc.call_count, 3)
        self.assertTrue(any("batch falló" in w for w in warnings))
        line_calls = [c for c in mock_rpc.call_args_list if c[0][1] == "account.move.line"]
        self.assertEqual(len(line_calls), 2)

    def test_should_refresh_purchase_links_skips_when_oc_ids_present(self):
        rows = [
            {
                "invoice_line_ids/name": "A",
                "invoice_line_ids/price_unit": "1",
                "__oc_line_id": "100",
                "__oc_name": "P0001",
            }
        ]
        self.assertFalse(_should_refresh_purchase_links(rows))

    def test_should_refresh_purchase_links_when_oc_name_without_line_id(self):
        rows = [
            {
                "invoice_line_ids/name": "A",
                "invoice_line_ids/price_unit": "1",
                "__oc_name": "P0001",
            }
        ]
        self.assertTrue(_should_refresh_purchase_links(rows))
