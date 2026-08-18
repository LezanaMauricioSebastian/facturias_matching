"""Unit tests: cliente Odoo (contexto de idioma) y elección de idioma por tenant."""
import unittest
from unittest.mock import patch

from facturia_matching.odoo.api import _merge_odoo_call_kwargs
from facturia_matching.odoo.env import clear_odoo_lang_cache, resolve_odoo_lang
from facturia_matching.odoo.request_context import odoo_profile_context

# Idiomas activos por tenant real: Aliare/Dinner tienen es_AR; Sudata Cloud solo es_419.
ALIARE_LANGS = ("en_US", "es_AR", "es_ES")
SUDATA_LANGS = ("en_US", "es_419")


def _patch_active_langs(codes):
    return patch("facturia_matching.odoo.env._active_lang_codes", return_value=tuple(codes))


class TestOdooLangContext(unittest.TestCase):
    def setUp(self):
        clear_odoo_lang_cache()

    def tearDown(self):
        clear_odoo_lang_cache()

    def test_adds_es_ar_by_default(self):
        with _patch_active_langs(ALIARE_LANGS), odoo_profile_context("default"):
            kw = _merge_odoo_call_kwargs({"fields": ["name"]})
        self.assertEqual(kw["context"]["lang"], "es_AR")

    def test_respects_explicit_lang(self):
        with _patch_active_langs(ALIARE_LANGS), odoo_profile_context("default"):
            kw = _merge_odoo_call_kwargs({"context": {"lang": "en_US"}})
        self.assertEqual(kw["context"]["lang"], "en_US")

    def test_merges_with_existing_context(self):
        with _patch_active_langs(ALIARE_LANGS), odoo_profile_context("default"):
            kw = _merge_odoo_call_kwargs({"context": {"active_test": False}})
        self.assertEqual(kw["context"]["lang"], "es_AR")
        self.assertIs(kw["context"]["active_test"], False)

    def test_sudata_falls_back_to_es_419(self):
        """Sudata no tiene es_AR instalado; sin lang el catálogo llega en inglés."""
        with _patch_active_langs(SUDATA_LANGS), odoo_profile_context("sudata"):
            kw = _merge_odoo_call_kwargs({"fields": ["name"]})
        self.assertEqual(kw["context"]["lang"], "es_419")

    def test_prefers_es_ar_over_es_419_when_both_installed(self):
        with _patch_active_langs(("en_US", "es_419", "es_AR")), odoo_profile_context("sudata"):
            self.assertEqual(resolve_odoo_lang("sudata"), "es_AR")

    def test_sudata_without_spanish_sends_no_lang(self):
        with _patch_active_langs(("en_US",)), odoo_profile_context("sudata"):
            kw = _merge_odoo_call_kwargs({"fields": ["name"]})
        self.assertNotIn("context", kw)

    def test_unreachable_tenant_keeps_previous_defaults(self):
        with _patch_active_langs(()):
            with odoo_profile_context("default"):
                self.assertEqual(resolve_odoo_lang("default"), "es_AR")
            with odoo_profile_context("sudata"):
                self.assertEqual(resolve_odoo_lang("sudata"), "")

    def test_env_override_wins_over_detection(self):
        with _patch_active_langs(SUDATA_LANGS), patch(
            "facturia_matching.odoo.env._env_odoo_lang", return_value="es_AR"
        ), odoo_profile_context("sudata"):
            self.assertEqual(resolve_odoo_lang("sudata"), "es_AR")

    def test_lang_probe_runs_once_per_tenant(self):
        with patch(
            "facturia_matching.odoo.env._active_lang_codes",
            return_value=SUDATA_LANGS,
        ) as probe, odoo_profile_context("sudata"):
            resolve_odoo_lang("sudata")
            resolve_odoo_lang("sudata")
            resolve_odoo_lang("sudata")
        self.assertEqual(probe.call_count, 1)


if __name__ == "__main__":
    unittest.main()
