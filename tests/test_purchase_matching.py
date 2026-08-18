"""Tests for purchase order matching and UOM scaling."""
import unittest
from unittest.mock import patch

from facturia_matching.odoo.purchase_matching import (
    _attach_dinner_po_note_labels,
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

    def test_attach_dinner_po_note_labels_folds_zero_qty_under_bracket_parent(self):
        """Dinner: qty 0 bajo '[B0003] BEB-GASEOSAS' → nota/etiqueta del padre."""
        lines = [
            {
                "line_id": 1,
                "order_id": 10,
                "line_name": "[B0003] BEB-GASEOSAS",
                "product_id": 620,
                "product_qty": 144,
                "qty_received": 144,
            },
            {
                "line_id": 2,
                "order_id": 10,
                "line_name": "coca",
                "product_id": None,
                "product_qty": 0,
                "qty_received": 0,
            },
            {
                "line_id": 3,
                "order_id": 10,
                "line_name": "[B0003] BEB-GASEOSAS",
                "product_id": 620,
                "product_qty": 96,
                "qty_received": 96,
            },
            {
                "line_id": 4,
                "order_id": 10,
                "line_name": "sprite",
                "product_id": None,
                "product_qty": 0,
                "qty_received": 0,
            },
        ]
        _attach_dinner_po_note_labels(lines)
        self.assertFalse(lines[0]["is_note"])
        self.assertEqual(lines[0]["note_labels"], ["coca"])
        self.assertTrue(lines[1]["is_note"])
        self.assertEqual(lines[1]["parent_line_id"], 1)
        self.assertEqual(lines[2]["note_labels"], ["sprite"])
        self.assertTrue(lines[3]["is_note"])

    def test_line_match_score_uses_dinner_note_label(self):
        """COCA-COLA… matchea la línea padre vía nota 'coca', no la nota sola."""
        parent = {
            "line_name": "[B0003] BEB-GASEOSAS",
            "product_qty": 144,
            "note_labels": ["coca"],
            "is_note": False,
        }
        note = {
            "line_name": "coca",
            "product_qty": 0,
            "is_note": True,
            "note_labels": [],
        }
        sc_parent = _line_match_score(
            codigo="",
            descripcion="COCA-COLA 600*12 PET 5548 ACUERDO GCIA.",
            qty=10,
            po_line=parent,
        )
        sc_note = _line_match_score(
            codigo="",
            descripcion="COCA-COLA 600*12 PET 5548 ACUERDO GCIA.",
            qty=10,
            po_line=note,
        )
        self.assertGreaterEqual(sc_parent, 75)
        self.assertEqual(sc_note, 0.0)

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

    def test_line_match_score_rejects_tomate_seco_vs_triturado(self):
        """PDF Mauri: TOMATE SECO no debe pasar umbral solo por token TOMATE."""
        po = {"line_name": "ALM-TOMATE TRITURADO", "product_qty": 5}
        sc = _line_match_score(
            codigo="",
            descripcion="TOMATE SECO X KG.",
            qty=5,
            po_line=po,
        )
        self.assertLess(sc, 75.0)

    def test_match_invoice_row_no_suggest_tomate_seco_as_triturado(self):
        row = {
            "invoice_line_ids/name": "TOMATE SECO X KG.",
            "__item_codigo": "",
            "invoice_line_ids/quantity": "5",
            "__um_proveedor": "KG",
        }
        pool = [
            {
                "line_name": "ALM-TOMATE TRITURADO",
                "product_qty": 5,
                "product_id": 818,
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

    def test_resolve_invoice_qty_ignores_package_um_when_qty_present(self):
        """«X 500 G» en descripción no debe volverse UM si ya hay cantidad de línea."""
        row = {
            "invoice_line_ids/quantity": "20",
            "__fac_item_cantidad": "20",
            "__um_proveedor": "",
        }
        qty, um = _resolve_invoice_qty_um(
            row,
            "SAL FINA CELUSAL X 500 G",
            repair_row=True,
        )
        self.assertEqual(qty, 20.0)
        self.assertEqual(um, "")

    def test_suggest_product_does_not_rescale_pack_qty_as_kg(self):
        """PDF Mauri Sal fina: sugerencia fuzzy no debe convertir 20 → 0.32."""
        catalog = {
            "by_id": {
                12: {"id": 12, "name": "kg", "factor": 1.0, "category_id": [2, "Peso"]},
                99: {
                    "id": 99,
                    "name": "unidad de (62.5 kg)",
                    "factor": 0.016,
                    "category_id": [2, "Peso"],
                },
            },
            "by_name": {
                "KG": {"id": 12, "name": "kg", "factor": 1.0, "category_id": [2, "Peso"]},
            },
        }
        row = {
            "invoice_line_ids/name": "SAL FINA CELUSAL X 500 G",
            "__item_codigo": "",
            "invoice_line_ids/quantity": "20",
            "__fac_item_cantidad": "20",
            "__um_proveedor": "KG",
        }
        pool = [
            {
                "line_name": "ALM-SAL FINA",
                "product_qty": 20,
                "product_id": 1037,
                "order_name": "P1",
                "order_id": 1,
                "line_id": 1,
                "partner_ref": "",
                "qty_received": 0,
                "qty_invoiced": 0,
                "product_uom_id": 99,
                "product_uom_name": "unidad de (62.5 kg)",
            }
        ]
        with patch(
            "facturia_matching.odoo.purchase_matching._product_default_uom_id",
            return_value=99,
        ):
            out = match_invoice_row(row, [], catalog, suggest_pool=pool)
        self.assertEqual(row.get("invoice_line_ids/product_id"), "1037")
        self.assertTrue(out.get("__product_suggested"))
        self.assertEqual(row["invoice_line_ids/quantity"], "20")
        self.assertNotEqual(out.get("__um_note"), "Re-escalado")

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

    def _dinner_like_uom_catalog(self):
        """Catálogo estilo Dinner: kg/L duplicados en categorías custom + UOMs de envase."""
        weight = [2, "Peso"]
        crema = [10, "Conversión Crema de Leche"]
        volume = [6, "Volumen"]
        litros = [9, "LITROS"]
        kg_peso = {
            "id": 12,
            "name": "kg",
            "factor": 1.0,
            "category_id": weight,
            "uom_type": "reference",
        }
        kg_crema = {
            "id": 73,
            "name": "kg",
            "factor": 1.0,
            "category_id": crema,
            "uom_type": "reference",
        }
        g = {
            "id": 13,
            "name": "g",
            "factor": 1000.0,
            "category_id": weight,
            "uom_type": "smaller",
        }
        pack_2840 = {
            "id": 90,
            "name": "unidad de (2840g)",
            "factor": 0.35211267605633806,
            "category_id": weight,
            "uom_type": "bigger",
        }
        l_vol = {
            "id": 10,
            "name": "L",
            "factor": 1.0,
            "category_id": volume,
            "uom_type": "reference",
        }
        l_litros = {
            "id": 62,
            "name": "L",
            "factor": 1.0,
            "category_id": litros,
            "uom_type": "reference",
        }
        pack_5lt = {
            "id": 85,
            "name": "unidad de (5LT)",
            "factor": 0.2,
            "category_id": volume,
            "uom_type": "bigger",
        }
        return {
            "by_id": {
                12: kg_peso,
                73: kg_crema,
                13: g,
                90: pack_2840,
                10: l_vol,
                62: l_litros,
                85: pack_5lt,
            },
            # Lista = colisión; el último solo (legado) era kg_crema / L LITROS y rompía Peso/Volumen.
            "by_name": {
                "KG": [kg_crema, kg_peso],
                "G": [g],
                "L": [l_litros, l_vol],
                "LT": [l_litros, l_vol],
                "UNIDAD DE (2840G)": [pack_2840],
                "UNIDAD DE (5LT)": [pack_5lt],
            },
        }

    def test_apply_uom_scaling_kg_collision_uses_target_category(self):
        """FacturIA manda KG; by_name global apunta al kg de otra categoría → debe usar Peso."""
        from facturia_matching.odoo.purchase_matching import _apply_uom_scaling

        catalog = self._dinner_like_uom_catalog()
        out = _apply_uom_scaling(
            {},
            invoice_qty=6.0,
            invoice_um_raw="KG",
            po_uom_id=12,
            po_uom_name="kg",
            uom_catalog=catalog,
        )
        self.assertEqual(out["um_empresa_id"], "12")
        self.assertEqual(out["um_factor"], "1")
        self.assertNotEqual(out["um_note"], "Categoría UM distinta")

    def test_apply_uom_scaling_oc_custom_pack_from_kg_invoice(self):
        """OC en unidad de (2840g); factura KG debe re-escalar a packs (misma categoría Peso)."""
        from facturia_matching.odoo.purchase_matching import _apply_uom_scaling

        catalog = self._dinner_like_uom_catalog()
        out = _apply_uom_scaling(
            {},
            invoice_qty=6.0,
            invoice_um_raw="KG",
            po_uom_id=90,
            po_uom_name="unidad de (2840g)",
            uom_catalog=catalog,
        )
        self.assertEqual(out["um_empresa_id"], "90")
        self.assertEqual(out["um_note"], "Re-escalado")
        # 6 kg * (0.352... / 1) ≈ 2.11 packs de 2840g
        self.assertAlmostEqual(float(out["qty_escalada"]), 6.0 * 0.35211267605633806, places=5)

    def test_apply_uom_scaling_oc_custom_pack_from_g_invoice(self):
        from facturia_matching.odoo.purchase_matching import _apply_uom_scaling

        catalog = self._dinner_like_uom_catalog()
        out = _apply_uom_scaling(
            {},
            invoice_qty=2840.0,
            invoice_um_raw="g",
            po_uom_id=90,
            po_uom_name="unidad de (2840g)",
            uom_catalog=catalog,
        )
        self.assertEqual(out["um_empresa_id"], "90")
        self.assertEqual(out["um_note"], "Re-escalado")
        self.assertEqual(out["qty_escalada"], "1")

    def test_apply_uom_scaling_lt_collision_uses_volume_category(self):
        from facturia_matching.odoo.purchase_matching import _apply_uom_scaling

        catalog = self._dinner_like_uom_catalog()
        out = _apply_uom_scaling(
            {},
            invoice_qty=6.0,
            invoice_um_raw="LT",
            po_uom_id=85,
            po_uom_name="unidad de (5LT)",
            uom_catalog=catalog,
        )
        self.assertEqual(out["um_empresa_id"], "85")
        self.assertEqual(out["um_note"], "Re-escalado")
        self.assertEqual(out["qty_escalada"], "1.2")

    def test_find_uom_in_category_prefers_weight_kg(self):
        from facturia_matching.odoo.purchase_matching import _find_uom_in_category

        catalog = self._dinner_like_uom_catalog()
        found = _find_uom_in_category("KG", 2, catalog)
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], 12)
        crema = _find_uom_in_category("KG", 10, catalog)
        self.assertIsNotNone(crema)
        self.assertEqual(crema["id"], 73)

    def test_match_invoice_row_oc_uses_product_purchase_uom_not_po_line(self):
        """Tras detectar producto, UM inferida = uom_po_id del producto (pack), no UM de la línea OC."""
        from unittest.mock import patch

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
        catalog = {
            "by_id": {1: units, 100: pack12},
            "by_name": {
                "UN": [units],
                "UNIDADES": [units],
                "PACK (12 UNIDADES)": [pack12],
            },
        }
        row = {
            "invoice_line_ids/name": "BEB-GASEOSAS",
            "__item_codigo": "B0003",
            "invoice_line_ids/quantity": "24",
            "__fac_item_cantidad": "24",
            "__um_proveedor": "UN",
        }
        po_lines = [
            {
                "line_name": "[B0003] BEB-GASEOSAS",
                "product_qty": 240,
                "product_id": 620,
                "order_name": "P06505",
                "order_id": 6505,
                "line_id": 99,
                "partner_ref": "",
                "qty_received": 240,
                "qty_invoiced": 0,
                "product_uom_id": 1,  # OC en Unidades…
                "product_uom_name": "Unidades",
            }
        ]
        with patch(
            "facturia_matching.odoo.purchase_matching._product_default_uom_id",
            return_value=100,  # …pero producto compra en pack 12
        ):
            out = match_invoice_row(row, po_lines, catalog)
        self.assertEqual(out["__oc_line_id"], "99")
        self.assertEqual(out["__um_empresa"], "pack (12 unidades)")
        self.assertEqual(out["__um_empresa_id"], "100")
        self.assertEqual(out["__um_note"], "Re-escalado")
        self.assertEqual(out["__qty_escalada"], "2")
        self.assertEqual(row["invoice_line_ids/product_id"], "620")

    def test_match_invoice_row_keeps_confirmed_product_and_saved_uom(self):
        """Producto+UM ya en fila: no pisa con etiqueta OC de otro producto; no re-escala qty."""
        from unittest.mock import patch

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
        catalog = {
            "by_id": {1: units, 100: pack12},
            "by_name": {
                "UN": [units],
                "UNIDADES": [units],
                "PACK (12 UNIDADES)": [pack12],
            },
        }
        row = {
            "invoice_line_ids/name": "SPRITE FX LS 500*12 PET",
            "__item_codigo": "B0099",
            "invoice_line_ids/quantity": "5",
            "invoice_line_ids/product_id": "620",
            "__um_empresa": "pack (12 unidades)",
            "__um_empresa_id": "100",
            "__um_proveedor": "UN",
        }
        po_lines = [
            {
                "line_name": "[OTHER] OTRO PRODUCTO",
                "product_qty": 10,
                "product_id": 999,
                "order_name": "P06041",
                "order_id": 6041,
                "line_id": 11,
                "partner_ref": "",
                "qty_received": 10,
                "qty_invoiced": 0,
                "product_uom_id": 1,
                "product_uom_name": "Unidades",
            },
            {
                "line_name": "[B0003] BEB-GASEOSAS",
                "product_qty": 50,
                "product_id": 620,
                "order_name": "P06041",
                "order_id": 6041,
                "line_id": 22,
                "partner_ref": "",
                "qty_received": 50,
                "qty_invoiced": 0,
                "product_uom_id": 100,
                "product_uom_name": "pack (12 unidades)",
            },
        ]
        with patch(
            "facturia_matching.odoo.purchase_matching._product_default_uom_id",
            return_value=100,
        ):
            out = match_invoice_row(row, po_lines, catalog)
        self.assertEqual(row["invoice_line_ids/product_id"], "620")
        self.assertEqual(row["invoice_line_ids/quantity"], "5")
        self.assertEqual(out["__um_empresa_id"], "100")
        self.assertIn(out["__qty_escalada"], ("5", "5.0"))
        self.assertEqual(out["__oc_line_id"], "22")
        self.assertNotIn("Re-escalado", out.get("__um_note") or "")

    def test_apply_product_uom_to_row_sets_pack_from_product(self):
        from unittest.mock import patch
        from facturia_matching.odoo.purchase_matching import apply_product_uom_to_row

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
        catalog = {
            "by_id": {1: units, 100: pack12},
            "by_name": {"UN": [units], "UNIDADES": [units]},
        }
        row = {
            "invoice_line_ids/name": "COCA-COLA 600*12 PET",
            "invoice_line_ids/product_id": "620",
            "invoice_line_ids/quantity": "24",
            "__fac_item_cantidad": "24",
            "__um_proveedor": "UN",
            "__product_suggested": "80",
        }
        with patch(
            "facturia_matching.odoo.purchase_matching._product_default_uom_id",
            return_value=100,
        ), patch(
            "facturia_matching.odoo.purchase_matching.get_uom_catalog",
            return_value=catalog,
        ):
            info = apply_product_uom_to_row(row)
        self.assertEqual(row["__um_empresa"], "pack (12 unidades)")
        self.assertEqual(row["__um_empresa_id"], "100")
        self.assertEqual(row["__um_note"], "Re-escalado")
        self.assertEqual(row["__qty_escalada"], "2")
        self.assertEqual(row["invoice_line_ids/quantity"], "2")
        self.assertEqual(row["__product_suggested"], "")
        self.assertEqual(info["um_empresa_id"], "100")

    def test_apply_product_uom_to_row_clears_without_product(self):
        from facturia_matching.odoo.purchase_matching import apply_product_uom_to_row

        row = {
            "invoice_line_ids/product_id": "",
            "__um_empresa": "pack (12 unidades)",
            "__um_empresa_id": "100",
            "__um_factor": "0.5",
            "__um_note": "Re-escalado",
        }
        apply_product_uom_to_row(row, None)
        self.assertEqual(row["__um_empresa"], "")
        self.assertEqual(row["__um_empresa_id"], "")

    def test_list_uoms_for_product_same_category(self):
        from unittest.mock import patch
        from facturia_matching.odoo.purchase_matching import list_uoms_for_product

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
        kg = {
            "id": 12,
            "name": "kg",
            "factor": 1.0,
            "category_id": [2, "Weight"],
            "uom_type": "reference",
        }
        catalog = {
            "by_id": {1: units, 100: pack12, 12: kg},
            "by_name": {},
        }
        with patch(
            "facturia_matching.odoo.purchase_matching._product_default_uom_id",
            return_value=100,
        ), patch(
            "facturia_matching.odoo.purchase_matching.get_uom_catalog",
            return_value=catalog,
        ):
            uoms = list_uoms_for_product(620)
        ids = {u["id"] for u in uoms}
        self.assertEqual(ids, {1, 100})
        self.assertTrue(all("name" in u for u in uoms))

    def test_apply_product_uom_to_row_explicit_uom_id_rescales(self):
        from unittest.mock import patch
        from facturia_matching.odoo.purchase_matching import apply_product_uom_to_row

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
        catalog = {
            "by_id": {1: units, 100: pack12},
            "by_name": {"UN": [units], "UNIDADES": [units]},
        }
        row = {
            "invoice_line_ids/name": "COCA-COLA 600*12 PET",
            "invoice_line_ids/product_id": "620",
            "invoice_line_ids/quantity": "2",  # ya re-escalada a packs
            "__fac_item_cantidad": "24",
            "__um_proveedor": "UN",
            "__qty_original": "24",
            "__um_empresa": "pack (12 unidades)",
            "__um_empresa_id": "100",
        }
        with patch(
            "facturia_matching.odoo.purchase_matching._product_default_uom_id",
            return_value=100,
        ), patch(
            "facturia_matching.odoo.purchase_matching.get_uom_catalog",
            return_value=catalog,
        ):
            info = apply_product_uom_to_row(row, 620, uom_id=1)
        self.assertEqual(row["__um_empresa"], "Unidades")
        self.assertEqual(row["__um_empresa_id"], "1")
        self.assertEqual(float(row["invoice_line_ids/quantity"]), 24.0)
        self.assertEqual(float(row["__qty_escalada"]), 24.0)
        self.assertEqual(info["um_empresa_id"], "1")

    def test_apply_product_uom_to_row_rejects_out_of_category_uom(self):
        from unittest.mock import patch
        from facturia_matching.odoo.purchase_matching import apply_product_uom_to_row

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
        kg = {
            "id": 12,
            "name": "kg",
            "factor": 1.0,
            "category_id": [2, "Weight"],
            "uom_type": "reference",
        }
        catalog = {
            "by_id": {1: units, 100: pack12, 12: kg},
            "by_name": {"UN": [units], "UNIDADES": [units]},
        }
        row = {
            "invoice_line_ids/name": "COCA-COLA",
            "invoice_line_ids/product_id": "620",
            "invoice_line_ids/quantity": "24",
            "__fac_item_cantidad": "24",
            "__um_proveedor": "UN",
            "__qty_original": "24",
        }
        with patch(
            "facturia_matching.odoo.purchase_matching._product_default_uom_id",
            return_value=100,
        ), patch(
            "facturia_matching.odoo.purchase_matching.get_uom_catalog",
            return_value=catalog,
        ):
            apply_product_uom_to_row(row, 620, uom_id=12)
        # kg fuera de categoría → cae al default pack
        self.assertEqual(row["__um_empresa"], "pack (12 unidades)")
        self.assertEqual(row["__um_empresa_id"], "100")

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
        # Sin conservar UM, el rematch pondría uom_po (pack 100) y re-escalaría qty.

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
        # Tras enrich rematch el producto queda confirmado (sin flag suggested).

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

    def test_resolve_target_uom_prefers_invoice_kg(self):
        """FacturIA KG + producto con pack de peso → preferir kg (Gran Crianza)."""
        from facturia_matching.odoo.purchase_matching import _resolve_target_uom_for_product

        catalog = self._dinner_like_uom_catalog()
        with patch(
            "facturia_matching.odoo.purchase_matching._product_default_uom_id",
            return_value=90,  # unidad de (2840g)
        ):
            to_uom = _resolve_target_uom_for_product(
                555, catalog, invoice_um_raw="KG"
            )
        self.assertIsNotNone(to_uom)
        self.assertEqual(int(to_uom["id"]), 12)  # kg en categoría Peso

    def test_um_aliases_resolve_with_spanish_uom_catalog(self):
        """Sudata en es_419 devuelve 'Unidades' / 'Tonelada': los alias UN/MES/TN siguen mapeando."""
        es_rows = [
            {"id": 1, "name": "Unidades", "uom_type": "reference", "factor": 1.0, "category_id": [1, "Unidad"]},
            {"id": 15, "name": "kg", "uom_type": "reference", "factor": 1.0, "category_id": [2, "Peso"]},
            {"id": 16, "name": "Tonelada", "uom_type": "bigger", "factor": 0.001, "category_id": [2, "Peso"]},
        ]
        catalog = _build_uom_catalog(es_rows, relative=False)

        for raw in ("UN", "U", "UNIDAD", "UNIDADES", "PIEZA", "MES", "Units"):
            with self.subTest(raw=raw):
                uom = resolve_uom(raw, catalog)
                self.assertIsNotNone(uom, f"{raw} no resolvió con catálogo en español")
                self.assertEqual(int(uom["id"]), 1)
        self.assertEqual(int(resolve_uom("KG", catalog)["id"]), 15)
        self.assertEqual(int(resolve_uom("TN", catalog)["id"]), 16)

    def test_um_aliases_still_resolve_with_english_uom_catalog(self):
        en_rows = [
            {"id": 1, "name": "Units", "uom_type": "reference", "factor": 1.0, "category_id": [1, "Unit"]},
            {"id": 16, "name": "Ton", "uom_type": "bigger", "factor": 0.001, "category_id": [2, "Weight"]},
        ]
        catalog = _build_uom_catalog(en_rows, relative=False)

        self.assertEqual(int(resolve_uom("UNIDAD", catalog)["id"]), 1)
        self.assertEqual(int(resolve_uom("TONELADA", catalog)["id"]), 16)


# uom.uom tal como responde Sudata (Odoo 19): árbol relative_uom_id, factor = razón a la raíz.
ODOO19_UOM_ROWS = [
    {"id": 1, "name": "Unidades", "factor": 1.0, "relative_factor": 1.0, "relative_uom_id": False},
    {"id": 2, "name": "Paquete de 6", "factor": 6.0, "relative_factor": 6.0, "relative_uom_id": [1, "Unidades"]},
    {"id": 8, "name": "m", "factor": 1000.0, "relative_factor": 100.0, "relative_uom_id": [7, "cm"]},
    {"id": 11, "name": "ml", "factor": 1.0, "relative_factor": 1.0, "relative_uom_id": False},
    {"id": 12, "name": "L", "factor": 1000.0, "relative_factor": 1000.0, "relative_uom_id": [11, "ml"]},
    {"id": 14, "name": "g", "factor": 1.0, "relative_factor": 1.0, "relative_uom_id": False},
    {"id": 15, "name": "kg", "factor": 1000.0, "relative_factor": 1000.0, "relative_uom_id": [14, "g"]},
    {"id": 16, "name": "Tonelada", "factor": 1000000.0, "relative_factor": 1000.0, "relative_uom_id": [15, "kg"]},
]
# 'mm' y 'cm' archivados: search_read no los trae, cierran el árbol de 'm'.
ODOO19_ARCHIVED_UOMS = [
    {"id": 6, "name": "mm", "factor": 1.0, "relative_factor": 1.0, "relative_uom_id": False},
    {"id": 7, "name": "cm", "factor": 10.0, "relative_factor": 10.0, "relative_uom_id": [6, "mm"]},
]


def _build_uom_catalog(rows, *, relative, archived=None):
    """Arma el catálogo como en producción, con el modelo uom.uom indicado."""
    from facturia_matching.odoo import purchase_matching as pm

    def fake_search_read(model, domain=None, fields=None, limit=500, **kwargs):
        wanted = None
        for term in domain or []:
            if isinstance(term, (list, tuple)) and len(term) == 3 and term[0] == "id":
                wanted = set(term[2])
        if wanted is not None:
            return [r for r in (archived or []) if int(r["id"]) in wanted]
        return list(rows)

    with patch.object(pm, "odoo_search_read", side_effect=fake_search_read), patch.object(
        pm, "_purchase_odoo_config", return_value={"base_url": "x", "db": "y"}
    ), patch.object(pm, "_uom_model_is_relative", return_value=relative):
        return pm._fetch_uom_catalog()


class TestUomOdoo19Model(unittest.TestCase):
    """Odoo 19: uom.uom sin category_id/uom_type (Sudata)."""

    def setUp(self):
        from facturia_matching.odoo.purchase_matching import clear_purchase_cache

        clear_purchase_cache()
        self.catalog = _build_uom_catalog(
            ODOO19_UOM_ROWS, relative=True, archived=ODOO19_ARCHIVED_UOMS
        )

    def _uom(self, name_or_alias):
        from facturia_matching.odoo.purchase_matching import resolve_uom

        return resolve_uom(name_or_alias, self.catalog)

    def test_detects_relative_model_by_fields(self):
        from facturia_matching.odoo import purchase_matching as pm

        with patch.object(
            pm, "_purchase_odoo_config", return_value={"base_url": "x", "db": "y"}
        ), patch.object(
            pm,
            "odoo_model_field_names",
            return_value=frozenset({"name", "relative_factor", "relative_uom_id"}),
        ):
            self.assertTrue(pm._uom_model_is_relative())
        pm.clear_purchase_cache()
        with patch.object(
            pm, "_purchase_odoo_config", return_value={"base_url": "x", "db": "y"}
        ), patch.object(
            pm,
            "odoo_model_field_names",
            return_value=frozenset({"name", "category_id", "uom_type", "factor"}),
        ):
            self.assertFalse(pm._uom_model_is_relative())

    def test_unknown_fields_keep_legacy_model(self):
        """Si el fields_get falla no se asume Odoo 19: se sigue con el catálogo histórico."""
        from facturia_matching.odoo import purchase_matching as pm

        with patch.object(
            pm, "_purchase_odoo_config", return_value={"base_url": "x", "db": "y"}
        ), patch.object(pm, "odoo_model_field_names", return_value=frozenset()):
            self.assertFalse(pm._uom_model_is_relative())

    def test_tree_root_becomes_category(self):
        from facturia_matching.odoo.purchase_matching import _category_id

        weight = {self._uom(n)["id"]: _category_id(self._uom(n)) for n in ("g", "kg", "Tonelada")}
        self.assertEqual(set(weight.values()), {14})  # raíz g
        self.assertEqual(_category_id(self._uom("L")), 11)  # raíz ml
        self.assertEqual(_category_id(self._uom("Paquete de 6")), 1)  # raíz Unidades

    def test_archived_parents_close_the_tree(self):
        """'m' cuelga de cm (archivado): su categoría debe ser la raíz mm, no él mismo."""
        from facturia_matching.odoo.purchase_matching import _category_id

        self.assertEqual(_category_id(self._uom("m")), 6)

    def test_convert_qty_weight(self):
        from facturia_matching.odoo.purchase_matching import convert_qty

        self.assertAlmostEqual(convert_qty(1000.0, self._uom("g"), self._uom("kg")), 1.0)
        self.assertAlmostEqual(convert_qty(1.0, self._uom("kg"), self._uom("g")), 1000.0)
        self.assertAlmostEqual(convert_qty(2.0, self._uom("Tonelada"), self._uom("kg")), 2000.0)

    def test_convert_qty_units_and_packs(self):
        from facturia_matching.odoo.purchase_matching import convert_qty

        self.assertAlmostEqual(
            convert_qty(12.0, self._uom("Unidades"), self._uom("Paquete de 6")), 2.0
        )
        self.assertAlmostEqual(
            convert_qty(2.0, self._uom("Paquete de 6"), self._uom("Unidades")), 12.0
        )

    def test_convert_qty_across_trees_is_none(self):
        from facturia_matching.odoo.purchase_matching import convert_qty

        self.assertIsNone(convert_qty(1.0, self._uom("kg"), self._uom("L")))

    def test_aliases_resolve_in_relative_model(self):
        self.assertEqual(int(self._uom("UN")["id"]), 1)
        self.assertEqual(int(self._uom("KG")["id"]), 15)
        self.assertEqual(int(self._uom("LT")["id"]), 12)
        self.assertEqual(int(self._uom("TN")["id"]), 16)

    def test_scaling_uses_relative_catalog(self):
        from facturia_matching.odoo.purchase_matching import _apply_uom_scaling

        out = _apply_uom_scaling(
            {},
            invoice_qty=1000.0,
            invoice_um_raw="g",
            po_uom_id=15,
            po_uom_name="kg",
            uom_catalog=self.catalog,
        )
        self.assertEqual(out["um_empresa_id"], "15")
        self.assertEqual(out["um_note"], "Re-escalado")
        self.assertEqual(out["qty_escalada"], "1")

    def test_product_default_uom_without_uom_po_id(self):
        """Odoo 19 no tiene uom_po_id: pedirlo hacía fallar el search_read completo."""
        from facturia_matching.odoo import purchase_matching as pm

        captured = {}

        def fake_search_read(model, domain=None, fields=None, limit=500, **kwargs):
            captured["fields"] = list(fields or [])
            return [{"id": 5, "uom_id": [15, "kg"]}]

        with patch.object(pm, "odoo_search_read", side_effect=fake_search_read), patch.object(
            pm, "_purchase_odoo_config", return_value={"base_url": "x", "db": "y"}
        ), patch.object(pm, "is_purchase_odoo_configured", return_value=True), patch.object(
            pm, "odoo_available_fields", return_value=["uom_id"]
        ):
            self.assertEqual(pm._product_default_uom_id(5), 15)
        self.assertEqual(captured["fields"], ["uom_id"])

    def test_list_uoms_for_product_uses_tree(self):
        from facturia_matching.odoo import purchase_matching as pm

        with patch.object(pm, "_product_default_uom_id", return_value=15), patch.object(
            pm, "get_uom_catalog", return_value=self.catalog
        ):
            names = [u["name"] for u in pm.list_uoms_for_product(5)]
        self.assertEqual(names, ["g", "kg", "Tonelada"])


if __name__ == "__main__":
    unittest.main()
