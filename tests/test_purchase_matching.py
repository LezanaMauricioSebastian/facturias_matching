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


if __name__ == "__main__":
    unittest.main()
