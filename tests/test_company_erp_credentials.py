"""Tests: credenciales Odoo desde company_erp_credentials (MySQL)."""

import unittest
from unittest.mock import patch

import facturia_matching.odoo.empresa_profile  # noqa: F401 — para patches

from facturia_matching.odoo.env import (
    _config_from_credential_map,
    build_odoo_main_config,
)
from facturia_matching.odoo.request_context import odoo_profile_context
from facturia_matching.persistence.company_erp_credentials import (
    fetch_company_odoo_credential_map,
)


class TestConfigFromCredentialMap(unittest.TestCase):
    @patch("facturia_matching.odoo.env.resolve_odoo_db_name", side_effect=lambda *a, **k: (a[1] or "").strip())
    def test_maps_email_user_id_to_login(self, _mock_db):
        cfg = _config_from_credential_map(
            {
                "ODOO_BASE_URL": "https://dinner-test.odoo.com/",
                "ODOO_ENDPOINT": "/jsonrpc",
                "ODOO_DB": "dinner-test-31946929",
                "ODOO_USER_ID": "user@example.com",
                "ODOO_PASSWORD": "secret-key",
            },
            company_id=1,
        )
        self.assertEqual(cfg["base_url"], "https://dinner-test.odoo.com")
        self.assertEqual(cfg["endpoint"], "jsonrpc")
        # ODOO_DB de la tabla se pasa a resolve (si está stale, resolve lo descarta)
        self.assertEqual(cfg["db"], "dinner-test-31946929")
        self.assertEqual(cfg["login"], "user@example.com")
        self.assertIsNone(cfg["uid"])
        self.assertEqual(cfg["password"], "secret-key")
        self.assertEqual(cfg["credential_source"], "company_erp_credentials")
        self.assertEqual(cfg["company_id"], 1)
        _mock_db.assert_called()
        self.assertEqual(_mock_db.call_args.args[1], "dinner-test-31946929")

    @patch("facturia_matching.odoo.env.resolve_odoo_db_name", side_effect=lambda *a, **k: (a[1] or "").strip())
    def test_numeric_user_id_becomes_uid(self, _mock_db):
        cfg = _config_from_credential_map(
            {
                "ODOO_BASE_URL": "https://example.odoo.com",
                "ODOO_USER_ID": "42",
                "ODOO_PASSWORD": "x",
                "ODOO_DB": "db1",
            },
            company_id="3",
        )
        self.assertEqual(cfg["uid"], 42)
        self.assertEqual(cfg["login"], "")
        self.assertEqual(cfg["db"], "db1")
        self.assertEqual(_mock_db.call_args.args[1], "db1")

    @patch(
        "facturia_matching.odoo.env.resolve_odoo_db_name",
        side_effect=lambda *a, **k: "resolved-from-list",
    )
    def test_stale_mysql_db_still_goes_through_resolve(self, mock_db):
        cfg = _config_from_credential_map(
            {
                "ODOO_BASE_URL": "https://dinner-test.odoo.com",
                "ODOO_USER_ID": "a@b.com",
                "ODOO_PASSWORD": "tok",
                "ODOO_DB": "dinner-test-stale",
            },
            company_id=1,
        )
        self.assertEqual(cfg["db"], "resolved-from-list")
        mock_db.assert_called_once()
        self.assertEqual(mock_db.call_args.args[1], "dinner-test-stale")


class TestBuildPrefersMysql(unittest.TestCase):
    @patch("facturia_matching.odoo.env.resolve_odoo_db_name", side_effect=lambda *a, **k: a[1] or "db")
    @patch(
        "facturia_matching.persistence.company_erp_credentials.fetch_company_odoo_credential_map"
    )
    @patch("facturia_matching.odoo.empresa_profile.resolve_odoo_profile_from_empresa")
    def test_mysql_wins_when_empresa_matches_profile(
        self, mock_map, mock_fetch, _mock_db
    ):
        mock_map.return_value = "default"
        mock_fetch.return_value = {
            "ODOO_BASE_URL": "https://from-mysql.odoo.com",
            "ODOO_DB": "mysql-db",
            "ODOO_USER_ID": "a@b.com",
            "ODOO_PASSWORD": "tok",
            "ODOO_ENDPOINT": "/jsonrpc",
        }
        with odoo_profile_context("default", empresa="1"):
            cfg = build_odoo_main_config("default", company_id="1")
        self.assertEqual(cfg["base_url"], "https://from-mysql.odoo.com")
        self.assertEqual(cfg["credential_source"], "company_erp_credentials")
        mock_fetch.assert_called()

    @patch(
        "facturia_matching.persistence.company_erp_credentials.fetch_company_odoo_credential_map"
    )
    @patch("facturia_matching.odoo.empresa_profile.resolve_odoo_profile_from_empresa")
    def test_skip_mysql_when_explicit_profile_mismatches(self, mock_map, mock_fetch):
        mock_map.return_value = "default"
        with patch.dict(
            "os.environ",
            {
                "ODOO_BASE_URL_ALIARE": "https://aliare.example",
                "ODOO_USER_ALIARE": "u@aliare",
                "ODOO_API_KEY_ALIARE": "k",
                "ODOO_DB_ALIARE": "aliare-db",
            },
            clear=False,
        ):
            with patch(
                "facturia_matching.odoo.env.resolve_odoo_db_name",
                side_effect=lambda *a, **k: a[1] or "aliare-db",
            ):
                cfg = build_odoo_main_config("aliare", company_id="1")
        self.assertEqual(cfg["credential_source"], "env")
        self.assertIn("aliare", cfg["base_url"])
        mock_fetch.assert_not_called()

    @patch(
        "facturia_matching.persistence.company_erp_credentials.fetch_company_odoo_credential_map",
        return_value=None,
    )
    @patch(
        "facturia_matching.odoo.empresa_profile.resolve_odoo_profile_from_empresa",
        return_value="default",
    )
    def test_fallback_env_when_mysql_empty(self, _mock_map, _mock_fetch):
        with patch.dict(
            "os.environ",
            {
                "ODOO_BASE_URL": "https://dinner-env.odoo.com",
                "ODOO_USER": "env-user",
                "ODOO_PASSWORD": "env-pass",
                "ODOO_DB": "env-db",
            },
            clear=False,
        ):
            with patch(
                "facturia_matching.odoo.env.resolve_odoo_db_name",
                side_effect=lambda *a, **k: a[1] or "env-db",
            ):
                cfg = build_odoo_main_config("default", company_id="1")
        self.assertEqual(cfg["credential_source"], "env")
        self.assertEqual(cfg["base_url"], "https://dinner-env.odoo.com")


class TestListActiveCredentials(unittest.TestCase):
    @patch("facturia_matching.infra.config.get_mysql_connection")
    def test_list_empty_on_connect_error(self, mock_conn):
        mock_conn.side_effect = RuntimeError("no db")
        from facturia_matching.persistence.company_erp_credentials import (
            list_active_company_odoo_credentials,
        )

        self.assertEqual(list_active_company_odoo_credentials(), [])


class TestHealthCredencialesDbRoute(unittest.TestCase):
    @patch("facturia_matching.api.routes.verify_odoo_config_connection")
    @patch(
        "facturia_matching.persistence.company_erp_credentials.list_active_company_odoo_credentials"
    )
    def test_health_credenciales_db_ok(self, mock_list, mock_verify):
        from facturia_matching.api.routes import odoo_health_credenciales_db

        mock_list.return_value = [
            {
                "credential_id": 1,
                "company_id": 1,
                "company_name": "Dinner",
                "provider_name": "Odoo SH/On-premise",
                "name": "Conexión",
                "config": {
                    "ODOO_BASE_URL": "https://dinner-test.odoo.com",
                    "ODOO_DB": "db1",
                    "ODOO_USER_ID": "a@b.com",
                    "ODOO_PASSWORD": "tok",
                    "ODOO_ENDPOINT": "/jsonrpc",
                },
            }
        ]
        mock_verify.return_value = {"ok": True, "auth_uid": 7, "version": {"server_version": "17"}}
        with patch(
            "facturia_matching.odoo.env.resolve_odoo_db_name",
            side_effect=lambda *a, **k: (a[1] or "").strip() or "resolved-db",
        ):
            out = odoo_health_credenciales_db(empresa="1")
        self.assertTrue(out["ok"])
        self.assertEqual(out["company_id"], 1)
        self.assertEqual(out["company_name"], "Dinner")
        self.assertEqual(set(out.keys()), {"ok", "company_id", "company_name"})

    @patch(
        "facturia_matching.persistence.company_erp_credentials.list_active_company_odoo_credentials",
        return_value=[],
    )
    def test_health_credenciales_db_empty(self, _mock_list):
        from facturia_matching.api.routes import odoo_health_credenciales_db

        out = odoo_health_credenciales_db(empresa=None)
        self.assertEqual(set(out.keys()), {"ok", "error"})
        self.assertFalse(out["ok"])
        self.assertIn("No hay credenciales", out["error"])

    @patch("facturia_matching.api.routes.verify_odoo_config_connection")
    @patch(
        "facturia_matching.persistence.company_erp_credentials.list_active_company_odoo_credentials"
    )
    def test_health_credenciales_db_auth_error_minimal(self, mock_list, mock_verify):
        from facturia_matching.api.routes import odoo_health_credenciales_db

        mock_list.return_value = [
            {
                "credential_id": 1,
                "company_id": 1,
                "company_name": "Dinner",
                "provider_name": "Odoo",
                "name": "c",
                "config": {
                    "ODOO_BASE_URL": "https://dinner-test.odoo.com",
                    "ODOO_USER_ID": "a@b.com",
                    "ODOO_PASSWORD": "bad",
                },
            }
        ]
        mock_verify.return_value = {
            "ok": False,
            "error": "No se pudo obtener uid (authenticate falló y no hay uid fijo).",
        }
        with patch(
            "facturia_matching.odoo.env.resolve_odoo_db_name",
            side_effect=lambda *a, **k: "resolved-db",
        ):
            out = odoo_health_credenciales_db(empresa="1")
        self.assertEqual(set(out.keys()), {"ok", "error"})
        self.assertFalse(out["ok"])
        self.assertIn("Dinner:", out["error"])
        self.assertIn("authenticate", out["error"])


class TestHealthCredencialesParamsRoute(unittest.TestCase):
    @patch("facturia_matching.api.routes.verify_odoo_config_connection")
    def test_health_credenciales_ok_from_body(self, mock_verify):
        from facturia_matching.api.routes import odoo_health_credenciales

        mock_verify.return_value = {"ok": True, "uid": 10, "db": "resolved-db"}
        with patch(
            "facturia_matching.odoo.env.resolve_odoo_db_name",
            side_effect=lambda *a, **k: (a[1] or "").strip() or "resolved-db",
        ):
            out = odoo_health_credenciales(
                {
                    "ODOO_BASE_URL": "https://testct.aliare.com.ar",
                    "ODOO_DB": "resolved-db",
                    "ODOO_USER_ID": "a@b.com",
                    "ODOO_PASSWORD": "tok",
                    "company_id": 4,
                }
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["company_id"], 4)
        self.assertEqual(out["db"], "resolved-db")
        self.assertNotIn("uid", out)
        self.assertNotIn("auth_uid", out)
        self.assertNotIn("uid_source", out)
        mock_verify.assert_called_once()

    @patch("facturia_matching.api.routes.verify_odoo_config_connection")
    def test_health_credenciales_nested_config(self, mock_verify):
        from facturia_matching.api.routes import odoo_health_credenciales

        mock_verify.return_value = {"ok": True, "uid": 2, "db": "db1"}
        with patch(
            "facturia_matching.odoo.env.resolve_odoo_db_name",
            side_effect=lambda *a, **k: "db1",
        ):
            out = odoo_health_credenciales(
                {
                    "config": {
                        "ODOO_BASE_URL": "https://dinner-test.odoo.com",
                        "ODOO_USER_ID": "a@b.com",
                        "ODOO_PASSWORD": "tok",
                    }
                }
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["db"], "db1")
        self.assertNotIn("uid", out)

    def test_health_credenciales_empty_body(self):
        from facturia_matching.api.routes import odoo_health_credenciales

        out = odoo_health_credenciales({})
        self.assertEqual(set(out.keys()), {"ok", "error"})
        self.assertFalse(out["ok"])
        self.assertIn("Faltan credenciales", out["error"])

    @patch("facturia_matching.api.routes.verify_odoo_config_connection")
    def test_health_credenciales_auth_error_minimal(self, mock_verify):
        from facturia_matching.api.routes import odoo_health_credenciales

        mock_verify.return_value = {
            "ok": False,
            "error": "No se pudo obtener uid (authenticate falló y no hay uid fijo).",
        }
        with patch(
            "facturia_matching.odoo.env.resolve_odoo_db_name",
            side_effect=lambda *a, **k: "db1",
        ):
            out = odoo_health_credenciales(
                {
                    "ODOO_BASE_URL": "https://dinner-test.odoo.com",
                    "ODOO_USER_ID": "a@b.com",
                    "ODOO_PASSWORD": "bad",
                }
            )
        self.assertEqual(set(out.keys()), {"ok", "error"})
        self.assertFalse(out["ok"])
        self.assertIn("authenticate", out["error"])


if __name__ == "__main__":
    unittest.main()
