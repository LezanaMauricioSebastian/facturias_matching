"""Catálogo Odoo: dominio de partners por perfil + paginación."""

import unittest
from unittest.mock import patch

from facturia_matching.odoo.catalog import (
    _fetch_partners_for_catalog,
    _merge_partners_by_id,
    _partner_catalog_domain,
    _search_partners_paginated,
)


class TestPartnerCatalogDomain(unittest.TestCase):
    def test_aliare_loads_all_contacts(self):
        self.assertEqual(_partner_catalog_domain("aliare"), [])

    def test_default_filters_suppliers(self):
        self.assertEqual(_partner_catalog_domain("default"), [("supplier_rank", ">", 0)])

    def test_sudata_filters_suppliers(self):
        self.assertEqual(_partner_catalog_domain("sudata"), [("supplier_rank", ">", 0)])


class TestPartnerCatalogPagination(unittest.TestCase):
    def test_merge_partners_by_id(self):
        a = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
        b = [{"id": 2, "name": "B2"}, {"id": 3, "name": "C"}]
        merged = _merge_partners_by_id(a, b)
        by_id = {r["id"]: r for r in merged}
        self.assertEqual(set(by_id), {1, 2, 3})
        self.assertEqual(by_id[2]["name"], "B2")

    def test_search_partners_paginated_walks_offsets(self):
        pages = {
            0: [{"id": i, "name": f"P{i}"} for i in range(1, 6)],
            5: [{"id": i, "name": f"P{i}"} for i in range(6, 9)],
        }

        def fake_search_read(model, domain, fields, limit=500, order=None, offset=None, config=None):
            self.assertEqual(model, "res.partner")
            self.assertEqual(order, "id")
            # domain ends with ("id", ">", last_id)
            last = 0
            for term in domain:
                if isinstance(term, (list, tuple)) and len(term) == 3 and term[0] == "id" and term[1] == ">":
                    last = int(term[2])
            return pages.get(last, [])

        with patch("facturia_matching.odoo.catalog.odoo_search_read", side_effect=fake_search_read):
            rows = _search_partners_paginated({"x": 1}, [], page_size=5, max_rows=100)
        self.assertEqual([r["id"] for r in rows], list(range(1, 9)))

    def test_aliare_skips_suppliers_when_contacts_complete(self):
        calls = []

        def fake_paginated(config, domain, page_size=5000, max_rows=100_000):
            calls.append(list(domain))
            if domain == []:
                return [{"id": 1, "name": "Contacto"}]
            if domain == [("supplier_rank", ">", 0)]:
                return [{"id": 99, "name": "GORDON DAN ALAN", "vat": "20413168091"}]
            return []

        with patch(
            "facturia_matching.odoo.catalog._search_partners_paginated",
            side_effect=fake_paginated,
        ):
            rows = _fetch_partners_for_catalog({}, "aliare")
        self.assertEqual([r["id"] for r in rows], [1])
        self.assertEqual(calls, [[]])

    def test_aliare_merges_suppliers_when_contacts_truncated(self):
        from facturia_matching.odoo import catalog as catalog_mod

        with patch.object(catalog_mod, "_PARTNER_FETCH_MAX", 3):

            def fake_paginated(config, domain, page_size=5000, max_rows=100_000):
                if domain == []:
                    return [{"id": i, "name": f"C{i}"} for i in range(1, 4)]  # len == max
                if domain == [("supplier_rank", ">", 0)]:
                    return [{"id": 99, "name": "GORDON DAN ALAN", "vat": "20413168091"}]
                return []

            with patch(
                "facturia_matching.odoo.catalog._search_partners_paginated",
                side_effect=fake_paginated,
            ):
                rows = _fetch_partners_for_catalog({}, "aliare")
        ids = {r["id"] for r in rows}
        self.assertEqual(ids, {1, 2, 3, 99})

    @patch("facturia_matching.odoo.catalog.odoo_search_read")
    @patch("facturia_matching.odoo.catalog.get_odoo_uid_from_config", return_value=2)
    @patch("facturia_matching.odoo.catalog.is_odoo_config_ready", return_value=True)
    @patch("facturia_matching.odoo.catalog.get_odoo_main_config", return_value={"db": "x"})
    @patch("facturia_matching.odoo.catalog.current_odoo_profile", return_value="aliare")
    def test_search_partners_by_query_tokens(self, *_mocks):
        from facturia_matching.odoo.catalog import search_partners_by_query

        captured = {}

        def fake_sr(model, domain, fields, limit=50, order=None, config=None, offset=None):
            captured["domain"] = domain
            return [{"id": 7, "name": "GORDON DAN ALAN", "vat": "20-41316809-1"}]

        with patch("facturia_matching.odoo.catalog.odoo_search_read", side_effect=fake_sr):
            rows = search_partners_by_query("dan alan")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "GORDON DAN ALAN")
        self.assertIn("&", captured["domain"])
        self.assertTrue(any(t[0] == "name" and t[2] == "dan" for t in captured["domain"] if isinstance(t, tuple)))


if __name__ == "__main__":
    unittest.main()
