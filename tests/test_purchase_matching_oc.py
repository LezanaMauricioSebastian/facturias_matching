"""Tests for purchase OC candidates, enrich, apply, rematch, search, and restore."""
import unittest
from unittest.mock import patch

from facturia_matching.odoo.purchase_matching import (
    _attach_dinner_po_note_labels,
    _line_match_score,
    _partner_po_search_domain,
    _resolve_selected_oc,
    _saved_oc_order_id,
    _set_comprobante_oc_selection,
    apply_oc_selection,
    compute_show_purchase_columns,
    enrich_rows_with_purchase_data,
    fetch_partner_po_lines,
    has_any_oc_candidates,
    rematch_comprobante_purchase,
    row_has_odoo_purchase_data,
    score_oc_candidates,
)


class TestPurchaseMatching(unittest.TestCase):
    def test_partner_po_search_domain_includes_all_receipt_statuses(self):
        domain = _partner_po_search_domain(42)
        self.assertIn(("partner_id", "child_of", 42), domain)
        self.assertNotIn(("receipt_status", "!=", "pending"), domain)

    def test_score_oc_candidates_hides_note_rows_and_keeps_match_on_parent(self):
        rows = [
            {
                "invoice_line_ids/name": "COCA-COLA 600*12 PET 5548 ACUERDO GCIA.",
                "invoice_line_ids/quantity": "10",
                "__comprobante_idx": 0,
            }
        ]
        po_lines = [
            {
                "line_id": 1,
                "order_id": 10,
                "order_name": "P1",
                "partner_ref": "",
                "date_order": "2026-05-05",
                "line_name": "[B0003] BEB-GASEOSAS",
                "product_id": 620,
                "product_qty": 144,
                "qty_received": 144,
                "qty_invoiced": 0,
                "price_unit": 824.07,
                "product_uom_name": "Unidades",
                "note_labels": [],
                "is_note": False,
            },
            {
                "line_id": 2,
                "order_id": 10,
                "order_name": "P1",
                "partner_ref": "",
                "date_order": "2026-05-05",
                "line_name": "coca",
                "product_id": None,
                "product_qty": 0,
                "qty_received": 0,
                "qty_invoiced": 0,
                "price_unit": 0,
                "product_uom_name": "",
                "note_labels": [],
                "is_note": False,
            },
        ]
        _attach_dinner_po_note_labels(po_lines)
        cands = score_oc_candidates(rows, po_lines)
        self.assertEqual(len(cands), 1)
        detail_names = [ln["line_name"] for ln in cands[0]["lines"]]
        self.assertEqual(detail_names, ["[B0003] BEB-GASEOSAS"])
        self.assertEqual(cands[0]["lines"][0]["note_labels"], ["coca"])
        self.assertIsNotNone(cands[0]["lines"][0]["invoice_match"])

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
        # Sin tope artificial: listar todas las OCs del proveedor.
        self.assertEqual(po_call.kwargs.get("limit"), False)
        self.assertEqual(lines[0]["receipt_status_label"], "No recepcionada")
        self.assertEqual(lines[0]["deliver_to"], "Depósito Central")

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

    def test_score_oc_candidates_ranks_higher_basket_score_first(self):
        """El % del modal (basket_score) va primero: 91,7% arriba de 90% aunque la de 90% sea más nueva."""
        from facturia_matching.odoo.purchase_matching import score_oc_candidates

        invoice_rows = [
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": "SPRITE FX LS 500ML",
                "invoice_line_ids/quantity": "10",
                "invoice_line_ids/product_id": "100",
            },
        ]
        po_lines = [
            {
                "line_id": 1,
                "order_id": 10,
                "order_name": "P04539",
                "partner_ref": "pedido del 16-01",
                "date_order": "2026-01-22",
                "line_name": "OTRO PRODUCTO SIN AFINIDAD",
                "product_qty": 10,
                "qty_received": 10,
                "qty_invoiced": 0,
                "product_id": 100,
            },
            {
                "line_id": 2,
                "order_id": 20,
                "order_name": "P06931",
                "partner_ref": "PEDIDO 5/08",
                "date_order": "2026-01-05",
                "line_name": "SPRITE FX LS 500ML",
                "product_qty": 10,
                "qty_received": 10,
                "qty_invoiced": 0,
                "product_id": 100,
            },
        ]
        ranked = score_oc_candidates(invoice_rows, po_lines)
        self.assertEqual(ranked[0]["order_name"], "P06931")
        self.assertGreater(ranked[0]["basket_score"], ranked[1]["basket_score"])

    def test_score_oc_candidates_boosts_matching_partner_ref(self):
        """PDF Salta: misma canasta, gana la OC con partner_ref = PEDIDO de la factura."""
        from facturia_matching.odoo.purchase_matching import score_oc_candidates

        invoice_rows = [
            {
                "__comprobante_idx": 0,
                "__fac_referencia": "PEDIDO 26.05",
                "invoice_date": "27/05/2026",
                "invoice_line_ids/name": "SPRITE FX LS 500ML",
                "invoice_line_ids/quantity": "10",
            },
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": "COCA COLA 1.5L",
                "invoice_line_ids/quantity": "5",
            },
        ]
        # Misma canasta (2/2); refs distintas.
        po_lines = [
            {
                "line_id": 1,
                "order_id": 100,
                "order_name": "P06735",
                "partner_ref": "PEDIDO 22.07",
                "line_name": "BEB-GASEOSAS",
                "product_qty": 10,
                "qty_received": 10,
                "qty_invoiced": 0,
            },
            {
                "line_id": 2,
                "order_id": 100,
                "order_name": "P06735",
                "partner_ref": "PEDIDO 22.07",
                "line_name": "BEB-GASEOSAS",
                "product_qty": 5,
                "qty_received": 5,
                "qty_invoiced": 0,
            },
            {
                "line_id": 3,
                "order_id": 6041,
                "order_name": "P06041",
                "partner_ref": "PEDIDO 26.05",
                "line_name": "BEB-GASEOSAS",
                "product_qty": 10,
                "qty_received": 10,
                "qty_invoiced": 0,
            },
            {
                "line_id": 4,
                "order_id": 6041,
                "order_name": "P06041",
                "partner_ref": "PEDIDO 26.05",
                "line_name": "BEB-GASEOSAS",
                "product_qty": 5,
                "qty_received": 5,
                "qty_invoiced": 0,
            },
        ]
        ranked = score_oc_candidates(invoice_rows, po_lines)
        self.assertEqual(ranked[0]["order_id"], 6041)
        self.assertEqual(ranked[0]["order_name"], "P06041")
        self.assertGreaterEqual(ranked[0]["ref_score"], 85.0)
        self.assertLess(ranked[1]["ref_score"], ranked[0]["ref_score"])

    def test_score_oc_candidates_prefers_newer_date_on_tie(self):
        """Mismo lines_matched → OC con date_order más reciente primero."""
        from facturia_matching.odoo.purchase_matching import score_oc_candidates

        invoice_rows = [
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": "BEB-GASEOSAS COCA",
                "invoice_line_ids/quantity": "10",
                "__item_codigo": "",
            },
        ]
        po_lines = [
            {
                "line_id": 1,
                "order_id": 10,
                "order_name": "P04243",
                "partner_ref": "pedido 29/12",
                "date_order": "2025-12-29",
                "line_name": "BEB-GASEOSAS",
                "product_qty": 10,
                "qty_received": 0,
                "qty_invoiced": 0,
            },
            {
                "line_id": 2,
                "order_id": 20,
                "order_name": "P06273",
                "partner_ref": "Pedido 11.06",
                "date_order": "2026-06-12",
                "line_name": "BEB-GASEOSAS",
                "product_qty": 10,
                "qty_received": 0,
                "qty_invoiced": 0,
            },
        ]
        ranked = score_oc_candidates(invoice_rows, po_lines)
        self.assertEqual(ranked[0]["order_id"], 20)
        self.assertEqual(ranked[0]["order_name"], "P06273")
        self.assertEqual(ranked[0]["lines_matched"], ranked[1]["lines_matched"])

    def test_score_oc_candidates_prefers_better_qty_fit(self):
        """3 PICADAs: OC pedida=3 gana a pedida=4 aunque sea más vieja (ambos 4/4)."""
        from facturia_matching.odoo.purchase_matching import score_oc_candidates

        invoice_rows = [
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": f'PICADA "C" ESP ({i})',
                "invoice_line_ids/quantity": "14",
                "invoice_line_ids/product_id": "563",
            }
            for i in range(3)
        ] + [
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": "SALCHICHA CARCARAÑA",
                "invoice_line_ids/quantity": "6.65",
                "invoice_line_ids/product_id": "909",
            },
        ]

        def _oc(order_id, name, date, carne_qty):
            return [
                {
                    "line_id": order_id * 10,
                    "order_id": order_id,
                    "order_name": name,
                    "partner_ref": f"PEDIDO {name}",
                    "date_order": date,
                    "line_name": "CAR-CARNE MOLIDA ESPECIAL",
                    "product_qty": carne_qty,
                    "qty_received": 40.0,
                    "qty_invoiced": 40.0,
                    "product_id": 563,
                    "product_uom_name": "kg",
                    "price_unit": 12257.92,
                },
                {
                    "line_id": order_id * 10 + 1,
                    "order_id": order_id,
                    "order_name": name,
                    "partner_ref": f"PEDIDO {name}",
                    "date_order": date,
                    "line_name": "FIA-SALCHICHAS",
                    "product_qty": 1,
                    "qty_received": 6.65,
                    "qty_invoiced": 6.65,
                    "product_id": 909,
                    "product_uom_name": "kg",
                    "price_unit": 5505.01,
                },
            ]

        # Más nueva pero pedida=4; P06790 más vieja con pedida=3 exacta.
        po_lines = _oc(100, "P06800", "2026-08-04", 4) + _oc(
            790, "P06790", "2026-07-28", 3
        )
        ranked = score_oc_candidates(invoice_rows, po_lines)
        self.assertEqual(ranked[0]["lines_matched"], 4)
        self.assertEqual(ranked[1]["lines_matched"], 4)
        self.assertEqual(ranked[0]["order_name"], "P06790")
        self.assertGreater(ranked[0]["qty_fit_score"], ranked[1]["qty_fit_score"])
        self.assertAlmostEqual(ranked[0]["qty_fit_score"], 100.0, places=0)

    def test_ref_match_score_exact_and_date_proximity(self):
        from facturia_matching.odoo.purchase_matching import _ref_match_score

        self.assertEqual(
            _ref_match_score("PEDIDO 26.05", ["PEDIDO 26.05"], ["27/05/2026"]),
            100.0,
        )
        # Sin ref de factura: boost suave por DD.MM cercano a la fecha.
        soft = _ref_match_score("PEDIDO 26.05", [], ["27/05/2026"])
        self.assertGreaterEqual(soft, 50.0)
        self.assertLess(soft, 85.0)

    def test_dinner_note_zero_not_benedictino_and_agua_affinity(self):
        """PDF Salta: zero↔Coca Zero; Benedictino↔AGUA; no ACUERDO≈ZERO."""
        from facturia_matching.odoo.purchase_matching import (
            _score_dinner_note,
            score_oc_candidates,
        )

        self.assertEqual(_score_dinner_note("COCA-COLA ZERO 600*06 PET", "zero"), 100.0)
        self.assertEqual(_score_dinner_note("COCA-COLA ZERO 600*06 PET", "coca"), 70.0)
        self.assertEqual(
            _score_dinner_note("BENEDICTINO SIN GAS 600*12 PET ACUERDO GCIA.", "zero"),
            0.0,
        )

        po_lines = []
        for note, qty, lid in [
            ("coca", 12, 1),
            ("sprite", 30, 2),
            ("zero", 30, 3),
            ("fanta", 30, 4),
        ]:
            po_lines.append(
                {
                    "line_id": lid,
                    "order_id": 1,
                    "order_name": "P06041",
                    "partner_ref": "",
                    "line_name": "[B0003] BEB-GASEOSAS",
                    "note_labels": [note],
                    "product_qty": qty,
                    "qty_received": 0,
                    "qty_invoiced": 0,
                }
            )
        po_lines.append(
            {
                "line_id": 8,
                "order_id": 1,
                "order_name": "P06041",
                "partner_ref": "",
                "line_name": "[B0001] BEB-AGUA C/S GAS",
                "note_labels": [],
                "product_qty": 60,
                "qty_received": 0,
                "qty_invoiced": 0,
            }
        )
        rows = [
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": name,
                "invoice_line_ids/quantity": "5",
                "__item_codigo": "",
            }
            for name in (
                "COCA-COLA 600*12 PET",
                "SPRITE FX LS 500ML",
                "COCA-COLA ZERO 600*06 PET",
                "FANTA NARANJA 500*06 PET",
                "BENEDICTINO SIN GAS 600*12 PET",
            )
        ]
        ranked = score_oc_candidates(rows, po_lines)
        by_lid = {ln["line_id"]: ln.get("invoice_match") for ln in ranked[0]["lines"]}
        self.assertIn("ZERO", (by_lid[3] or {}).get("invoice_desc", "").upper())
        self.assertIn("BENEDICTINO", (by_lid[8] or {}).get("invoice_desc", "").upper())
        self.assertNotIn("BENEDICTINO", (by_lid[3] or {}).get("invoice_desc", "").upper())

    def test_score_oc_candidates_fanta_not_saborizada_and_gas_notes(self):
        """FANTA no pega a agua naranja; Benedictino sin gas no pega a nota con gas."""
        from facturia_matching.odoo.purchase_matching import (
            _line_match_score,
            _score_dinner_note,
            score_oc_candidates,
        )

        self.assertEqual(
            _score_dinner_note("BENEDICTINO SIN GAS 600*12 PET", "agua con gas"),
            0.0,
        )
        self.assertEqual(
            _score_dinner_note("BENEDICTINO C/G 600*12 PET", "agua con gas"),
            100.0,
        )
        self.assertEqual(
            _line_match_score(
                codigo="",
                descripcion="FANTA NARANJA 500*06 PET 5548 ACUERDO GCIA.",
                qty=30,
                po_line={
                    "line_name": "[B0002] BEB-AGUAS SABORIZADAS",
                    "note_labels": ["naranja"],
                    "product_qty": 18,
                },
            ),
            0.0,
        )

        invoice_rows = [
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": name,
                "invoice_line_ids/quantity": "10",
            }
            for name in (
                "COCA-COLA 600*12 PET 5548 ACUERDO GCIA.",
                "SPRITE FX LS 500ML NR 06PET 5548 ACUERDO GCIA.",
                "COCA-COLA ZERO 600*06 PET 5548 ACUERDO GCIA.",
                "FANTA NARANJA 500*06 PET 5548 ACUERDO GCIA.",
                "BENEDICTINO SIN GAS 600*12 PET 5548 ACUERDO GCIA.",
                "BENEDICTINO C/G 600*12 PET 5548 ACUERDO GCIA.",
            )
        ]
        po_specs = [
            (1, "[B0003] BEB-GASEOSAS", ["coca cola"], 180),
            (2, "[B0003] BEB-GASEOSAS", ["sprite"], 60),
            (3, "[B0003] BEB-GASEOSAS", ["coca zero"], 60),
            (4, "[B0001] BEB-AGUA C/S GAS", ["agua con gas"], 60),
            (5, "[B0002] BEB-AGUAS SABORIZADAS", ["pomelo"], 30),
            (6, "[B0002] BEB-AGUAS SABORIZADAS", ["naranja"], 18),
            (7, "[B0002] BEB-AGUAS SABORIZADAS", ["pomelo rosa"], 30),
            (8, "[B0003] BEB-GASEOSAS", ["fanta"], 30),
            (9, "[B0001] BEB-AGUA C/S GAS", [], 120),
        ]
        po_lines = [
            {
                "line_id": lid,
                "order_id": 1,
                "order_name": "P1",
                "partner_ref": "pedido del 09/01",
                "date_order": "2026-01-10",
                "line_name": name,
                "note_labels": notes,
                "product_qty": qty,
                "qty_received": qty,
                "qty_invoiced": qty,
                "product_uom_name": "Unidades",
                "price_unit": 1,
            }
            for lid, name, notes, qty in po_specs
        ]
        ranked = score_oc_candidates(invoice_rows, po_lines)
        by_lid = {ln["line_id"]: ln.get("invoice_match") for ln in ranked[0]["lines"]}

        def desc(lid):
            return ((by_lid.get(lid) or {}).get("invoice_desc") or "").upper()

        self.assertIn("COCA-COLA", desc(1))
        self.assertNotIn("ZERO", desc(1))
        self.assertIn("SPRITE", desc(2))
        self.assertIn("ZERO", desc(3))
        self.assertIn("C/G", desc(4))
        self.assertFalse(by_lid[5])
        self.assertFalse(by_lid[6])
        self.assertFalse(by_lid[7])
        self.assertIn("FANTA", desc(8))
        self.assertIn("SIN GAS", desc(9))
        self.assertEqual(ranked[0]["lines_matched"], 6)
        self.assertEqual(ranked[0]["lines_total"], 6)

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
        self.assertTrue(summary["oc_searched_by_comprobante"].get("0"))

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.fetch_partner_po_lines")
    @patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
    def test_enrich_restores_saved_oc_and_marks_searched(self, mock_uom, mock_fetch, _mock_odoo):
        """Carga inicial: re-aplica OC guardada y marca searched (pastilla «OC: …» tras reload)."""
        mock_uom.return_value = {"by_name": {}, "by_id": {}}
        mock_fetch.return_value = [
            {
                "line_id": 1,
                "order_id": 6552,
                "order_name": "P06552",
                "partner_ref": "",
                "line_name": "ITEM",
                "product_qty": 1,
                "qty_received": 1,
                "qty_invoiced": 0,
                "product_id": 5,
                "product_uom_id": None,
                "product_uom_name": "Units",
            }
        ]
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
        self.assertTrue(summary["oc_searched_by_comprobante"].get("0"))
        self.assertEqual(summary["oc_candidates_by_comprobante"].get("0"), [])
        self.assertEqual(rows[0]["__oc_line_id"], "1")
        self.assertTrue(summary["show_purchase_columns"])

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.fetch_partner_po_lines")
    @patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
    @patch("facturia_matching.odoo.purchase_matching._product_default_uom_id", return_value=100)
    def test_enrich_preserves_saved_manual_uom_on_reload(
        self, _mock_default_uom, mock_uom, mock_fetch, _mock_odoo
    ):
        """Reload de conversión: no pisar UM elegida a mano con el uom_po default."""
        units = {
            "id": 1,
            "name": "Unidades",
            "factor": 1.0,
            "category_id": [1, "Unidad"],
            "uom_type": "reference",
        }
        pack12 = {
            "id": 100,
            "name": "pack (12 unidades)",
            "factor": 1.0 / 12.0,
            "category_id": [1, "Unidad"],
            "uom_type": "bigger",
        }
        mock_uom.return_value = {
            "by_id": {1: units, 100: pack12},
            "by_name": {"UN": [units], "UNIDADES": [units]},
        }
        mock_fetch.return_value = [
            {
                "line_id": 1,
                "order_id": 6552,
                "order_name": "P06552",
                "partner_ref": "",
                "line_name": "COCA-COLA",
                "product_qty": 2,
                "qty_received": 0,
                "qty_invoiced": 0,
                "product_id": 620,
                "product_uom_id": 100,
                "product_uom_name": "pack (12 unidades)",
            }
        ]
        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "42",
                "__selected_oc_order_id": "6552",
                "__selected_oc_name": "P06552",
                "invoice_line_ids/name": "COCA-COLA",
                "invoice_line_ids/product_id": "620",
                # Cantidad ya re-escalada a Unidades (elección manual).
                "invoice_line_ids/quantity": "24",
                "__um_proveedor": "UN",
                "__qty_original": "24",
                "__qty_escalada": "24",
                "__um_empresa": "Unidades",
                "__um_empresa_id": "1",
                "__um_factor": "1",
                "__um_note": "Misma UM",
                "__overwrite_oc_price": "1",
            }
        ]
        summary = enrich_rows_with_purchase_data(rows, fetch_candidates=False)
        self.assertEqual(summary["selected_oc_by_comprobante"].get("0"), 6552)
        self.assertEqual(rows[0]["__um_empresa_id"], "1")
        self.assertEqual(rows[0]["__um_empresa"], "Unidades")
        self.assertEqual(float(rows[0]["invoice_line_ids/quantity"]), 24.0)
        self.assertEqual(rows[0]["__overwrite_oc_price"], "1")

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.fetch_partner_po_lines")
    @patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
    def test_enrich_restores_saved_oc_on_solo_encabezado(self, mock_uom, mock_fetch, _mock_odoo):
        """Factura solo encabezado: conserva OC guardada en summary/header tras reload."""
        mock_uom.return_value = {"by_name": {}, "by_id": {}}
        mock_fetch.return_value = [
            {
                "line_id": 9,
                "order_id": 77,
                "order_name": "P00077",
                "partner_ref": "",
                "line_name": "X",
                "product_qty": 1,
                "qty_received": 0,
                "qty_invoiced": 0,
                "product_id": 1,
                "product_uom_name": "Units",
            }
        ]
        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "42",
                "__solo_encabezado": True,
                "__selected_oc_order_id": "77",
                "__selected_oc_name": "P00077",
                "invoice_line_ids/name": "",
                "invoice_line_ids/quantity": "",
            }
        ]
        summary = enrich_rows_with_purchase_data(rows, fetch_candidates=False)
        self.assertEqual(summary["selected_oc_by_comprobante"].get("0"), 77)
        self.assertTrue(summary["oc_searched_by_comprobante"].get("0"))
        self.assertEqual(rows[0]["__selected_oc_name"], "P00077")
        self.assertEqual(summary["rows_matched"], 0)

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

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.fetch_partner_po_lines")
    @patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
    def test_apply_oc_selection_uses_product_memory(self, mock_uom, mock_fetch, _mock_odoo):
        """Al elegir OC, memoria de producto gana al fuzzy de etiqueta OC (Gran Crianza)."""
        from facturia_matching.persistence.product_label_memory import (
            MemoryChoice,
            normalize_label_key,
        )

        mock_uom.return_value = {"by_name": {}, "by_id": {}}
        mock_fetch.return_value = [
            {
                "line_id": 1,
                "order_id": 10,
                "order_name": "P06785",
                "partner_ref": "",
                "line_name": "SALCHICHA",
                "product_qty": 10,
                "qty_received": 10,
                "qty_invoiced": 0,
                "product_id": 100,
                "product_uom_id": None,
                "product_uom_name": "kg",
            },
            {
                "line_id": 2,
                "order_id": 10,
                "order_name": "P06785",
                "partner_ref": "",
                "line_name": "OTRO-PACK",
                "product_qty": 5,
                "qty_received": 5,
                "qty_invoiced": 0,
                "product_id": 200,
                "product_uom_id": None,
                "product_uom_name": "kg",
            },
        ]
        label = "BIFE ANGUS X KG"
        key = normalize_label_key(label)
        memory = {(42, key): MemoryChoice(product_id=777, uom_id=None)}
        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "42",
                "invoice_line_ids/name": label,
                "invoice_line_ids/quantity": "3",
                "__um_proveedor": "kg",
            }
        ]
        apply_oc_selection(rows, 0, 10, product_memory=memory)
        self.assertEqual(rows[0]["invoice_line_ids/product_id"], "777")

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
    def test_oc_collision_keeps_product_id(self, mock_uom, _mock_odoo):
        """Colisión 1:1 de línea OC no debe borrar product_id del match."""
        from facturia_matching.odoo.purchase_matching import _match_comprobante_rows

        mock_uom.return_value = {"by_name": {}, "by_id": {}}
        po_lines = [
            {
                "line_id": 1,
                "order_id": 10,
                "order_name": "P001",
                "partner_ref": "",
                "line_name": "COCA ZERO",
                "product_qty": 10,
                "qty_received": 10,
                "qty_invoiced": 0,
                "product_id": 50,
                "product_uom_name": "Units",
                "note_labels": ["zero"],
            },
        ]
        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "42",
                "__selected_oc_order_id": "10",
                "invoice_line_ids/name": "COCA COLA ZERO",
                "invoice_line_ids/quantity": "5",
            },
            {
                "__comprobante_idx": 0,
                "partner_id": "42",
                "__selected_oc_order_id": "10",
                "invoice_line_ids/name": "COCA COLA ZERO PACK",
                "invoice_line_ids/quantity": "5",
            },
        ]
        matched = _match_comprobante_rows(rows, po_lines, mock_uom.return_value, 10)
        self.assertEqual(matched, 1)
        self.assertEqual(rows[0]["invoice_line_ids/product_id"], "50")
        # Segunda fila: misma línea OC reclamada → sin vínculo, pero conserva producto.
        self.assertEqual(rows[1]["invoice_line_ids/product_id"], "50")
        self.assertIn("ya asignada", (rows[1].get("__oc_match_note") or "").lower())
        self.assertFalse(str(rows[1].get("__oc_line_id") or "").isdigit())

    @patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
    @patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
    def test_same_product_oc_lines_distributed_one_each(self, mock_uom, _mock_odoo):
        """Gran Crianza: 3× CAR-CARNE MOLIDA en OC → 3 filas PICADA con product 563."""
        from facturia_matching.odoo.purchase_matching import _match_comprobante_rows

        mock_uom.return_value = {"by_name": {}, "by_id": {}}
        po_lines = [
            {
                "line_id": 10 + i,
                "order_id": 85,
                "order_name": "P06785",
                "partner_ref": "",
                "line_name": "CAR-CARNE MOLIDA ESPECIAL",
                "product_qty": 1,
                "qty_received": 14.0 + i,
                "qty_invoiced": 0,
                "product_id": 563,
                "product_uom_name": "kg",
                "price_unit": 10000 + i,
            }
            for i in range(3)
        ]
        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "42",
                "__selected_oc_order_id": "85",
                "invoice_line_ids/name": f"PICADA {i}",
                "invoice_line_ids/quantity": "15",
                "invoice_line_ids/product_id": "563",
                "__um_proveedor": "kg",
            }
            for i in range(3)
        ]
        matched = _match_comprobante_rows(rows, po_lines, mock_uom.return_value, 85)
        self.assertEqual(matched, 3)
        linked = {str(r.get("__oc_line_id")) for r in rows}
        self.assertEqual(linked, {"10", "11", "12"})
        for r in rows:
            self.assertEqual(r["invoice_line_ids/product_id"], "563")
            self.assertNotIn("ya asignada", (r.get("__oc_match_note") or "").lower())

    def test_score_oc_candidates_matches_by_product_id(self):
        """Preview: PICADA con product_id=563 matchea CAR-CARNE aunque el texto no."""
        from facturia_matching.odoo.purchase_matching import score_oc_candidates

        invoice_rows = [
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": "PICADA \\",
                "invoice_line_ids/quantity": "14",
                "invoice_line_ids/product_id": "563",
            },
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": "PICADA \\",
                "invoice_line_ids/quantity": "15",
                "invoice_line_ids/product_id": "563",
            },
        ]
        po_lines = [
            {
                "line_id": 1,
                "order_id": 85,
                "order_name": "P06785",
                "partner_ref": "",
                "date_order": "2026-08-03",
                "line_name": "CAR-CARNE MOLIDA ESPECIAL",
                "product_qty": 1,
                "qty_received": 14.64,
                "qty_invoiced": 0,
                "product_id": 563,
                "product_uom_name": "kg",
                "price_unit": 10390,
            },
            {
                "line_id": 2,
                "order_id": 85,
                "order_name": "P06785",
                "partner_ref": "",
                "date_order": "2026-08-03",
                "line_name": "CAR-CARNE MOLIDA ESPECIAL",
                "product_qty": 1,
                "qty_received": 15.2,
                "qty_invoiced": 0,
                "product_id": 563,
                "product_uom_name": "kg",
                "price_unit": 12257,
            },
        ]
        ranked = score_oc_candidates(invoice_rows, po_lines)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["lines_matched"], 2)
        matched_details = [
            d for d in ranked[0]["lines"] if d.get("invoice_match")
        ]
        self.assertEqual(len(matched_details), 2)

    def test_score_oc_candidates_soft_counts_same_product_up_to_qty(self):
        """1× CAR-CARNE product_qty=3 + 3 PICADA mismo product_id → 3/3 en ranking."""
        from facturia_matching.odoo.purchase_matching import score_oc_candidates

        invoice_rows = [
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": f'PICADA "C" ESP ({i})',
                "invoice_line_ids/quantity": str(14 + i),
                "invoice_line_ids/product_id": "563",
            }
            for i in range(3)
        ]
        po_lines = [
            {
                "line_id": 1,
                "order_id": 790,
                "order_name": "P06790",
                "partner_ref": "PEDIDO 27.07",
                "date_order": "2026-07-28",
                "line_name": "CAR-CARNE MOLIDA ESPECIAL",
                "product_qty": 3,
                "qty_received": 44.06,
                "qty_invoiced": 44.06,
                "product_id": 563,
                "product_uom_name": "kg",
                "price_unit": 12257.92,
            },
        ]
        ranked = score_oc_candidates(invoice_rows, po_lines)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["lines_matched"], 3)
        self.assertEqual(ranked[0]["lines_total"], 3)
        self.assertAlmostEqual(ranked[0]["basket_score"], 90.0, places=0)
        # UI sigue mostrando un solo invoice_match primario.
        matched_details = [
            d for d in ranked[0]["lines"] if d.get("invoice_match")
        ]
        self.assertEqual(len(matched_details), 1)

    def test_score_oc_candidates_soft_p06790_style_four_of_four(self):
        """P06790: 3× PICADA + 1× SALCHICHA vs CARNE qty=3 + SALCHICHAS qty=1 → 4/4."""
        from facturia_matching.odoo.purchase_matching import score_oc_candidates

        invoice_rows = [
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": f'PICADA "C" ESP ({i})',
                "invoice_line_ids/quantity": "14",
                "invoice_line_ids/product_id": "563",
            }
            for i in range(3)
        ] + [
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": "SALCHICHA CARCARAÑA 35X6 190GS (909)",
                "invoice_line_ids/quantity": "6.65",
                "invoice_line_ids/product_id": "909",
            },
        ]
        po_lines = [
            {
                "line_id": 10,
                "order_id": 790,
                "order_name": "P06790",
                "partner_ref": "PEDIDO 27.07",
                "date_order": "2026-07-28",
                "line_name": "CAR-CARNE MOLIDA ESPECIAL",
                "product_qty": 3,
                "qty_received": 44.06,
                "qty_invoiced": 44.06,
                "product_id": 563,
                "product_uom_name": "kg",
                "price_unit": 12257.92,
            },
            {
                "line_id": 11,
                "order_id": 790,
                "order_name": "P06790",
                "partner_ref": "PEDIDO 27.07",
                "date_order": "2026-07-28",
                "line_name": "FIA-SALCHICHAS",
                "product_qty": 1,
                "qty_received": 6.65,
                "qty_invoiced": 6.65,
                "product_id": 909,
                "product_uom_name": "kg",
                "price_unit": 5505.01,
            },
        ]
        ranked = score_oc_candidates(invoice_rows, po_lines)
        self.assertEqual(ranked[0]["lines_matched"], 4)
        self.assertEqual(ranked[0]["lines_total"], 4)
        self.assertAlmostEqual(ranked[0]["basket_score"], 90.0, places=0)

    def test_score_oc_candidates_soft_respects_product_qty_capacity(self):
        """product_qty=1: solo 1 de 3 PICADA cuenta en el ranking."""
        from facturia_matching.odoo.purchase_matching import score_oc_candidates

        invoice_rows = [
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": f"PICADA {i}",
                "invoice_line_ids/quantity": "10",
                "invoice_line_ids/product_id": "563",
            }
            for i in range(3)
        ]
        po_lines = [
            {
                "line_id": 1,
                "order_id": 1,
                "order_name": "P1",
                "partner_ref": "",
                "date_order": "2026-07-28",
                "line_name": "CAR-CARNE MOLIDA ESPECIAL",
                "product_qty": 1,
                "qty_received": 30.0,
                "qty_invoiced": 0,
                "product_id": 563,
                "product_uom_name": "kg",
                "price_unit": 1000,
            },
        ]
        ranked = score_oc_candidates(invoice_rows, po_lines)
        self.assertEqual(ranked[0]["lines_matched"], 1)
        self.assertEqual(ranked[0]["lines_total"], 3)
        self.assertAlmostEqual(ranked[0]["basket_score"], 30.0, places=0)

    def test_score_oc_candidates_soft_skips_zero_and_gas_variants(self):
        """Coca/Sprite/Fanta/Benedictino s/gas = 4/6; Zero y C/G no inflan el basket."""
        from facturia_matching.odoo.purchase_matching import score_oc_candidates

        invoice_rows = [
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": name,
                "invoice_line_ids/quantity": "10",
                "invoice_line_ids/product_id": pid,
            }
            for name, pid in (
                ("COCA-COLA 600*12 PET 5548 ACUERDO GCIA.", "620"),
                ("SPRITE FX LS 500ML NR 06PET 5548 ACUERDO GCIA.", "620"),
                ("COCA-COLA ZERO 600*06 PET 5548 ACUERDO GCIA.", "620"),
                ("FANTA NARANJA 500*06 PET 5548 ACUERDO GCIA.", "620"),
                ("BENEDICTINO SIN GAS 600*12 PET 5548 ACUERDO GCIA.", "510"),
                ("BENEDICTINO C/G 600*12 PET 5548 ACUERDO GCIA.", "510"),
            )
        ]
        po_specs = [
            (1, "[B0003] BEB-GASEOSAS", ["cocacola"], 120, 620),
            (2, "[B0003] BEB-GASEOSAS", ["sprite"], 60, 620),
            (3, "[B0002] BEB-AGUAS SABORIZADAS", ["pera"], 84, 621),
            (4, "[B0001] BEB-AGUA C/S GAS", ["agua sin gas"], 48, 510),
            (5, "[B0002] BEB-AGUAS SABORIZADAS", ["manzana"], 30, 621),
            (6, "[B0003] BEB-GASEOSAS", ["fanta"], 60, 620),
            (7, "[B0002] BEB-AGUAS SABORIZADAS", ["naranja"], 30, 621),
        ]
        po_lines = [
            {
                "line_id": lid,
                "order_id": 1,
                "order_name": "P1",
                "partner_ref": "pedido del 09/01",
                "date_order": "2026-01-10",
                "line_name": name,
                "note_labels": notes,
                "product_qty": qty,
                "qty_received": qty,
                "qty_invoiced": qty,
                "product_id": pid,
                "product_uom_name": "Unidades",
                "price_unit": 1,
            }
            for lid, name, notes, qty, pid in po_specs
        ]
        ranked = score_oc_candidates(invoice_rows, po_lines)
        self.assertEqual(ranked[0]["lines_total"], 6)
        self.assertEqual(ranked[0]["lines_matched"], 4)
        self.assertLess(ranked[0]["basket_score"], 80.0)
        primary = [
            (d["line_id"], (d.get("invoice_match") or {}).get("invoice_desc", ""))
            for d in ranked[0]["lines"]
            if d.get("invoice_match")
        ]
        self.assertEqual(len(primary), 4)
        blob = " ".join(desc.upper() for _, desc in primary)
        self.assertIn("COCA-COLA", blob)
        self.assertNotIn("ZERO", blob)
        self.assertIn("SPRITE", blob)
        self.assertIn("FANTA", blob)
        self.assertIn("BENEDICTINO", blob)
        self.assertNotIn("C/G", blob)

    def test_score_oc_candidates_soft_skips_pack_count_mismatch(self):
        """Soft recount: SPRITE pack 6 hard-match no arrastra pack 8 (mismo product_id)."""
        from facturia_matching.odoo.purchase_matching import score_oc_candidates

        invoice_rows = [
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": name,
                "invoice_line_ids/quantity": "10",
                "invoice_line_ids/product_id": "620",
            }
            for name in (
                "SPRITE FX LS 500ML NR 06PET 5548 ACUERDO GCIA.",
                "SPRITE FX LS 500ML NR 08PET 5548 ACUERDO GCIA.",
            )
        ]
        po_lines = [
            {
                "line_id": 1,
                "order_id": 1,
                "order_name": "P1",
                "partner_ref": "",
                "date_order": "2026-01-10",
                "line_name": "[B0003] BEB-GASEOSAS",
                "note_labels": ["sprite"],
                "product_qty": 2,
                "qty_received": 2,
                "qty_invoiced": 0,
                "product_id": 620,
                "product_uom_name": "Unidades",
                "price_unit": 1,
            }
        ]
        ranked = score_oc_candidates(invoice_rows, po_lines)
        self.assertEqual(ranked[0]["lines_total"], 2)
        self.assertEqual(ranked[0]["lines_matched"], 1)

    def test_score_oc_candidates_soft_sibling_label_without_product_id(self):
        """Sin product_id en extras: etiqueta hermana ≥88 hereda el hard-match."""
        from facturia_matching.odoo.purchase_matching import score_oc_candidates

        invoice_rows = [
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": 'PICADA "C" ESP',
                "invoice_line_ids/quantity": "14",
                "invoice_line_ids/product_id": "563",
            },
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": 'PICADA "C" ESP (6214)',
                "invoice_line_ids/quantity": "15",
            },
            {
                "__comprobante_idx": 0,
                "invoice_line_ids/name": 'PICADA "C" ESP 6215',
                "invoice_line_ids/quantity": "15",
            },
        ]
        po_lines = [
            {
                "line_id": 1,
                "order_id": 790,
                "order_name": "P06790",
                "partner_ref": "",
                "date_order": "2026-07-28",
                "line_name": "CAR-CARNE MOLIDA ESPECIAL",
                "product_qty": 3,
                "qty_received": 44.06,
                "qty_invoiced": 0,
                "product_id": 563,
                "product_uom_name": "kg",
                "price_unit": 12000,
            },
        ]
        ranked = score_oc_candidates(invoice_rows, po_lines)
        self.assertEqual(ranked[0]["lines_matched"], 3)
        self.assertAlmostEqual(ranked[0]["basket_score"], 90.0, places=0)
