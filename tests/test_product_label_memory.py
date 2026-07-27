"""Tests for product label learning from past process conversions."""

import unittest

from facturia_matching.odoo.purchase_matching import match_invoice_row
from facturia_matching.persistence.product_label_memory import (
    build_product_memory_index,
    is_confirmed_product_choice,
    lookup_in_index,
    normalize_label_key,
)
from unittest.mock import patch


class TestProductLabelMemory(unittest.TestCase):
    def test_normalize_label_key(self):
        self.assertEqual(normalize_label_key("  sprite  2L "), "SPRITE 2L")

    def test_skips_fuzzy_suggested_rows(self):
        row = {
            "partner_id": "10",
            "invoice_line_ids/name": "SPRITE",
            "invoice_line_ids/product_id": "99",
            "__product_suggested": "82",
            "__comprobante_idx": 0,
        }
        self.assertFalse(is_confirmed_product_choice(row))
        index = build_product_memory_index([[row]])
        self.assertEqual(index, {})

    def test_index_takes_most_recent_confirmed_choice(self):
        older = [
            {
                "partner_id": "42",
                "invoice_line_ids/name": "SPRITE",
                "invoice_line_ids/product_id": "100",
                "__product_suggested": "",
                "__comprobante_idx": 0,
            }
        ]
        newer = [
            {
                "partner_id": "42",
                "invoice_line_ids/name": "sprite",
                "invoice_line_ids/product_id": "777",
                "__product_suggested": "",
                "__comprobante_idx": 0,
            }
        ]
        # conversion_row_lists: newest first
        index = build_product_memory_index([newer, older])
        self.assertEqual(lookup_in_index(index, 42, "SPRITE"), 777)

    def test_propagates_partner_from_comprobante_header(self):
        rows = [
            {
                "partner_id": "42",
                "invoice_line_ids/name": "HEADER",
                "invoice_line_ids/product_id": "",
                "__comprobante_idx": 0,
            },
            {
                "partner_id": "",
                "invoice_line_ids/name": "SPRITE",
                "invoice_line_ids/product_id": "555",
                "__product_suggested": "",
                "__comprobante_idx": 0,
            },
        ]
        index = build_product_memory_index([rows])
        self.assertEqual(lookup_in_index(index, "42", "SPRITE"), 555)

    def test_match_invoice_row_prefers_learned_over_fuzzy(self):
        row = {
            "invoice_line_ids/name": "SPRITE",
            "invoice_line_ids/quantity": "1",
            "partner_id": "42",
        }
        # Fuzzy pool would suggest another product; memory must win.
        pool = [
            {
                "line_name": "SPRITE",
                "product_qty": 1,
                "product_id": 111,
                "order_name": "P1",
                "order_id": 1,
                "line_id": 1,
                "partner_ref": "",
                "qty_received": 0,
                "qty_invoiced": 0,
                "product_uom_id": 1,
                "product_uom_name": "Units",
            }
        ]
        out = match_invoice_row(
            row,
            [],
            {"by_name": {}, "by_id": {}},
            suggest_pool=pool,
            learned_product_id=777,
        )
        self.assertEqual(row.get("invoice_line_ids/product_id"), "777")
        self.assertEqual(out.get("__product_suggested"), "memory")
        self.assertIn("aprendido", out.get("__oc_match_note", "").lower())
        self.assertFalse(out.get("__oc_line_id"))

    def test_match_invoice_row_oc_beats_learned(self):
        row = {
            "invoice_line_ids/name": "CON-CHOCLO",
            "__item_codigo": "100967",
            "invoice_line_ids/quantity": "3",
            "__um_proveedor": "KG",
        }
        po_lines = [
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
        out = match_invoice_row(
            row,
            po_lines,
            {"by_name": {}, "by_id": {}},
            learned_product_id=999,
        )
        self.assertEqual(row.get("invoice_line_ids/product_id"), "575")
        self.assertEqual(out.get("__oc_line_id"), "1")
        self.assertFalse(out.get("__product_suggested"))

    def test_duplicate_oc_line_falls_back_to_memory(self):
        """Si la línea OC ya está usada, no dejar vacío: aplicar memoria."""
        from facturia_matching.odoo.purchase_matching import _match_comprobante_rows

        po = {
            "line_name": "ZERO",
            "product_qty": 1,
            "product_id": 111,
            "order_name": "P1",
            "order_id": 9,
            "line_id": 77,
            "partner_ref": "",
            "qty_received": 0,
            "qty_invoiced": 0,
            "product_uom_id": 1,
            "product_uom_name": "Units",
        }
        rows = [
            {
                "partner_id": "1582",
                "invoice_line_ids/name": "COCA-COLA ZERO 600*06 PET",
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/product_id": "",
                "__comprobante_idx": 0,
            },
            {
                "partner_id": "1582",
                "invoice_line_ids/name": "BENEDICTINO SIN GAS 600*12 PET 5548 ACUERDO GCIA.",
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/product_id": "",
                "__comprobante_idx": 0,
            },
        ]
        memory = {(1582, "BENEDICTINO SIN GAS 600*12 PET 5548 ACUERDO GCIA."): 620}
        with patch(
            "facturia_matching.odoo.purchase_matching._line_match_score",
            return_value=90.0,
        ):
            _match_comprobante_rows(
                rows,
                [po],
                {"by_name": {}, "by_id": {}},
                selected_order_id=9,
                product_memory=memory,
            )
        self.assertEqual(rows[0].get("__oc_line_id"), "77")
        self.assertEqual(rows[1].get("__oc_line_id"), "")
        self.assertEqual(rows[1].get("invoice_line_ids/product_id"), "620")
        self.assertEqual(rows[1].get("__product_suggested"), "memory")
        self.assertIn("asignada", (rows[1].get("__oc_match_note") or "").lower())


if __name__ == "__main__":
    unittest.main()
