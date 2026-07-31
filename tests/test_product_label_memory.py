"""Tests for product label learning from past process conversions."""

import unittest

from facturia_matching.odoo.purchase_matching import match_invoice_row
from facturia_matching.persistence.product_label_memory import (
    build_product_memory_index,
    is_confirmed_product_choice,
    lookup_in_index,
    normalize_label_key,
)
from unittest.mock import MagicMock, patch


class TestProductLabelMemory(unittest.TestCase):
    def test_normalize_label_key(self):
        self.assertEqual(normalize_label_key("  sprite  2L "), "SPRITE 2L")
        self.assertEqual(normalize_label_key("Aquarius 0,5L*06PET"), "AQUARIUS 0.5L 6PET")
        self.assertEqual(
            normalize_label_key("BENEDICTINO SIN GAS 600*12 PET 5548 ACUERDO GCIA."),
            normalize_label_key("benedictino sin gas 600×12 pet 5548 acuerdo gcia"),
        )
        self.assertEqual(normalize_label_key("TOMATE SECO"), normalize_label_key("Tomate Seco"))
        # Contenido distinto sigue siendo distinto (no es fuzzy).
        self.assertNotEqual(
            normalize_label_key("SPRITE FX LS 500ML"),
            normalize_label_key("SPRITE FV LS 500ML"),
        )

    def test_lookup_fuzzy_matches_near_labels(self):
        key = normalize_label_key(
            "SPRITE FX LS 500ML NR 06PET 5548 ACUERDO GCIA."
        )
        index = {(1582, key): 620}
        # Misma familia con formato distinto (6*6PET vs 06PET + cola).
        self.assertEqual(
            lookup_in_index(index, 1582, "SPRITE FX LS 500ML NR 6*6PET"),
            620,
        )

    def test_lookup_fuzzy_rejects_sin_gas_vs_con_gas(self):
        key = normalize_label_key(
            "BENEDICTINO SIN GAS 600*12 PET 5548 ACUERDO GCIA."
        )
        index = {(1582, key): 620}
        self.assertIsNone(
            lookup_in_index(
                index, 1582, "BENEDICTINO C/G 600*12 PET 5548 ACUERDO GCIA."
            )
        )

    def test_lookup_fuzzy_rejects_zero_mismatch(self):
        key = normalize_label_key("COCA-COLA 600*12 PET 5548 ACUERDO GCIA.")
        index = {(1582, key): 620}
        self.assertIsNone(
            lookup_in_index(
                index, 1582, "COCA-COLA ZERO 600*06 PET 5548 ACUERDO GCIA."
            )
        )

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

    def test_match_invoice_row_learned_beats_oc(self):
        """Memoria gana al match OC cuando el producto aprendido es otro."""
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
        self.assertEqual(row.get("invoice_line_ids/product_id"), "999")
        self.assertEqual(out.get("__product_suggested"), "memory")
        self.assertFalse(out.get("__oc_line_id"))
        self.assertIn("aprendido", out.get("__oc_match_note", "").lower())

    def test_match_invoice_row_learned_keeps_oc_when_same_product(self):
        """Si memoria y OC coinciden en product_id, se sugiere y se vincula OC."""
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
            learned_product_id=575,
        )
        self.assertEqual(row.get("invoice_line_ids/product_id"), "575")
        self.assertEqual(out.get("__product_suggested"), "memory")
        self.assertEqual(out.get("__oc_line_id"), "1")

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
        memory = {
            (
                1582,
                normalize_label_key(
                    "BENEDICTINO SIN GAS 600*12 PET 5548 ACUERDO GCIA."
                ),
            ): 620
        }
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
        self.assertIn("aprendido", (rows[1].get("__oc_match_note") or "").lower())

    @patch("facturia_matching.persistence.product_label_memory.get_conversion_template_id", return_value=99)
    @patch("facturia_matching.persistence.product_label_memory.ensure_product_label_memory_table")
    @patch("facturia_matching.persistence.product_label_memory.get_mysql_connection")
    def test_upsert_writes_confirmed_choices(self, mock_conn_fn, _ensure, _tid):
        from facturia_matching.persistence import product_label_memory as mem

        conn = MagicMock()
        mock_conn_fn.return_value = conn
        cur = MagicMock()
        conn.cursor.return_value = cur
        rows = [
            {
                "partner_id": "1582",
                "invoice_line_ids/name": "SPRITE",
                "invoice_line_ids/product_id": "620",
                "__product_suggested": "",
                "__comprobante_idx": 0,
            },
            {
                "partner_id": "1582",
                "invoice_line_ids/name": "FANTA",
                "invoice_line_ids/product_id": "111",
                "__product_suggested": "82",
                "__comprobante_idx": 0,
            },
        ]
        n = mem.upsert_product_memory_choices(
            1, rows, template_id=99, source_process_id=290, source_conversion_id=140
        )
        self.assertEqual(n, 1)
        self.assertEqual(cur.execute.call_count, 1)
        sql = cur.execute.call_args[0][0]
        self.assertIn("ON DUPLICATE KEY UPDATE", sql)
        args = cur.execute.call_args[0][1]
        self.assertEqual(args[0], 1)
        self.assertEqual(args[1], 99)
        self.assertEqual(args[2], 1582)
        self.assertEqual(args[3], "SPRITE")
        self.assertEqual(args[4], 620)

    @patch("facturia_matching.persistence.product_label_memory._seed_table_from_conversions")
    @patch("facturia_matching.persistence.product_label_memory.fetch_memory_index_from_table")
    def test_build_index_seeds_when_table_empty(self, mock_fetch, mock_seed):
        from facturia_matching.persistence import product_label_memory as mem

        mock_fetch.return_value = {}
        mock_seed.return_value = {(1582, "SPRITE"): 620}
        index = mem.build_memory_index_for_company(1, template_id=99)
        self.assertEqual(index[(1582, "SPRITE")], 620)
        mock_seed.assert_called_once()


if __name__ == "__main__":
    unittest.main()
