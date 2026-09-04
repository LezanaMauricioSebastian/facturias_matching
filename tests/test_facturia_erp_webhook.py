"""Tests del webhook FacturIA erp-imports."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from facturia_matching.facturia.erp_import_webhook import (
    build_webhook_payload,
    extract_erp_import_callback,
    notify_erp_import_webhook,
    resolve_erp_import_webhook_url,
    resolve_facturia_base_url,
)


class TestResolveUrls(unittest.TestCase):
    @patch("facturia_matching.facturia.erp_import_webhook.env_strip", return_value="")
    def test_staging_schema(self, _env):
        self.assertEqual(
            resolve_facturia_base_url("sudataco_staging"),
            "https://facturia-staging.sudata.co",
        )
        self.assertEqual(
            resolve_erp_import_webhook_url("sudataco_staging"),
            "https://facturia-staging.sudata.co/api/erp-imports/webhook",
        )

    @patch("facturia_matching.facturia.erp_import_webhook.env_strip", return_value="")
    def test_prod_schema(self, _env):
        self.assertEqual(
            resolve_facturia_base_url("sudataco_facturia"),
            "https://facturia.sudata.co",
        )

    @patch(
        "facturia_matching.facturia.erp_import_webhook.env_strip",
        side_effect=lambda k, d="": {
            "FACTURIA_BASE_URL": "https://custom.example",
            "FACTURIA_ERP_WEBHOOK_URL": "",
        }.get(k, d),
    )
    def test_explicit_base(self, _env):
        self.assertEqual(
            resolve_erp_import_webhook_url("sudataco_facturia"),
            "https://custom.example/api/erp-imports/webhook",
        )


class TestExtractAndBuild(unittest.TestCase):
    def test_extract_aliases(self):
        import_id, token = extract_erp_import_callback(
            {"erp_import_id": "12", "callback_token": "abc"}
        )
        self.assertEqual(import_id, 12)
        self.assertEqual(token, "abc")

    def test_build_completed(self):
        body = build_webhook_payload(
            import_id=3,
            token="tok",
            import_result={
                "ok": True,
                "created": [{"move_id": 1}],
                "updated_taxes": [{"move_id": 2}],
                "errors": [],
            },
        )
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["comprobantes_importados"], 2)
        self.assertEqual(body["import_id"], 3)
        self.assertEqual(body["token"], "tok")

    def test_build_failed(self):
        body = build_webhook_payload(
            import_id=3,
            token="tok",
            import_result={"ok": False, "created": [], "updated_taxes": [], "errors": [{}]},
        )
        self.assertEqual(body["status"], "failed")
        self.assertEqual(body["comprobantes_importados"], 0)


class TestNotify(unittest.TestCase):
    @patch("facturia_matching.facturia.erp_import_webhook.requests.post")
    @patch(
        "facturia_matching.facturia.erp_import_webhook.resolve_erp_import_webhook_url",
        return_value="https://facturia-staging.sudata.co/api/erp-imports/webhook",
    )
    def test_notify_posts_json(self, _url, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"status": true}'
        mock_resp.json.return_value = {"status": True}
        mock_post.return_value = mock_resp

        out = notify_erp_import_webhook(
            import_id=9,
            token="secret",
            import_result={"ok": True, "created": [{}], "updated_taxes": [], "errors": []},
        )
        self.assertTrue(out["ok"])
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://facturia-staging.sudata.co/api/erp-imports/webhook")
        self.assertEqual(kwargs["json"]["import_id"], 9)
        self.assertEqual(kwargs["json"]["token"], "secret")
        self.assertEqual(kwargs["json"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
