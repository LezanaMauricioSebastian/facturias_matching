"""Tests for partner header memory (journal/account/rubro from past conversions)."""

import unittest
from unittest.mock import patch

from facturia_matching.persistence.partner_header_memory import (
    HeaderChoice,
    apply_learned_header_ids,
    build_header_index_for_company,
    build_header_index_from_row_lists,
    catalog_contains_id,
    extract_header_choice,
    invalidate_header_index_cache,
    lookup_header,
)


def _row(
    *,
    partner_id="",
    journal_id="",
    account_id="",
    rubro_id="",
    comp=0,
):
    return {
        "partner_id": partner_id,
        "journal_id": journal_id,
        "invoice_line_ids/account_id": account_id,
        "x_studio_category": rubro_id,
        "__comprobante_idx": comp,
    }


class TestPartnerHeaderMemory(unittest.TestCase):
    def tearDown(self):
        invalidate_header_index_cache()

    def test_extract_header_from_comprobante_rows(self):
        rows = [
            _row(partner_id="1582", journal_id="21", account_id="147", rubro_id=""),
            _row(comp=0),  # misma factura, sin partner en filas siguientes
        ]
        extracted = extract_header_choice(rows)
        self.assertIsNotNone(extracted)
        partner_id, choice = extracted
        self.assertEqual(partner_id, 1582)
        self.assertEqual(choice.journal_id, "21")
        self.assertEqual(choice.account_id, "147")
        self.assertEqual(choice.rubro_id, "")

    def test_index_prefers_most_recent_conversion(self):
        older = [
            _row(partner_id="10", journal_id="22", account_id="100", comp=0),
        ]
        newer = [
            _row(partner_id="10", journal_id="21", account_id="147", comp=0),
        ]
        # Listas más recientes primero.
        index = build_header_index_from_row_lists([newer, older])
        choice = lookup_header(index, 10)
        self.assertEqual(choice, HeaderChoice(journal_id="21", account_id="147"))

    def test_index_keeps_first_partner_across_comprobantes(self):
        rows = [
            _row(partner_id="1", journal_id="21", comp=0),
            _row(partner_id="2", journal_id="22", comp=1),
        ]
        index = build_header_index_from_row_lists([rows])
        self.assertEqual(lookup_header(index, 1).journal_id, "21")
        self.assertEqual(lookup_header(index, 2).journal_id, "22")

    def test_catalog_contains_id(self):
        journals = [{"id": 21, "name": "FP Resistencia Libertad"}, {"id": 22, "name": "FP Corrientes"}]
        self.assertTrue(catalog_contains_id(journals, "21"))
        self.assertTrue(catalog_contains_id(journals, 21))
        self.assertFalse(catalog_contains_id(journals, "99"))
        self.assertFalse(catalog_contains_id(journals, ""))

    def test_apply_learned_overrides_padron_when_in_catalog(self):
        index = {1582: HeaderChoice(journal_id="21", account_id="147", rubro_id="5")}
        journals = [{"id": 21, "name": "FP Resistencia Libertad"}, {"id": 22, "name": "FP Centenario"}]
        cuentas = [{"id": 147, "name": "Compra"}, {"id": 100, "name": "Otra"}]
        rubros = [{"id": 5, "name": "Bebidas"}]
        j, a, r = apply_learned_header_ids(
            partner_id="1582",
            journal_id="22",
            account_id="100",
            rubro_id="9",
            header_index=index,
            journals=journals,
            cuentas=cuentas,
            rubros=rubros,
            supports_rubro=True,
        )
        self.assertEqual((j, a, r), ("21", "147", "5"))

    def test_apply_learned_keeps_padron_when_stale_id(self):
        index = {1582: HeaderChoice(journal_id="999", account_id="888")}
        journals = [{"id": 22, "name": "FP Centenario"}]
        cuentas = [{"id": 100, "name": "Otra"}]
        j, a, r = apply_learned_header_ids(
            partner_id="1582",
            journal_id="22",
            account_id="100",
            rubro_id="",
            header_index=index,
            journals=journals,
            cuentas=cuentas,
            rubros=[],
            supports_rubro=False,
        )
        self.assertEqual(j, "22")
        self.assertEqual(a, "100")
        self.assertEqual(r, "")

    def test_apply_learned_skips_rubro_when_unsupported(self):
        index = {1: HeaderChoice(journal_id="21", rubro_id="5")}
        journals = [{"id": 21, "name": "FP"}]
        j, a, r = apply_learned_header_ids(
            partner_id=1,
            journal_id="22",
            account_id="",
            rubro_id="",
            header_index=index,
            journals=journals,
            cuentas=[],
            rubros=[{"id": 5, "name": "X"}],
            supports_rubro=False,
        )
        self.assertEqual(j, "21")
        self.assertEqual(r, "")

    def test_build_header_index_for_company_uses_payloads_and_cache(self):
        payloads = [
            {
                "process_id": 240,
                "conversion_id": 1,
                "rows": [
                    _row(partner_id="1582", journal_id="21", account_id="147"),
                ],
            }
        ]
        with patch(
            "facturia_matching.persistence.partner_header_memory.fetch_recent_conversion_row_lists",
            return_value=payloads,
        ) as fetch:
            with patch(
                "facturia_matching.persistence.partner_header_memory.get_conversion_template_id",
                return_value=1,
            ):
                idx1 = build_header_index_for_company(1)
                self.assertEqual(lookup_header(idx1, 1582).journal_id, "21")
                idx2 = build_header_index_for_company(1)
                self.assertIs(idx1, idx2)
                fetch.assert_called_once()

                invalidate_header_index_cache(1, template_id=1)
                build_header_index_for_company(1)
                self.assertEqual(fetch.call_count, 2)


if __name__ == "__main__":
    unittest.main()
