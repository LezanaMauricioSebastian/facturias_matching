"""Smoke / wiring tests for the composed API router."""

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from facturia_matching.api.proceso_response import (
    _build_proceso_response,
    _handle_process_load_errors,
)
from facturia_matching.api.profile import _public_health_payload
from facturia_matching.api.route_meta import post_csv
from facturia_matching.api.route_meta import router as meta_router
from facturia_matching.api.route_odoo import odoo_health, odoo_import
from facturia_matching.api.route_odoo import router as odoo_router
from facturia_matching.api.route_proceso import get_proceso, put_proceso_conversion
from facturia_matching.api.route_proceso import router as proceso_router
from facturia_matching.api.routes import router
from facturia_matching.persistence.back_check import MySQLUnavailableError
from facturia_matching.persistence.process_conversions import ProcessConversionError


def _collect_routes(*routers):
    registered = {}
    for rtr in routers:
        for route in rtr.routes:
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None) or set()
            if path is None or not methods:
                continue
            registered.setdefault(path, set()).update(methods)
    return registered


EXPECTED_ROUTES = [
    ("/", {"GET"}),
    ("/api/metadata", {"GET"}),
    ("/api/bootstrap", {"GET"}),
    ("/api/options", {"GET"}),
    ("/api/odoo/health", {"GET"}),
    ("/api/odoo/health/import", {"GET"}),
    ("/api/odoo/health/credenciales_db", {"GET"}),
    ("/api/odoo/health/credenciales", {"POST"}),
    ("/api/odoo/import", {"POST"}),
    ("/api/padron/schema", {"GET"}),
    ("/api/padron/odoo", {"GET"}),
    ("/api/proceso/{process_number}", {"GET"}),
    ("/api/proceso/{process_number}/select-oc", {"POST"}),
    ("/api/proceso/{process_number}/search-oc", {"POST"}),
    ("/api/proceso/{process_number}/rematch-purchase", {"POST"}),
    ("/api/proceso/{process_number}/rematch-uom", {"POST"}),
    ("/api/proceso/{process_number}/product-uoms", {"GET"}),
    ("/api/proceso/{process_number}/conversion", {"PUT"}),
    ("/api/proceso/{process_number}/revert", {"POST"}),
    ("/api/csv", {"POST"}),
]


class TestRouteRegistry(unittest.TestCase):
    def test_expected_paths_and_methods_registered(self):
        # Prefer domain routers; also walk facade includes for wiring check.
        registered = _collect_routes(meta_router, odoo_router, proceso_router)
        self.assertEqual(len(router.routes), 3)
        for included in router.routes:
            original = getattr(included, "original_router", None)
            if original is not None:
                registered.update(_collect_routes(original))

        for path, methods in EXPECTED_ROUTES:
            self.assertIn(path, registered, f"missing path {path}")
            self.assertTrue(
                methods.issubset(registered[path]),
                f"{path}: expected {methods}, got {registered[path]}",
            )


class TestValidation400(unittest.TestCase):
    def test_odoo_import_requires_rows_list(self):
        with self.assertRaises(HTTPException) as ctx:
            odoo_import({"rows": "nope"})
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("lista", ctx.exception.detail)

    def test_csv_requires_rows_list(self):
        with self.assertRaises(HTTPException) as ctx:
            post_csv({})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_conversion_requires_rows_list(self):
        with self.assertRaises(HTTPException) as ctx:
            put_proceso_conversion("123", {"empresa": "1"})
        self.assertEqual(ctx.exception.status_code, 400)


class TestGetProcesoSmoke(unittest.TestCase):
    @patch("facturia_matching.api.route_proceso.load_process_rows")
    @patch(
        "facturia_matching.api.proceso_response.build_output_rows",
        side_effect=lambda rows: rows,
    )
    def test_get_proceso_shape(self, _mock_build, mock_load):
        mock_load.return_value = (
            [{"partner_id": "1"}],
            ["Producto A"],
            {"matched": 1},
            "json",
            {"id": 9, "saved_at": "2026-01-01"},
        )
        body = get_proceso("42", empresa="1")
        self.assertTrue(body["ok"])
        self.assertEqual(body["process_number"], "42")
        self.assertEqual(body["empresa"], "1")
        self.assertEqual(body["source"], "json")
        self.assertEqual(body["rows"], [{"partner_id": "1"}])
        self.assertEqual(body["purchase_matching"], {"matched": 1})
        self.assertEqual(body["conversion_id"], 9)
        self.assertEqual(body["etiqueta_options"], ["Producto A"])


class TestHealthPrivacy(unittest.TestCase):
    def test_public_health_payload_strips_uids(self):
        out = _public_health_payload(
            {
                "ok": True,
                "uid": 99,
                "auth_uid": 7,
                "uid_source": "authenticate",
                "db": "demo",
            }
        )
        self.assertEqual(out, {"ok": True, "db": "demo"})
        self.assertNotIn("uid", out)
        self.assertNotIn("auth_uid", out)
        self.assertNotIn("uid_source", out)

    @patch("facturia_matching.api.route_odoo.odoo_xmlrpc_version", return_value={"server_version": "17"})
    @patch("facturia_matching.api.route_odoo._jsonrpc_url", return_value="https://x/jsonrpc")
    @patch("facturia_matching.api.route_odoo.verify_odoo_config_connection")
    @patch("facturia_matching.api.route_odoo.is_odoo_config_ready", return_value=True)
    @patch("facturia_matching.api.route_odoo.get_active_odoo_config")
    def test_odoo_health_hides_uid(self, mock_cfg, _ready, mock_verify, _url, _ver):
        mock_cfg.return_value = {
            "db": "demo",
            "base_url": "https://x",
            "credential_source": "env",
        }
        mock_verify.return_value = {
            "ok": True,
            "uid": 12,
            "auth_uid": 12,
            "uid_source": "authenticate",
            "version": {"server_version": "17"},
        }
        body = odoo_health()
        self.assertTrue(body["ok"])
        self.assertNotIn("uid", body)
        self.assertNotIn("auth_uid", body)
        self.assertNotIn("uid_source", body)
        self.assertEqual(body["db"], "demo")


class TestProcesoResponseHelpers(unittest.TestCase):
    @patch(
        "facturia_matching.api.proceso_response.current_odoo_profile",
        return_value="default",
    )
    def test_empty_filas_message(self, _profile):
        out = _build_proceso_response("1", None, [], [], {}, "json")
        self.assertEqual(out["rows"], [])
        self.assertIn("Sin filas", out["message"])

    @patch(
        "facturia_matching.api.proceso_response.build_output_rows",
        side_effect=lambda rows: rows,
    )
    @patch(
        "facturia_matching.api.proceso_response.current_odoo_profile",
        return_value="aliare",
    )
    def test_with_filas_includes_purchase(self, _profile, _build):
        out = _build_proceso_response(
            "2",
            "4",
            [{"a": 1}],
            ["x"],
            {"ok": True},
            "saved",
            {"id": 3},
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["purchase_matching"], {"ok": True})
        self.assertEqual(out["conversion_id"], 3)
        self.assertEqual(out["odoo_profile"], "aliare")

    def test_handle_mysql_unavailable_is_503(self):
        with self.assertRaises(HTTPException) as ctx:
            _handle_process_load_errors(
                lambda: (_ for _ in ()).throw(MySQLUnavailableError("down"))
            )
        self.assertEqual(ctx.exception.status_code, 503)

    def test_handle_conversion_error_is_400(self):
        with self.assertRaises(HTTPException) as ctx:
            _handle_process_load_errors(
                lambda: (_ for _ in ()).throw(ProcessConversionError("bad"))
            )
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
