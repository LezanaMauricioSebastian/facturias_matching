"""Tests for purchase order matching and UOM scaling."""
import unittest
from unittest.mock import patch

from facturia_matching.odoo.purchase_matching import (
    _canonical_um,
    _extract_qty_um_from_description,
    _line_match_score,
    _ocr_fix_token,
    _partner_po_search_domain,
    _resolve_invoice_qty_um,
    _resolve_selected_oc,
    _saved_oc_order_id,
    _set_comprobante_oc_selection,
    apply_oc_selection,
    compute_show_purchase_columns,
    convert_qty,
    enrich_rows_with_purchase_data,
    fetch_partner_po_lines,
    has_any_oc_candidates,
    match_invoice_row,
    rematch_comprobante_purchase,
    resolve_uom,
    row_has_odoo_purchase_data,
    score_oc_candidates,
)


class TestPurchaseMatching(unittest.TestCase):
    def test_canonical_um(self):
        self.assertEqual(_canonical_um("unidad(es)"), "Units")
        self.assertEqual(_canonical_um("kgs"), "kg")

    def test_partner_po_search_domain_includes_all_receipt_statuses(self):
        domain = _partner_po_search_domain(42)
        self.assertIn(("partner_id", "child_of", 42), domain)
        self.assertNotIn(("receipt_status", "!=", "pending"), domain)

    def test_receipt_status_label(self):
        from facturia_matching.odoo.purchase_matching import _receipt_status_label

        self.assertEqual(_receipt_status_label("pending"), "No recepcionada")
        self.assertEqual(_receipt_status_label("full"), "Recepcionada")

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.odoo_search_read")
    @patch("facturia_matching.odoo.purchase_matching._resolve_po_partner_scope", return_value=42)
    def test_fetch_partner_po_lines_includes_receipt_and_deliver_fields(
        self, _mock_scope, mock_search_read, _mock_odoo
    ):
        from facturia_matching.odoo.purchase_matching import clear_purchase_cache

        clear_purchase_cache()
        mock_search_read.side_effect = [
            [
                {
                    "id": 10,
                    "name": "P001",
                    "partner_ref": "",
                    "date_order": "2026-01-01",
                    "receipt_status": "pending",
                    "picking_type_id": [1, "WH/IN"],
                    "dest_address_id": [5, "Depósito Central"],
                }
            ],
            [
                {
                    "id": 100,
                    "order_id": [10, "P001"],
                    "name": "Line",
                    "product_id": [1, "Prod"],
                    "product_qty": 1,
                    "qty_received": 0,
                    "qty_invoiced": 0,
                    "price_unit": 10,
                    "product_uom": [1, "Units"],
                }
            ],
        ]

        lines = fetch_partner_po_lines(99)

        po_call = mock_search_read.call_args_list[0]
        self.assertEqual(po_call.args[0], "purchase.order")
        self.assertNotIn(("receipt_status", "!=", "pending"), po_call.args[1])
        self.assertIn("receipt_status", po_call.args[2])
        self.assertEqual(lines[0]["receipt_status_label"], "No recepcionada")
        self.assertEqual(lines[0]["deliver_to"], "Depósito Central")

    def test_extract_qty_um_from_description(self):
        qty, um = _extract_qty_um_from_description("6 kg pan líquido")
        self.assertAlmostEqual(qty, 6.0)
        self.assertEqual(um, "kg")

    def test_resolve_invoice_qty_prefers_facturia_over_package_size(self):
        row = {
            "invoice_line_ids/quantity": "1",
            "__fac_item_cantidad": "10",
            "__um_proveedor": "UN",
        }
        qty, um = _resolve_invoice_qty_um(
            row,
            "AZUCAR COMUN X 1 KG.",
            repair_row=True,
        )
        self.assertEqual(qty, 10.0)
        self.assertEqual(um, "UN")
        self.assertEqual(row["invoice_line_ids/quantity"], "10")

    def test_resolve_invoice_qty_repairs_saved_desc_pollution(self):
        row = {
            "invoice_line_ids/quantity": "2840",
            "__fac_item_cantidad": "6",
            "__um_proveedor": "UN",
        }
        qty, _ = _resolve_invoice_qty_um(
            row,
            "CHAMP. CARACAS FILETEADO X 2840 G",
            repair_row=True,
        )
        self.assertEqual(qty, 6.0)
        self.assertEqual(row["invoice_line_ids/quantity"], "6")

    def test_resolve_invoice_qty_repairs_partial_sanitize_to_one(self):
        row = {
            "invoice_line_ids/quantity": "1",
            "__fac_item_cantidad": "6",
            "__um_proveedor": "UN",
        }
        qty, _ = _resolve_invoice_qty_um(
            row,
            "CHAMP. CARACAS FILETEADO X 2840 G",
            repair_row=True,
        )
        self.assertEqual(qty, 6.0)
        self.assertEqual(row["invoice_line_ids/quantity"], "6")

    def test_resolve_invoice_qty_keeps_manual_edit(self):
        row = {
            "invoice_line_ids/quantity": "5",
            "__fac_item_cantidad": "10",
            "__um_proveedor": "UN",
        }
        qty, _ = _resolve_invoice_qty_um(
            row,
            "AZUCAR COMUN X 1 KG.",
            repair_row=True,
        )
        self.assertEqual(qty, 5.0)
        self.assertEqual(row["invoice_line_ids/quantity"], "5")

    def test_match_invoice_row_does_not_use_package_qty(self):
        row = {
            "invoice_line_ids/name": "BROCOLI MC CAIN X 2 KG.",
            "__item_codigo": "100908",
            "invoice_line_ids/quantity": "2",
            "__fac_item_cantidad": "1",
            "__um_proveedor": "UN",
        }
        out = match_invoice_row(row, [], {"by_name": {}, "by_id": {}})
        self.assertEqual(row["invoice_line_ids/quantity"], "1")
        self.assertEqual(out["__qty_original"], "1.0")

    def test_line_match_score_by_code(self):
        po = {"line_name": "MOT-ACTAB1", "product_qty": 3}
        sc = _line_match_score(codigo="MOT-ACTAB1", descripcion="acrílico", qty=3, po_line=po)
        self.assertGreaterEqual(sc, 99.0)

    def test_line_match_score_fuzzy_pan(self):
        po = {"line_name": "ALM-PAN FRANCES", "product_qty": 6}
        sc = _line_match_score(codigo="", descripcion="6 kg pan líquido", qty=6, po_line=po)
        self.assertGreaterEqual(sc, 70.0)

    def test_ocr_fix_token_choclo(self):
        self.assertEqual(_ocr_fix_token("CHOCL0"), "CHOCLO")

    def test_line_match_score_ocr_choclo(self):
        po = {"line_name": "CON-CHOCLO", "product_qty": 3}
        sc = _line_match_score(
            codigo="100967",
            descripcion="CHOCL0 MC CAIN X 2 KG.",
            qty=3,
            po_line=po,
        )
        self.assertGreaterEqual(sc, 75.0)

    def test_match_invoice_row_choclo_ocr(self):
        row = {
            "invoice_line_ids/name": "CHOCL0 MC CAIN X 2 KG.",
            "__item_codigo": "100967",
            "invoice_line_ids/quantity": "3",
            "__um_proveedor": "KG",
        }
        po_lines = [{"line_name": "CON-CHOCLO", "product_qty": 3, "product_id": 575, "order_name": "P06345", "order_id": 1, "line_id": 1, "partner_ref": "", "qty_received": 0, "qty_invoiced": 0, "product_uom_id": 12, "product_uom_name": "kg"}]
        out = match_invoice_row(row, po_lines, {"by_name": {}, "by_id": {}})
        self.assertIn("CON-CHOCLO", out["__oc_match_note"])
        self.assertEqual(row.get("invoice_line_ids/product_id"), "575")

    def test_match_invoice_row_suggests_product_from_pool_without_oc(self):
        """Sin OC vinculada, pero el proveedor tiene OCs: sugiere producto por fuzzy."""
        row = {
            "invoice_line_ids/name": "CHOCL0 MC CAIN X 2 KG.",
            "__item_codigo": "100967",
            "invoice_line_ids/quantity": "3",
            "__um_proveedor": "KG",
        }
        pool = [
            {
                "line_name": "CON-CHOCLO",
                "product_qty": 3,
                "product_id": 575,
                "order_name": "P06345",
                "order_id": 1,
                "line_id": 1,
                "partner_ref": "",
                "qty_received": 0,
                "qty_invoiced": 0,
                "product_uom_id": 12,
                "product_uom_name": "kg",
            }
        ]
        out = match_invoice_row(row, [], {"by_name": {}, "by_id": {}}, suggest_pool=pool)
        self.assertEqual(row.get("invoice_line_ids/product_id"), "575")
        self.assertTrue(out.get("__product_suggested"))
        self.assertFalse(out.get("__oc_line_id"))
        self.assertIn("sugerido", out["__oc_match_note"].lower())

    def test_match_invoice_row_no_suggestion_below_threshold(self):
        """Sin OC y sin match suficiente: no se sugiere producto."""
        row = {
            "invoice_line_ids/name": "TORNILLO HEXAGONAL 8MM",
            "__item_codigo": "",
            "invoice_line_ids/quantity": "2",
            "__um_proveedor": "UN",
        }
        pool = [
            {
                "line_name": "CON-CHOCLO",
                "product_qty": 99,
                "product_id": 575,
                "order_name": "P1",
                "order_id": 1,
                "line_id": 1,
                "partner_ref": "",
                "qty_received": 0,
                "qty_invoiced": 0,
                "product_uom_id": 12,
                "product_uom_name": "kg",
            }
        ]
        out = match_invoice_row(row, [], {"by_name": {}, "by_id": {}}, suggest_pool=pool)
        self.assertEqual(row.get("invoice_line_ids/product_id", ""), "")
        self.assertFalse(out.get("__product_suggested"))
        self.assertIn("Sin", out["__oc_match_note"])

    def test_convert_qty_same_category(self):
        from_uom = {"id": 13, "factor": 1000.0, "category_id": [2, "Weight"]}
        to_uom = {"id": 12, "factor": 1.0, "category_id": [2, "Weight"]}
        self.assertAlmostEqual(convert_qty(1000.0, from_uom, to_uom), 1.0)

    def test_apply_uom_scaling_sets_empresa_id(self):
        from facturia_matching.odoo.purchase_matching import _apply_uom_scaling

        catalog = {
            "by_id": {
                12: {"id": 12, "name": "kg", "factor": 1.0, "category_id": [2, "Weight"]},
                13: {"id": 13, "name": "g", "factor": 1000.0, "category_id": [2, "Weight"]},
            },
            "by_name": {
                "KG": {"id": 12, "name": "kg", "factor": 1.0, "category_id": [2, "Weight"]},
                "G": {"id": 13, "name": "g", "factor": 1000.0, "category_id": [2, "Weight"]},
            },
        }
        out = _apply_uom_scaling(
            {},
            invoice_qty=1000.0,
            invoice_um_raw="g",
            po_uom_id=12,
            po_uom_name="kg",
            uom_catalog=catalog,
        )
        self.assertEqual(out["um_empresa_id"], "12")
        self.assertEqual(out["um_note"], "Re-escalado")
        self.assertEqual(out["qty_escalada"], "1")

    def test_match_invoice_row_without_po(self):
        row = {
            "invoice_line_ids/name": "Producto X",
            "invoice_line_ids/quantity": "2",
            "__item_codigo": "",
            "__um_proveedor": "UN",
        }
        out = match_invoice_row(row, [], {"by_name": {}, "by_id": {}})
        self.assertIn("Sin OC", out["__oc_match_note"])

    def test_row_has_odoo_purchase_data_with_oc_match(self):
        self.assertTrue(
            row_has_odoo_purchase_data(
                {"__oc_line_id": "12", "__oc_match_note": "OC P001 · LINEA"}
            )
        )

    def test_row_has_odoo_purchase_data_without_odoo(self):
        self.assertFalse(
            row_has_odoo_purchase_data(
                {"__um_proveedor": "UN", "__oc_match_note": "Sin OC en Odoo"}
            )
        )

    def test_compute_show_purchase_columns(self):
        rows = [
            {"__um_proveedor": "UN", "__oc_match_note": "Sin OC en Odoo"},
            {"__oc_line_id": "9", "__oc_match_note": "OC P002 · X"},
        ]
        self.assertTrue(compute_show_purchase_columns(rows))
        self.assertFalse(
            compute_show_purchase_columns(
                [{"__oc_match_note": "Sin match OC"}, {"__oc_match_note": "Sin OC en Odoo"}]
            )
        )

    def test_score_oc_candidates_ranks_by_basket(self):
        invoice_rows = [
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": "CHOCL0 MC CAIN X 2 KG.",
                "__item_codigo": "100967",
                "invoice_line_ids/quantity": "3",
            },
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": "6 kg pan líquido",
                "__item_codigo": "",
                "invoice_line_ids/quantity": "6",
            },
        ]
        po_lines = [
            {
                "line_id": 1,
                "order_id": 10,
                "order_name": "P001",
                "partner_ref": "A",
                "line_name": "CON-CHOCLO",
                "product_qty": 3,
                "qty_received": 3,
                "qty_invoiced": 0,
            },
            {
                "line_id": 2,
                "order_id": 20,
                "order_name": "P002",
                "partner_ref": "B",
                "line_name": "CON-CHOCLO",
                "product_qty": 3,
                "qty_received": 0,
                "qty_invoiced": 0,
            },
            {
                "line_id": 3,
                "order_id": 20,
                "order_name": "P002",
                "partner_ref": "B",
                "line_name": "ALM-PAN FRANCES",
                "product_qty": 6,
                "qty_received": 6,
                "qty_invoiced": 0,
            },
        ]
        ranked = score_oc_candidates(invoice_rows, po_lines)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["order_id"], 20)
        self.assertEqual(ranked[0]["lines_matched"], 2)
        self.assertGreater(ranked[0]["basket_score"], ranked[1]["basket_score"])

    def test_resolve_selected_oc_prefers_saved(self):
        candidates = [
            {"order_id": 20, "order_name": "P002"},
            {"order_id": 10, "order_name": "P001"},
        ]
        oid, name = _resolve_selected_oc(candidates, 10)
        self.assertEqual(oid, 10)
        self.assertEqual(name, "P001")

    def test_resolve_selected_oc_auto_top(self):
        candidates = [
            {"order_id": 20, "order_name": "P002"},
            {"order_id": 10, "order_name": "P001"},
        ]
        oid, name = _resolve_selected_oc(candidates, None)
        self.assertEqual(oid, 20)
        self.assertEqual(name, "P002")

    def test_resolve_selected_oc_falls_back_when_saved_stale(self):
        candidates = [
            {"order_id": 20, "order_name": "P002"},
            {"order_id": 10, "order_name": "P001"},
        ]
        oid, name = _resolve_selected_oc(candidates, 99)
        self.assertEqual(oid, 20)
        self.assertEqual(name, "P002")

    def test_saved_and_set_comprobante_oc_selection(self):
        rows = [{"__comprobante_idx": 0}, {"__comprobante_idx": 0}]
        _set_comprobante_oc_selection(rows, 99, "P099")
        self.assertEqual(_saved_oc_order_id(rows), 99)
        self.assertEqual(rows[1]["__selected_oc_name"], "P099")

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.fetch_partner_po_lines")
    @patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
    def test_enrich_rows_auto_selects_top_oc(self, mock_uom, mock_fetch, _mock_odoo):
        mock_uom.return_value = {"by_name": {}, "by_id": {}}
        mock_fetch.return_value = [
            {
                "line_id": 1,
                "order_id": 10,
                "order_name": "P001",
                "partner_ref": "",
                "line_name": "CON-CHOCLO",
                "product_qty": 3,
                "qty_received": 3,
                "qty_invoiced": 0,
                "product_id": 575,
                "product_uom_id": None,
                "product_uom_name": "kg",
            }
        ]
        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "42",
                "invoice_line_ids/name": "CHOCL0 MC CAIN X 2 KG.",
                "__item_codigo": "100967",
                "invoice_line_ids/quantity": "3",
            }
        ]
        summary = enrich_rows_with_purchase_data(rows)
        self.assertTrue(summary["enabled"])
        self.assertTrue(summary["show_purchase_columns"])
        self.assertEqual(summary["selected_oc_by_comprobante"]["0"], 10)
        self.assertIn("CON-CHOCLO", rows[0]["__oc_match_note"])

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.fetch_partner_po_lines")
    @patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
    def test_apply_oc_selection_manual_override(self, mock_uom, mock_fetch, _mock_odoo):
        mock_uom.return_value = {"by_name": {}, "by_id": {}}
        mock_fetch.return_value = [
            {
                "line_id": 1,
                "order_id": 10,
                "order_name": "P001",
                "partner_ref": "",
                "line_name": "CON-CHOCLO",
                "product_qty": 3,
                "qty_received": 1,
                "qty_invoiced": 0,
                "product_id": 575,
                "product_uom_id": None,
                "product_uom_name": "kg",
            },
            {
                "line_id": 2,
                "order_id": 20,
                "order_name": "P002",
                "partner_ref": "",
                "line_name": "OTRO-PRODUCTO",
                "product_qty": 1,
                "qty_received": 0,
                "qty_invoiced": 0,
                "product_id": 999,
                "product_uom_id": None,
                "product_uom_name": "kg",
            },
        ]
        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "42",
                "__selected_oc_order_id": "20",
                "invoice_line_ids/name": "CHOCL0 MC CAIN X 2 KG.",
                "__item_codigo": "100967",
                "invoice_line_ids/quantity": "3",
            }
        ]
        summary = apply_oc_selection(rows, 0, 10)
        self.assertEqual(summary["selected_oc_by_comprobante"]["0"], 10)
        self.assertEqual(rows[0]["__selected_oc_order_id"], "10")
        self.assertIn("CON-CHOCLO", rows[0]["__oc_match_note"])

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.fetch_partner_po_lines")
    @patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
    def test_rematch_comprobante_after_partner_change(self, mock_uom, mock_fetch, _mock_odoo):
        mock_uom.return_value = {"by_name": {}, "by_id": {}}

        def fetch_side_effect(partner_id, **kwargs):
            if partner_id == 100:
                return [
                    {
                        "line_id": 1,
                        "order_id": 10,
                        "order_name": "P-MADRID",
                        "partner_ref": "",
                        "line_name": "CON-CHOCLO",
                        "product_qty": 3,
                        "qty_received": 3,
                        "qty_invoiced": 0,
                        "product_id": 575,
                        "product_uom_id": None,
                        "product_uom_name": "kg",
                    }
                ]
            return []

        mock_fetch.side_effect = fetch_side_effect
        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "42",
                "__selected_oc_order_id": "99",
                "invoice_line_ids/name": "CHOCL0 MC CAIN X 2 KG.",
                "__item_codigo": "100967",
                "invoice_line_ids/quantity": "3",
                "invoice_line_ids/product_id": "1",
            }
        ]
        enrich_rows_with_purchase_data(rows)
        rows[0]["partner_id"] = "100"
        summary = rematch_comprobante_purchase(rows, 0)
        self.assertEqual(summary["selected_oc_by_comprobante"].get("0"), 10)
        self.assertIn("P-MADRID", rows[0].get("__oc_name", "") + rows[0].get("__oc_match_note", ""))
        self.assertEqual(rows[0]["__selected_oc_order_id"], "10")

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.fetch_partner_po_lines")
    @patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
    def test_enrich_rows_recovers_stale_saved_oc_order_id(self, mock_uom, mock_fetch, _mock_odoo):
        mock_uom.return_value = {"by_name": {}, "by_id": {}}
        mock_fetch.return_value = [
            {
                "line_id": 501,
                "order_id": 20,
                "order_name": "P002",
                "partner_ref": "",
                "line_name": "ACEITE OLIVA",
                "product_qty": 2,
                "qty_received": 2,
                "qty_invoiced": 0,
                "product_id": 100,
                "product_uom_id": None,
                "product_uom_name": "L",
            },
            {
                "line_id": 502,
                "order_id": 20,
                "order_name": "P002",
                "partner_ref": "",
                "line_name": "AZUCAR",
                "product_qty": 10,
                "qty_received": 10,
                "qty_invoiced": 0,
                "product_id": 101,
                "product_uom_id": None,
                "product_uom_name": "kg",
            },
        ]
        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "42",
                "__selected_oc_order_id": "99",
                "invoice_line_ids/name": "ACEITE OLIVA EBENEZER X 5 LT.",
                "invoice_line_ids/quantity": "2",
            }
        ]
        summary = enrich_rows_with_purchase_data(rows)
        self.assertEqual(summary["selected_oc_by_comprobante"].get("0"), 20)
        self.assertEqual(rows[0]["__oc_line_id"], "501")

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.fetch_partner_po_lines", return_value=[])
    @patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
    def test_enrich_rows_hides_purchase_ui_without_oc(self, mock_uom, mock_fetch, _mock_odoo):
        mock_uom.return_value = {"by_name": {}, "by_id": {}}
        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "42",
                "invoice_line_ids/name": "Producto X",
                "invoice_line_ids/quantity": "2",
            }
        ]
        summary = enrich_rows_with_purchase_data(rows)
        self.assertTrue(summary["enabled"])
        self.assertFalse(summary["show_purchase_columns"])
        self.assertFalse(has_any_oc_candidates(summary["oc_candidates_by_comprobante"]))
        self.assertFalse(
            summary["oc_provider_has_ocs_by_comprobante"].get("0", False)
        )

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.fetch_partner_po_lines")
    @patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
    def test_enrich_flags_provider_has_ocs_per_comprobante(self, mock_uom, mock_fetch, _mock_odoo):
        """Flag por comprobante: True si el proveedor tiene OCs; False si no."""
        mock_uom.return_value = {"by_name": {}, "by_id": {}}

        def _fetch(partner_id, **_kwargs):
            if partner_id == 42:
                return [
                    {
                        "line_id": 1,
                        "order_id": 10,
                        "order_name": "P001",
                        "partner_ref": "",
                        "line_name": "ITEM",
                        "product_qty": 1,
                        "qty_received": 0,
                        "qty_invoiced": 0,
                        "product_id": 1,
                        "product_uom_id": None,
                        "product_uom_name": "Units",
                    }
                ]
            return []

        mock_fetch.side_effect = _fetch
        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "42",
                "invoice_line_ids/name": "ITEM",
                "invoice_line_ids/quantity": "1",
            },
            {
                "__comprobante_idx": 1,
                "partner_id": "77",
                "invoice_line_ids/name": "OTRO",
                "invoice_line_ids/quantity": "1",
            },
        ]
        summary = enrich_rows_with_purchase_data(rows, fetch_candidates=False)
        flags = summary["oc_provider_has_ocs_by_comprobante"]
        self.assertTrue(flags.get("0"))
        self.assertFalse(flags.get("1"))

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.fetch_partner_po_lines")
    @patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
    def test_enrich_without_candidates_does_not_auto_pick_oc(self, mock_uom, mock_fetch, _mock_odoo):
        mock_uom.return_value = {"by_name": {}, "by_id": {}}
        mock_fetch.return_value = [
            {
                "line_id": 1,
                "order_id": 10,
                "order_name": "P001",
                "partner_ref": "",
                "line_name": "ITEM",
                "product_qty": 1,
                "qty_received": 1,
                "qty_invoiced": 0,
                "product_id": 1,
                "product_uom_id": None,
                "product_uom_name": "Units",
            }
        ]
        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "42",
                "invoice_line_ids/name": "ITEM",
                "invoice_line_ids/quantity": "1",
            }
        ]
        summary = enrich_rows_with_purchase_data(rows, fetch_candidates=False)
        self.assertEqual(summary["oc_candidates_by_comprobante"].get("0"), [])
        self.assertNotIn("0", summary.get("selected_oc_by_comprobante", {}))
        self.assertFalse(rows[0].get("__oc_line_id"))

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.fetch_partner_po_lines")
    @patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
    def test_search_oc_candidates_for_comprobante(self, mock_uom, mock_fetch, _mock_odoo):
        mock_uom.return_value = {"by_name": {}, "by_id": {}}
        mock_fetch.return_value = [
            {
                "line_id": 1,
                "order_id": 10,
                "order_name": "P001",
                "partner_ref": "",
                "date_order": "2026-01-01",
                "receipt_status": "pending",
                "receipt_status_label": "No recepcionada",
                "deliver_to": "Depósito",
                "line_name": "ITEM",
                "product_qty": 1,
                "qty_received": 0,
                "qty_invoiced": 0,
                "product_id": 1,
                "product_uom_id": None,
                "product_uom_name": "Units",
            }
        ]
        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "42",
                "invoice_line_ids/name": "ITEM",
                "invoice_line_ids/quantity": "1",
            }
        ]
        from facturia_matching.odoo.purchase_matching import search_oc_candidates_for_comprobante

        summary = search_oc_candidates_for_comprobante(rows, 0)
        self.assertTrue(summary["oc_searched_by_comprobante"]["0"])
        self.assertEqual(len(summary["oc_candidates_by_comprobante"]["0"]), 1)
        self.assertEqual(summary["oc_candidates_by_comprobante"]["0"][0]["receipt_status_label"], "No recepcionada")

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.fetch_partner_po_lines")
    @patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
    def test_score_oc_candidates_lists_ocs_without_content_rows(self, mock_uom, mock_fetch, _mock_odoo):
        """Solo encabezado / sin líneas de producto: igual listar OCs del proveedor."""
        from facturia_matching.odoo.purchase_matching import score_oc_candidates

        po_lines = [
            {
                "line_id": 1,
                "order_id": 10,
                "order_name": "P06552",
                "partner_ref": "",
                "date_order": "2026-01-01",
                "receipt_status": "partial",
                "receipt_status_label": "Parcialmente recepcionada",
                "deliver_to": "",
                "line_name": "ITEM",
                "product_qty": 1,
                "qty_received": 0,
                "qty_invoiced": 0,
                "price_unit": 10,
                "product_uom_name": "Units",
            }
        ]
        rows = [{"__comprobante_idx": 0, "partner_id": "42", "__solo_encabezado": True}]
        cands = score_oc_candidates(rows, po_lines)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["order_name"], "P06552")
        self.assertEqual(cands[0]["basket_score"], 0.0)

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.fetch_partner_po_lines", return_value=[])
    @patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
    def test_enrich_keeps_saved_oc_when_po_fetch_empty(self, mock_uom, mock_fetch, _mock_odoo):
        """Si no hay líneas PO (fetch vacío), no borrar la OC guardada."""
        from facturia_matching.odoo.purchase_matching import enrich_rows_with_purchase_data, clear_purchase_cache

        clear_purchase_cache()
        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "42",
                "__selected_oc_order_id": "6552",
                "__selected_oc_name": "P06552",
                "invoice_line_ids/name": "ITEM",
                "invoice_line_ids/quantity": "1",
            }
        ]
        summary = enrich_rows_with_purchase_data(rows, fetch_candidates=False)
        self.assertEqual(summary["selected_oc_by_comprobante"].get("0"), 6552)
        self.assertEqual(rows[0]["__selected_oc_name"], "P06552")

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.fetch_partner_po_lines", return_value=[])
    @patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
    def test_apply_oc_selection_sin_oc_clears_match(self, mock_uom, mock_fetch, _mock_odoo):
        mock_uom.return_value = {"by_name": {}, "by_id": {}}
        mock_fetch.return_value = [
            {
                "line_id": 1,
                "order_id": 10,
                "order_name": "P001",
                "partner_ref": "",
                "date_order": "2026-01-01",
                "receipt_status": "pending",
                "receipt_status_label": "No recepcionada",
                "deliver_to": "",
                "line_name": "ITEM",
                "product_qty": 1,
                "qty_received": 0,
                "qty_invoiced": 0,
                "price_unit": 1,
                "product_id": 5,
                "product_uom_name": "Units",
            }
        ]
        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "42",
                "__selected_oc_order_id": "10",
                "__oc_line_id": "1",
                "invoice_line_ids/name": "ITEM",
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/product_id": "5",
            }
        ]
        summary = apply_oc_selection(rows, 0, 0)
        self.assertNotIn("0", summary.get("selected_oc_by_comprobante", {}))
        self.assertEqual(rows[0]["__selected_oc_order_id"], "")
        self.assertEqual(rows[0]["__oc_line_id"], "")
        # El proveedor sigue teniendo OCs: el botón/modal deben seguir disponibles.
        self.assertTrue(summary["oc_searched_by_comprobante"].get("0"))
        self.assertTrue(summary["oc_provider_has_ocs_by_comprobante"].get("0"))
        self.assertEqual(len(summary["oc_candidates_by_comprobante"].get("0") or []), 1)


if __name__ == "__main__":
    unittest.main()
