"""Tests: resolución de etiquetas IIBB UI → account.tax id Odoo."""
import unittest
from unittest.mock import patch

from facturia_matching.odoo_import import collect_expected_tax_amounts_from_group
from facturia_matching.padron_taxes import _label_key, _resolve_iibb_label_to_id


def _by_name(*pairs):
    return {_label_key(name): tid for name, tid in pairs}


class TestIibbLabelResolution(unittest.TestCase):
    def test_arba_does_not_match_caba_when_ba_missing(self):
        by_name = _by_name(("P. IIBB CABA", 1), ("P. IIBB C", 5), ("P. IIBB CHO", 16))
        tid = _resolve_iibb_label_to_id("Percepción IIBB ARBA Sufrida", by_name)
        self.assertIsNone(tid)

    def test_arba_matches_p_iibb_ba(self):
        by_name = _by_name(("P. IIBB CABA", 1), ("P. IIBB BA", 2))
        tid = _resolve_iibb_label_to_id("Percepción IIBB ARBA Sufrida", by_name)
        self.assertEqual(tid, 2)

    def test_caba_still_resolves(self):
        by_name = _by_name(("P. IIBB CABA", 1), ("P. IIBB BA", 2))
        tid = _resolve_iibb_label_to_id("Percepción IIBB CABA Sufrida", by_name)
        self.assertEqual(tid, 1)

    def test_corrientes_suffix_c_not_caba(self):
        by_name = _by_name(("P. IIBB CABA", 1), ("P. IIBB C", 5))
        tid = _resolve_iibb_label_to_id("Percepción IIBB Corrientes Sufrida", by_name)
        self.assertEqual(tid, 5)

    def test_chaco_suffix_cho(self):
        by_name = _by_name(("P. IIBB CHO", 16), ("P. IIBB BA", 2))
        tid = _resolve_iibb_label_to_id("Percepción IIBB Chaco Sufrida", by_name)
        self.assertEqual(tid, 16)

    def test_collect_expected_maps_arba_monto_to_ba_tax(self):
        by_name = {1: "P. IIBB CABA", 2: "P. IIBB BA", 63: "IVA 21%"}
        id_by_name = _by_name(("P. IIBB CABA", 1), ("P. IIBB BA", 2), ("IVA 21%", 63))
        rows = [
            {
                "iva_pct": "21",
                "iva_monto": "57255,38",
                "otros_impuestos": "Percepción IIBB ARBA Sufrida",
                "otros_impuestos_monto": "3271,74",
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/price_unit": "272644,68",
            }
        ]
        with patch("facturia_matching.padron_taxes.get_tax_id_by_name", return_value=id_by_name):
            with patch("facturia_matching.padron_taxes.get_tax_name_by_id", return_value=by_name):
                amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertEqual(amounts.get(2), 3271.74)
        self.assertNotIn(1, amounts)


if __name__ == "__main__":
    unittest.main()
