"""Unit tests for process_conversions payload and persistence logic."""

import json
import unittest
from unittest.mock import MagicMock, patch

from facturia_matching.odoo.request_context import odoo_profile_context
from facturia_matching.core.process import backfill_fac_iva_montos_from_process

from facturia_matching.odoo.env import (
    ODOO_TEMPLATE_ID_ALIARE,
    ODOO_TEMPLATE_ID_DEFAULT,
    get_conversion_template_id,
)
from facturia_matching.persistence.process_conversions import (
    CONVERSION_FORMAT,
    ODOO_TEMPLATE_ID,
    build_converted_payload,
    delete_conversion,
    infer_otro_impuesto_indices,
    parse_converted_payload,
    resolve_process_row,
    save_conversion,
)


class TestProcessConversionsPayload(unittest.TestCase):
    def test_build_and_parse_roundtrip(self):
        rows = [
            {
                "partner_id": "1180",
                "otros_impuestos": "Percepción IIBB CABA Sufrida",
                "otros_impuestos_monto": "100",
            }
        ]
        raw = build_converted_payload(rows)
        data = json.loads(raw)
        self.assertEqual(data["format"], CONVERSION_FORMAT)
        self.assertEqual(data["version"], 1)
        self.assertIn("odoo_profile", data)
        self.assertEqual(parse_converted_payload(raw), rows)

    def test_conversion_template_id_aliare(self):
        with odoo_profile_context("aliare"):
            self.assertEqual(get_conversion_template_id(), ODOO_TEMPLATE_ID_ALIARE)

    def test_conversion_template_id_default(self):
        self.assertEqual(get_conversion_template_id(), ODOO_TEMPLATE_ID_DEFAULT)

    def test_infer_otro_impuesto_indices(self):
        rows = [
            {
                "otros_impuestos": "A",
                "otros_impuestos_monto": "1",
                "otros_impuestos_2": "B",
                "otros_impuestos_2_monto": "2",
                "otros_impuestos_3": "C",
            }
        ]
        self.assertEqual(infer_otro_impuesto_indices(rows), [1, 2, 3])

    def test_parse_rejects_invalid_format(self):
        with self.assertRaises(Exception):
            parse_converted_payload(json.dumps({"format": "excel", "rows": []}))

    def test_parse_rejects_missing_rows(self):
        with self.assertRaises(Exception):
            parse_converted_payload(json.dumps({"format": CONVERSION_FORMAT}))


class TestResolveProcessRow(unittest.TestCase):
    @patch("facturia_matching.persistence.process_conversions.get_process")
    def test_resolve_process_row_ok(self, mock_get):
        mock_get.return_value = {"id": 188, "company_id": 1, "user_id": 3, "process_number": 185}
        row = resolve_process_row("185", empresa="1")
        self.assertEqual(row["id"], 188)
        self.assertEqual(row["company_id"], 1)
        self.assertEqual(row["user_id"], 3)

    @patch("facturia_matching.persistence.process_conversions.get_process")
    def test_resolve_process_row_missing_company(self, mock_get):
        mock_get.return_value = {"id": 1, "company_id": None}
        with self.assertRaises(Exception):
            resolve_process_row("1")


class TestSaveConversion(unittest.TestCase):
    @patch("facturia_matching.persistence.process_conversions.ensure_export_template_exists")
    @patch("facturia_matching.persistence.process_conversions.get_mysql_connection")
    def test_save_conversion_insert(self, mock_conn_fn, _mock_ensure):
        conn = MagicMock()
        mock_conn_fn.return_value = conn
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = None
        cur.lastrowid = 42

        result = save_conversion(10, 1, 3, [{"partner_id": "1"}])

        self.assertEqual(result["id"], 42)
        self.assertEqual(result["process_id"], 10)
        self.assertEqual(result["template_id"], ODOO_TEMPLATE_ID)
        conn.commit.assert_called_once()
        insert_sql = cur.execute.call_args_list[-1][0][0]
        self.assertIn("INSERT INTO", insert_sql)

    @patch("facturia_matching.persistence.process_conversions.get_mysql_connection")
    def test_save_conversion_update(self, mock_conn_fn):
        conn = MagicMock()
        mock_conn_fn.return_value = conn
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = {"id": 7}

        result = save_conversion(10, 1, None, [{"partner_id": "2"}])

        self.assertEqual(result["id"], 7)
        update_sql = cur.execute.call_args_list[-1][0][0]
        self.assertIn("UPDATE", update_sql)
        conn.commit.assert_called_once()

    @patch("facturia_matching.persistence.process_conversions.get_mysql_connection")
    def test_delete_conversion(self, mock_conn_fn):
        conn = MagicMock()
        mock_conn_fn.return_value = conn
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.rowcount = 1

        deleted = delete_conversion(10)

        self.assertEqual(deleted, 1)
        delete_sql = cur.execute.call_args[0][0]
        self.assertIn("DELETE FROM", delete_sql)
        conn.commit.assert_called_once()


class TestBackfillFacIvaMontos(unittest.TestCase):
    @patch("facturia_matching.core.process.get_process")
    def test_backfill_from_process_json_without_line_iva(self, mock_get):
        mock_get.return_value = {
            "json_data": json.dumps(
                {
                    "facturas": [
                        {
                            "json": {
                                "factura": {
                                    "iva_21": "15893.38",
                                    "iva_10_5": "2832.75",
                                    "items": [{"descripcion": "Item A"}],
                                }
                            }
                        }
                    ]
                }
            )
        }
        rows = [{"__comprobante_idx": 0, "iva_pct": ""}]
        out = backfill_fac_iva_montos_from_process(rows, "123")
        montos = json.loads(out[0]["__fac_iva_montos"])
        self.assertEqual(montos.get("21"), "15893.38")
        self.assertEqual(montos.get("10.5"), "2832.75")
        self.assertTrue(str(out[0].get("__fac_iva_monto") or "").strip())


class TestConversionIvaMetadata(unittest.TestCase):
    def test_roundtrip_preserves_fac_iva_metadata(self):
        rows = [
            {
                "partner_id": "1",
                "__fac_subtotal": "110024.13",
                "__fac_iva_monto": "20521.22",
                "__fac_iva_montos": '{"21": "20521.22"}',
            }
        ]
        raw = build_converted_payload(rows)
        parsed = parse_converted_payload(raw)
        self.assertEqual(parsed[0]["__fac_iva_montos"], rows[0]["__fac_iva_montos"])
        self.assertEqual(parsed[0]["__fac_subtotal"], rows[0]["__fac_subtotal"])
        self.assertEqual(parsed[0]["__fac_iva_monto"], rows[0]["__fac_iva_monto"])


if __name__ == "__main__":
    unittest.main()
