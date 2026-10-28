"""Confirmation gate for Facturia MCP (no live Odoo / matching UI)."""

from __future__ import annotations

import time
import unittest
from unittest import mock

from facturia_matching.mcp.confirm import ConfirmStore, ConfirmationError
from facturia_matching.mcp.facturia_client import extract_init_callback
from facturia_matching.mcp.preview import build_match_preview
from facturia_matching.mcp import server as mcp_server


def _sample_rows():
    return [
        {
            "__comprobante_idx": 0,
            "partner_id": "ACME SA",
            "CUIT": "30-11111111-1",
            "l10n_latam_document_number": "0001-00001234",
            "l10n_latam_document_type_id": "FACTURAS A",
            "invoice_date": "2026-01-15",
            "journal_id": "Compras",
            "__fac_subtotal": "1000",
            "__fac_iva_monto": "210",
            "invoice_line_ids/name": "Servicio",
            "invoice_line_ids/product_id": "PROD-1",
            "invoice_line_ids/account_id": "ACC-1",
            "invoice_line_ids/quantity": "1",
            "invoice_line_ids/price_unit": "1000",
            "iva_pct": "21",
        }
    ]


class TestMatchPreview(unittest.TestCase):
    def test_ready(self):
        summary = build_match_preview(
            _sample_rows(), process_number="42", odoo_profile="aliare"
        )
        self.assertTrue(summary["ready_for_draft_import"])
        self.assertEqual(summary["comprobante_count"], 1)
        self.assertEqual(summary["gaps"], [])
        self.assertIn("confirm_invoice_preview", summary["ask_user"])

    def test_gaps(self):
        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "",
                "l10n_latam_document_number": "",
                "invoice_line_ids/name": "X",
                "invoice_line_ids/product_id": "",
                "invoice_line_ids/account_id": "",
            }
        ]
        summary = build_match_preview(rows, process_number="7")
        self.assertFalse(summary["ready_for_draft_import"])
        joined = " ".join(summary["gaps"]).lower()
        self.assertIn("proveedor", joined)
        self.assertTrue("producto" in joined or "sin producto" in joined)


class TestConfirmStore(unittest.TestCase):
    def test_requires_token_for_import(self):
        store = ConfirmStore(secret="test-secret")
        with self.assertRaises(ConfirmationError) as ctx:
            store.consume_for_import("")
        self.assertIn("confirmation_token", str(ctx.exception).lower())

    def test_happy_path_single_use(self):
        store = ConfirmStore(secret="test-secret")
        rows = _sample_rows()
        summary = build_match_preview(rows, process_number="99")
        rec = store.create_preview(
            process_number="99",
            rows=rows,
            summary=summary,
            empresa="1",
            odoo_profile="aliare",
        )
        token = store.confirm(rec.preview_id)
        self.assertTrue(token)
        bound = store.consume_for_import(token)
        self.assertEqual(bound.process_number, "99")
        self.assertEqual(bound.rows, rows)
        with self.assertRaises(ConfirmationError):
            store.consume_for_import(token)

    def test_confirm_expires(self):
        store = ConfirmStore(secret="test-secret", preview_ttl_sec=60, confirm_ttl_sec=1)
        rec = store.create_preview(
            process_number="1",
            rows=_sample_rows(),
            summary={},
        )
        token = store.confirm(rec.preview_id)
        with store._lock:
            store._previews[rec.preview_id].confirmed_at = time.time() - 5
        with self.assertRaises(ConfirmationError) as ctx:
            store.consume_for_import(token)
        self.assertIn("expir", str(ctx.exception).lower())


class TestFacturiaInitExtract(unittest.TestCase):
    def test_nested_callback_token(self):
        import_id, token = extract_init_callback(
            {"data": {"import_id": "12", "callback_token": "abc"}}
        )
        self.assertEqual(import_id, 12)
        self.assertEqual(token, "abc")


class TestImportTool(unittest.TestCase):
    def test_blocks_without_token(self):
        out = mcp_server.tool_import_odoo_draft("")
        self.assertFalse(out["ok"])
        self.assertTrue(
            "confirmation_token" in out["error"].lower() or "Falta" in out["error"]
        )

    def test_uses_api_after_confirm(self):
        calls = {}

        class FakeApi:
            def import_odoo(self, rows, **kwargs):
                calls["rows"] = rows
                calls["kwargs"] = kwargs
                return {"created": 1, "errors": []}

        with mock.patch.object(mcp_server, "_client", FakeApi()), mock.patch.object(
            mcp_server, "_store", ConfirmStore(secret="t")
        ):
            rows = _sample_rows()
            rec = mcp_server._store.create_preview(
                process_number="55",
                rows=rows,
                summary=build_match_preview(rows, process_number="55"),
                empresa="1",
                odoo_profile="default",
                erp_import_id=99,
                erp_import_token="cb-tok",
            )
            conf = mcp_server.tool_confirm_invoice_preview(rec.preview_id)
            self.assertTrue(conf["ok"])
            out = mcp_server.tool_import_odoo_draft(conf["confirmation_token"])
            self.assertTrue(out["ok"])
            self.assertEqual(out["target_state"], "draft")
            self.assertTrue(out["facturia_webhook_requested"])
            self.assertEqual(calls["kwargs"]["odoo_profile"], "default")
            self.assertEqual(calls["kwargs"]["import_id"], 99)
            self.assertEqual(calls["kwargs"]["token"], "cb-tok")
            self.assertEqual(calls["rows"], rows)


if __name__ == "__main__":
    unittest.main()
