"""Tests for purchase line/product matching, Dinner notes, and OCR helpers."""
import unittest
from unittest.mock import patch

from facturia_matching.odoo.purchase_matching import (
    _attach_dinner_po_note_labels,
    _canonical_um,
    _line_match_score,
    _ocr_fix_token,
    match_invoice_row,
)


class TestPurchaseMatching(unittest.TestCase):
    def test_canonical_um(self):
        self.assertEqual(_canonical_um("unidad(es)"), "Units")
        self.assertEqual(_canonical_um("kgs"), "kg")

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

    def test_match_invoice_row_without_po(self):
        row = {
            "invoice_line_ids/name": "Producto X",
            "invoice_line_ids/quantity": "2",
            "__item_codigo": "",
            "__um_proveedor": "UN",
        }
        out = match_invoice_row(row, [], {"by_name": {}, "by_id": {}})
        self.assertIn("Sin OC", out["__oc_match_note"])
