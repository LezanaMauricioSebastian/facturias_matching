"""Tests for purchase order matching and UOM scaling."""
import unittest

from purchase_matching import (
    _canonical_um,
    _extract_qty_um_from_description,
    _line_match_score,
    _ocr_fix_token,
    convert_qty,
    match_invoice_row,
    resolve_uom,
)


class TestPurchaseMatching(unittest.TestCase):
    def test_canonical_um(self):
        self.assertEqual(_canonical_um("unidad(es)"), "Units")
        self.assertEqual(_canonical_um("kgs"), "kg")

    def test_extract_qty_um_from_description(self):
        qty, um = _extract_qty_um_from_description("6 kg pan líquido")
        self.assertAlmostEqual(qty, 6.0)
        self.assertEqual(um, "kg")

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

    def test_convert_qty_same_category(self):
        from_uom = {"id": 13, "factor": 1000.0, "category_id": [2, "Weight"]}
        to_uom = {"id": 12, "factor": 1.0, "category_id": [2, "Weight"]}
        self.assertAlmostEqual(convert_qty(1000.0, from_uom, to_uom), 1.0)

    def test_match_invoice_row_without_po(self):
        row = {
            "invoice_line_ids/name": "Producto X",
            "invoice_line_ids/quantity": "2",
            "__item_codigo": "",
            "__um_proveedor": "UN",
        }
        out = match_invoice_row(row, [], {"by_name": {}, "by_id": {}})
        self.assertIn("Sin OC", out["__oc_match_note"])


if __name__ == "__main__":
    unittest.main()
