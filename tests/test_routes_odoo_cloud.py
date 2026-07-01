import unittest

from facturia_matching.api.routes import _resolve_request_odoo_profile
from facturia_matching.odoo.env import resolve_odoo_profile
from facturia_matching.odoo.request_context import odoo_profile_context


class TestResolveRequestOdooProfile(unittest.TestCase):
    def test_odoo_cloud_query_selects_sudata(self):
        self.assertEqual(_resolve_request_odoo_profile(odoo_cloud="1"), "sudata")

    def test_odoo_cloud_body_selects_sudata(self):
        self.assertEqual(
            _resolve_request_odoo_profile(payload={"odoo_cloud": "1"}),
            "sudata",
        )

    def test_odoo_profile_explicit_over_query_cloud_when_in_body(self):
        self.assertEqual(
            _resolve_request_odoo_profile(
                odoo_cloud="1",
                payload={"odoo_profile": "aliare"},
            ),
            "aliare",
        )

    def test_perfil_query_when_no_cloud(self):
        self.assertEqual(_resolve_request_odoo_profile(perfil="sudata"), "sudata")

    def test_context_after_resolve(self):
        profile = _resolve_request_odoo_profile(odoo_cloud="1")
        with odoo_profile_context(profile):
            self.assertEqual(resolve_odoo_profile(), "sudata")


if __name__ == "__main__":
    unittest.main()
