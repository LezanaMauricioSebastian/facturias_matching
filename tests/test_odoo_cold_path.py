"""Tests: cold-path performance helpers (catalog single-flight, tax cache, uid, PO limit)."""
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from facturia_matching.odoo import catalog as catalog_mod
from facturia_matching.odoo.api import clear_odoo_uid_cache, get_odoo_uid_from_config
from facturia_matching.odoo.request_context import (
    odoo_profile_context,
    reset_tax_cache_scope,
)
from facturia_matching.padron.taxes import clear_odoo_tax_catalog_cache


class TestCatalogSingleFlight(unittest.TestCase):
    def setUp(self):
        catalog_mod.invalidate_catalog_cache()
        catalog_mod._cache_by_profile.clear()

    def tearDown(self):
        catalog_mod.invalidate_catalog_cache()
        catalog_mod._cache_by_profile.clear()

    def test_parallel_get_catalog_fetches_once(self):
        config = {
            "base_url": "https://odoo.test",
            "db": "db",
            "password": "x",
            "uid": 2,
            "login": "",
        }
        raw = {
            "journals": [],
            "document_types": [],
            "proveedores": [],
            "cuentas": [],
            "rubros": [],
            "productos": [],
        }
        fetch_count = {"n": 0}
        gate = threading.Event()

        def slow_fetch(_cfg, _profile):
            fetch_count["n"] += 1
            gate.wait(timeout=2)
            time.sleep(0.05)
            return raw

        results = []

        def caller():
            cat, ok = catalog_mod.get_catalog(profile="default")
            results.append((cat is not None, ok))

        with patch(
            "facturia_matching.odoo.catalog.get_odoo_main_config", return_value=config
        ), patch(
            "facturia_matching.odoo.catalog.is_odoo_config_ready", return_value=True
        ), patch(
            "facturia_matching.odoo.catalog.get_odoo_uid_from_config", return_value=2
        ), patch(
            "facturia_matching.odoo.catalog.probe_odoo_db_exists",
            return_value=(True, None, None),
        ), patch(
            "facturia_matching.odoo.catalog._fetch_catalog_raw", side_effect=slow_fetch
        ), patch(
            "facturia_matching.odoo.catalog.current_odoo_profile", return_value="default"
        ):
            t1 = threading.Thread(target=caller)
            t2 = threading.Thread(target=caller)
            t1.start()
            t2.start()
            time.sleep(0.05)
            gate.set()
            t1.join(timeout=5)
            t2.join(timeout=5)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(ok for _, ok in results))
        self.assertEqual(fetch_count["n"], 1)


class TestTaxCacheScope(unittest.TestCase):
    def setUp(self):
        clear_odoo_tax_catalog_cache()
        reset_tax_cache_scope()

    def tearDown(self):
        clear_odoo_tax_catalog_cache()
        reset_tax_cache_scope()

    def test_repeated_context_reuses_tax_cache_globals(self):
        from facturia_matching.padron import taxes

        sentinel = {1: "IVA 21"}
        with odoo_profile_context("default"):
            taxes._TAX_NAME_BY_ID = sentinel
        with odoo_profile_context("default"):
            self.assertIs(taxes._TAX_NAME_BY_ID, sentinel)
        with odoo_profile_context("sudata"):
            self.assertIsNone(taxes._TAX_NAME_BY_ID)


class TestUidCache(unittest.TestCase):
    def setUp(self):
        clear_odoo_uid_cache()

    def tearDown(self):
        clear_odoo_uid_cache()

    def test_authenticate_cached_per_login(self):
        config = {
            "base_url": "https://odoo.test",
            "db": "db1",
            "password": "secret",
            "login": "user@example.com",
        }
        common = MagicMock()
        common.authenticate.return_value = 42
        with patch(
            "facturia_matching.odoo.api.xmlrpc.client.ServerProxy", return_value=common
        ):
            self.assertEqual(get_odoo_uid_from_config(config), 42)
            self.assertEqual(get_odoo_uid_from_config(config), 42)
        self.assertEqual(common.authenticate.call_count, 1)


class TestPoEnrichLimit(unittest.TestCase):
    def test_limit_helper_unlimited_when_candidates_or_saved(self):
        from facturia_matching.odoo.purchase_matching.match import (
            _po_order_limit_for_enrich,
        )

        self.assertIsNone(
            _po_order_limit_for_enrich(fetch_candidates=True, saved_oid=None)
        )
        self.assertIsNone(
            _po_order_limit_for_enrich(fetch_candidates=False, saved_oid=99)
        )
        with patch(
            "facturia_matching.infra.config.ODOO_PO_ENRICH_ORDER_LIMIT", 100
        ):
            # Import path reads config inside function
            lim = _po_order_limit_for_enrich(fetch_candidates=False, saved_oid=None)
        self.assertEqual(lim, 100)

    def test_header_only_cold_uses_has_pos_not_full_fetch(self):
        from facturia_matching.odoo.purchase_matching import enrich_rows_with_purchase_data
        from facturia_matching.odoo.purchase_matching import match as match_mod

        rows = [
            {
                "__comprobante_idx": 0,
                "partner_id": "10",
                "invoice_line_ids/name": "",
            }
        ]
        with patch.object(
            match_mod, "_pkg"
        ) as pkg, patch(
            "facturia_matching.odoo.purchase_matching.match.partner_has_confirmed_pos",
            return_value=True,
        ) as has_pos, patch.object(
            match_mod, "_fetch_partner_lines_for_enrich"
        ) as fetch_lines:
            pkg.return_value.is_purchase_odoo_configured.return_value = True
            pkg.return_value.get_uom_catalog.return_value = {"by_id": {}, "by_name": {}}
            summary = enrich_rows_with_purchase_data(rows, fetch_candidates=False)
        has_pos.assert_called_once_with(10)
        fetch_lines.assert_not_called()
        self.assertTrue(summary["oc_provider_has_ocs_by_comprobante"]["0"])


if __name__ == "__main__":
    unittest.main()
