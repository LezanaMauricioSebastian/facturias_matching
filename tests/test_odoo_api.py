"""Unit tests: cliente Odoo (contexto de idioma)."""
import unittest

from facturia_matching.odoo.api import _merge_odoo_call_kwargs
from facturia_matching.odoo.request_context import odoo_profile_context


class TestOdooLangContext(unittest.TestCase):
    def test_adds_es_ar_by_default(self):
        with odoo_profile_context("default"):
            kw = _merge_odoo_call_kwargs({"fields": ["name"]})
        self.assertEqual(kw["context"]["lang"], "es_AR")

    def test_sudata_skips_lang_by_default(self):
        with odoo_profile_context("sudata"):
            kw = _merge_odoo_call_kwargs({"fields": ["name"]})
        self.assertNotIn("context", kw)

    def test_respects_explicit_lang(self):
        with odoo_profile_context("default"):
            kw = _merge_odoo_call_kwargs({"context": {"lang": "en_US"}})
        self.assertEqual(kw["context"]["lang"], "en_US")

    def test_merges_with_existing_context(self):
        with odoo_profile_context("default"):
            kw = _merge_odoo_call_kwargs({"context": {"active_test": False}})
        self.assertEqual(kw["context"]["lang"], "es_AR")
        self.assertIs(kw["context"]["active_test"], False)


if __name__ == "__main__":
    unittest.main()
