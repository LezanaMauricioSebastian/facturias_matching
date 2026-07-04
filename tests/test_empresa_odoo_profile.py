import unittest
from unittest.mock import patch

from facturia_matching.api.routes import _resolve_request_odoo_profile
from facturia_matching.odoo.empresa_profile import (
    empresa_odoo_profile_map,
    resolve_odoo_display_label,
    resolve_odoo_profile_from_empresa,
)


class TestEmpresaOdooProfileMap(unittest.TestCase):
    @patch("facturia_matching.odoo.empresa_profile.resolve_process_schema")
    def test_prod_map(self, mock_schema):
        mock_schema.return_value = "sudataco_facturia"
        m = empresa_odoo_profile_map()
        self.assertEqual(m["1"], "default")
        self.assertEqual(m["4"], "aliare")
        self.assertEqual(m["7"], "sudata")

    @patch("facturia_matching.odoo.empresa_profile.resolve_process_schema")
    def test_staging_map(self, mock_schema):
        mock_schema.return_value = "sudataco_staging"
        m = empresa_odoo_profile_map()
        self.assertEqual(m["1"], "default")
        self.assertEqual(m["3"], "sudata")
        self.assertNotIn("4", m)

    @patch("facturia_matching.odoo.empresa_profile._env_strip")
    def test_env_override(self, mock_env):
        mock_env.return_value = "1=default,9=aliare"
        m = empresa_odoo_profile_map()
        self.assertEqual(m["1"], "default")
        self.assertEqual(m["9"], "aliare")

    @patch("facturia_matching.odoo.empresa_profile.resolve_process_schema")
    def test_resolve_from_empresa(self, mock_schema):
        mock_schema.return_value = "sudataco_facturia"
        self.assertEqual(resolve_odoo_profile_from_empresa("4"), "aliare")
        self.assertIsNone(resolve_odoo_profile_from_empresa("99"))
        self.assertIsNone(resolve_odoo_profile_from_empresa(""))


class TestResolveRequestOdooProfileEmpresa(unittest.TestCase):
    @patch("facturia_matching.odoo.empresa_profile.resolve_process_schema")
    def test_empresa_selects_aliare_when_no_explicit_profile(self, mock_schema):
        mock_schema.return_value = "sudataco_facturia"
        self.assertEqual(
            _resolve_request_odoo_profile(empresa="4"),
            "aliare",
        )

    @patch("facturia_matching.odoo.empresa_profile.resolve_process_schema")
    def test_empresa_selects_sudata_staging(self, mock_schema):
        mock_schema.return_value = "sudataco_staging"
        self.assertEqual(
            _resolve_request_odoo_profile(empresa="3"),
            "sudata",
        )

    @patch("facturia_matching.odoo.empresa_profile.resolve_process_schema")
    def test_explicit_profile_overrides_empresa(self, mock_schema):
        mock_schema.return_value = "sudataco_facturia"
        self.assertEqual(
            _resolve_request_odoo_profile(perfil="sudata", empresa="1"),
            "sudata",
        )

    @patch("facturia_matching.odoo.empresa_profile.resolve_process_schema")
    def test_empresa_from_body(self, mock_schema):
        mock_schema.return_value = "sudataco_facturia"
        self.assertEqual(
            _resolve_request_odoo_profile(payload={"empresa": "7"}),
            "sudata",
        )

    @patch("facturia_matching.odoo.empresa_profile.resolve_process_schema")
    def test_explicit_profile_overrides_empresa(self, mock_schema):
        mock_schema.return_value = "sudataco_staging"
        self.assertEqual(
            _resolve_request_odoo_profile(perfil="aliare", empresa="1"),
            "aliare",
        )
        self.assertEqual(
            _resolve_request_odoo_profile(odoo_profile_q="aliare", empresa="1"),
            "aliare",
        )

    @patch("facturia_matching.odoo.empresa_profile.resolve_process_schema")
    def test_dinner_empresa_returns_default(self, mock_schema):
        mock_schema.return_value = "sudataco_facturia"
        self.assertEqual(
            _resolve_request_odoo_profile(empresa="1"),
            "default",
        )

    @patch("facturia_matching.odoo.empresa_profile.empresa_odoo_display_labels")
    def test_display_label_from_empresa(self, mock_labels):
        mock_labels.return_value = {"5": "Odoo Central Ticket"}
        self.assertEqual(resolve_odoo_display_label("5", "aliare"), "Odoo Central Ticket")

    @patch("facturia_matching.odoo.empresa_profile.empresa_odoo_display_labels")
    def test_display_label_fallback_profile(self, mock_labels):
        mock_labels.return_value = {}
        self.assertEqual(resolve_odoo_display_label("", "sudata"), "Odoo Sudata")


if __name__ == "__main__":
    unittest.main()
