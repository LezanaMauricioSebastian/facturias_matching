import unittest
from unittest.mock import patch

from facturia_matching.odoo import env as odoo_env
from facturia_matching.odoo.env import (
    _odoo_db_from_url,
    get_conversion_template_id,
    is_odoo_cloud_flag,
    list_odoo_databases,
    ODOO_TEMPLATE_ID_SUDATA,
    resolve_odoo_db_name,
    resolve_odoo_profile,
    uses_odoo_padron_first,
)
from facturia_matching.odoo.request_context import odoo_profile_context


class TestOdooProfileResolve(unittest.TestCase):
    @patch.object(odoo_env, "FACTURIA_ODOO_PROFILE", "")
    def test_explicit_aliare(self):
        self.assertEqual(resolve_odoo_profile("aliare"), "aliare")

    @patch.object(odoo_env, "FACTURIA_ODOO_PROFILE", "aliare")
    def test_explicit_default_overrides_deploy(self):
        self.assertEqual(resolve_odoo_profile("default"), "default")

    @patch.object(odoo_env, "FACTURIA_ODOO_PROFILE", "aliare")
    def test_no_profile_keeps_aliare_deploy_compat(self):
        self.assertEqual(resolve_odoo_profile(None), "aliare")

    @patch.object(odoo_env, "FACTURIA_ODOO_PROFILE", "")
    def test_empresa_does_not_select_profile(self):
        self.assertEqual(resolve_odoo_profile("8"), "default")
        self.assertEqual(resolve_odoo_profile("1"), "default")

    def test_context_profile(self):
        with odoo_profile_context("aliare"):
            self.assertEqual(resolve_odoo_profile(), "aliare")

    @patch.object(odoo_env, "FACTURIA_ODOO_PROFILE", "")
    def test_explicit_sudata(self):
        self.assertEqual(resolve_odoo_profile("sudata"), "sudata")

    @patch.object(odoo_env, "FACTURIA_ODOO_PROFILE", "sudata")
    def test_explicit_default_overrides_sudata_deploy(self):
        self.assertEqual(resolve_odoo_profile("default"), "default")

    @patch.object(odoo_env, "FACTURIA_ODOO_PROFILE", "sudata")
    def test_no_profile_keeps_sudata_deploy(self):
        self.assertEqual(resolve_odoo_profile(None), "sudata")

    @patch.object(odoo_env, "FACTURIA_ODOO_PROFILE", "sudata")
    def test_sudata_conversion_template(self):
        self.assertEqual(get_conversion_template_id("sudata"), ODOO_TEMPLATE_ID_SUDATA)

    def test_is_odoo_cloud_flag(self):
        self.assertTrue(is_odoo_cloud_flag("1"))
        self.assertTrue(is_odoo_cloud_flag("true"))
        self.assertFalse(is_odoo_cloud_flag("0"))
        self.assertFalse(is_odoo_cloud_flag(""))

    @patch.object(odoo_env, "FACTURIA_ODOO_PROFILE", "")
    def test_uses_odoo_padron_first(self):
        self.assertTrue(uses_odoo_padron_first("sudata"))
        self.assertTrue(uses_odoo_padron_first("aliare"))
        self.assertFalse(uses_odoo_padron_first("default"))

    def test_context_sudata_profile(self):
        with odoo_profile_context("sudata"):
            self.assertEqual(resolve_odoo_profile(), "sudata")


class TestOdooDbResolve(unittest.TestCase):
    def test_explicit_configured(self):
        self.assertEqual(
            resolve_odoo_db_name("https://foo.odoo.com", "mydb"),
            "mydb",
        )

    def test_db_from_url_hostname(self):
        self.assertEqual(
            _odoo_db_from_url("https://staging-ejtngefwqs.cloudpepper.site"),
            "staging-ejtngefwqs.cloudpepper.site",
        )

    @patch("facturia_matching.odoo.env.list_odoo_databases")
    def test_single_db_from_list(self, mock_list):
        mock_list.return_value = ["only_one"]
        self.assertEqual(
            resolve_odoo_db_name("https://example.com", ""),
            "only_one",
        )

    @patch("facturia_matching.odoo.env.list_odoo_databases")
    @patch("facturia_matching.odoo.env._odoo_db_exists")
    def test_multiple_dbs_skips_bad_hostname(self, mock_exists, mock_list):
        mock_list.return_value = ["db_a", "db_b"]
        mock_exists.return_value = False
        self.assertEqual(
            resolve_odoo_db_name("https://tenant.odoo.com", ""),
            "",
        )

    @patch("facturia_matching.odoo.env._odoo_auth_ok")
    @patch("facturia_matching.odoo.env.list_odoo_databases")
    def test_multiple_dbs_auth_picks_valid(self, mock_list, mock_auth):
        mock_list.return_value = ["db_a", "db_b"]
        mock_auth.side_effect = lambda _b, db, *_: db == "db_b"
        self.assertEqual(
            resolve_odoo_db_name(
                "https://tenant.odoo.com",
                "",
                login="u",
                password="p",
            ),
            "db_b",
        )

    @patch("facturia_matching.odoo.env._odoo_auth_ok")
    @patch("facturia_matching.odoo.env._odoo_db_exists")
    @patch("facturia_matching.odoo.env.list_odoo_databases")
    def test_hostname_auth_when_db_exist_denied(self, mock_list, mock_exists, mock_auth):
        mock_list.return_value = []
        mock_exists.return_value = False
        mock_auth.return_value = True
        self.assertEqual(
            resolve_odoo_db_name(
                "https://staging-ejtngefwqs.cloudpepper.site",
                "",
                login="u",
                password="p",
            ),
            "staging-ejtngefwqs.cloudpepper.site",
        )

    @patch("facturia_matching.odoo.env.xmlrpc.client.ServerProxy")
    def test_list_odoo_databases(self, mock_proxy):
        mock_proxy.return_value.list.return_value = ["x"]
        self.assertEqual(list_odoo_databases("https://odoo.example.com"), ["x"])
        mock_proxy.assert_called_once()
        self.assertIn("/xmlrpc/2/db", mock_proxy.call_args[0][0])

    @patch("facturia_matching.odoo.env.list_odoo_databases_web")
    @patch("facturia_matching.odoo.env.xmlrpc.client.ServerProxy")
    def test_list_odoo_databases_web_fallback(self, mock_proxy, mock_web):
        mock_proxy.return_value.list.side_effect = Exception("Access Denied")
        mock_web.return_value = ["dinner-test-34416236"]
        self.assertEqual(
            list_odoo_databases("https://dinner-test.odoo.com"),
            ["dinner-test-34416236"],
        )

    @patch("facturia_matching.odoo.env._odoo_db_exists")
    @patch("facturia_matching.odoo.env.list_odoo_databases")
    def test_stale_explicit_db_falls_back_to_list(self, mock_list, mock_exists):
        mock_exists.return_value = False
        mock_list.return_value = ["dinner-test-34416236"]
        self.assertEqual(
            resolve_odoo_db_name(
                "https://dinner-test.odoo.com",
                "dinner-test-33873862",
                login="u",
                password="p",
            ),
            "dinner-test-34416236",
        )


if __name__ == "__main__":
    unittest.main()
