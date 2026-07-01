"""Unit tests: cliente Odoo (contexto de idioma)."""
import unittest

from facturia_matching.odoo.api import _merge_odoo_call_kwargs


class TestOdooLangContext(unittest.TestCase):
    def test_adds_es_ar_by_default(self):
        kw = _merge_odoo_call_kwargs({"fields": ["name"]})
        self.assertEqual(kw["context"]["lang"], "es_AR")

    def test_respects_explicit_lang(self):
        kw = _merge_odoo_call_kwargs({"context": {"lang": "en_US"}})
        self.assertEqual(kw["context"]["lang"], "en_US")

    def test_merges_with_existing_context(self):
        kw = _merge_odoo_call_kwargs({"context": {"active_test": False}})
        self.assertEqual(kw["context"]["lang"], "es_AR")
        self.assertIs(kw["context"]["active_test"], False)


if __name__ == "__main__":
    unittest.main()
