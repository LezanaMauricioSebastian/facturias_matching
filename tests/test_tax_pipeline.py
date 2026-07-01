"""Pipeline end-to-end: clasificación → totales → import Odoo."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from facturia_matching.core.comprobante_tax import (
    classify_comprobante_tax_mode,
    compute_comprobante_totals,
    fac_iva_montos,
    sum_otros_impuestos,
)
from facturia_matching.core.process import backfill_fac_iva_montos_from_process
from facturia_matching.odoo.import_ import collect_expected_tax_amounts_from_group
from tax_fixtures import load_tax_scenarios, scenario_by_id

ALIARE_IVA_TAXES = [
    {"id": 55, "name": "IVA No Corresp", "amount": 0.0},
    {"id": 63, "name": "IVA 10.5%", "amount": 10.5},
    {"id": 65, "name": "IVA 21%", "amount": 21.0},
]


class TestTaxScenarioFixtures(unittest.TestCase):
    def test_all_fixture_modes(self):
        for scenario in load_tax_scenarios():
            with self.subTest(scenario=scenario["id"]):
                rows = scenario["rows"]
                mode = classify_comprobante_tax_mode(rows)
                self.assertEqual(mode, scenario["expected_mode"])

    def test_fixture_totals(self):
        for scenario in load_tax_scenarios():
            with self.subTest(scenario=scenario["id"]):
                rows = scenario["rows"]
                totals = compute_comprobante_totals(rows)
                if scenario.get("expected_iva_odoo") is not None:
                    self.assertAlmostEqual(
                        totals["iva_odoo"], scenario["expected_iva_odoo"], places=2
                    )
                if scenario.get("expected_base_odoo") is not None:
                    self.assertAlmostEqual(
                        totals["base_odoo"], scenario["expected_base_odoo"], places=2
                    )
                if scenario.get("expected_total_odoo") is not None:
                    self.assertAlmostEqual(
                        totals["total_odoo"], scenario["expected_total_odoo"], places=2
                    )
                if scenario.get("expected_otros") is not None:
                    self.assertAlmostEqual(
                        sum_otros_impuestos(rows), scenario["expected_otros"], places=2
                    )
                if scenario.get("expected_warnings"):
                    self.assertTrue(totals.get("warnings"))

    def test_collect_matches_totals_for_explicit_json(self):
        scenario = scenario_by_id("explicit_json_overrides_line")
        rows = scenario["rows"]
        totals = compute_comprobante_totals(rows)
        with patch(
            "facturia_matching.padron.taxes.get_purchase_iva_taxes",
            return_value=ALIARE_IVA_TAXES,
        ):
            amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertEqual(sum(amounts.values()), totals["iva_odoo"])
        self.assertAlmostEqual(totals["iva_odoo"], 999.0, places=2)

    def test_proceso4_footer_not_editable_in_breakdown(self):
        """Regresión: modo line → pie readonly (verificado vía flags del fixture)."""
        scenario = scenario_by_id("proceso4_line_single_rate")
        self.assertFalse(scenario["footer_editable"])
        self.assertTrue(scenario["show_iva_column"])
        self.assertEqual(classify_comprobante_tax_mode(scenario["rows"]), "line")

    def test_line_manual_iva_uses_row_override(self):
        scenario = scenario_by_id("line_manual_iva_override")
        totals = compute_comprobante_totals(scenario["rows"])
        self.assertEqual(scenario["expected_mode"], "line")
        self.assertAlmostEqual(totals["iva_odoo"], 460.0, places=2)

    def test_multi_rate_fac_iva_montos(self):
        scenario = scenario_by_id("multi_rate_json")
        montos = fac_iva_montos(scenario["rows"])
        self.assertAlmostEqual(montos["21"], 18726.13, places=2)
        self.assertAlmostEqual(montos["10.5"], 1012.59, places=2)
        totals = compute_comprobante_totals(scenario["rows"])
        self.assertAlmostEqual(totals["iva_odoo"], 19738.72, places=2)


class TestBackfillPipeline(unittest.TestCase):
    @patch("facturia_matching.core.process.get_process")
    def test_backfill_then_classify_and_totals(self, mock_get):
        mock_get.return_value = {
            "json_data": json.dumps(
                {
                    "facturas": [
                        {
                            "json": {
                                "factura": {
                                    "iva_21": "15893.38",
                                    "iva_10_5": "2832.75",
                                    "items": [{"descripcion": "A", "alicuota_iva": 21}],
                                }
                            }
                        }
                    ]
                }
            )
        }
        rows = [
            {
                "__comprobante_idx": 0,
                "iva_pct": "21",
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "1000",
            }
        ]
        out = backfill_fac_iva_montos_from_process(rows, "99")
        montos = json.loads(out[0]["__fac_iva_montos"])
        self.assertEqual(montos.get("21"), "15893.38")
        self.assertEqual(montos.get("10.5"), "2832.75")
        totals = compute_comprobante_totals(out)
        self.assertGreater(totals["iva_odoo"], 0)

    @patch("facturia_matching.core.process.get_process")
    def test_backfill_skips_existing_json(self, mock_get):
        mock_get.return_value = {
            "json_data": json.dumps(
                {
                    "facturas": [
                        {
                            "json": {
                                "factura": {
                                    "iva_21": "99999",
                                    "items": [],
                                }
                            }
                        }
                    ]
                }
            )
        }
        rows = [
            {
                "__comprobante_idx": 0,
                "__fac_iva_montos": '{"21": "100"}',
                "__fac_iva_monto": "100",
            }
        ]
        out = backfill_fac_iva_montos_from_process(rows, "1")
        self.assertEqual(json.loads(out[0]["__fac_iva_montos"])["21"], "100")


class TestAliareMultiRateImport(unittest.TestCase):
    def setUp(self):
        self.patcher = patch(
            "facturia_matching.padron.taxes.get_purchase_iva_taxes",
            return_value=ALIARE_IVA_TAXES,
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_collect_multi_rate_explicit_montos(self):
        rows = [
            {
                "iva_pct": "21",
                "__fac_iva_montos": '{"21": "18726.13", "10.5": "1012.59"}',
                "__fac_iva_monto": "19738.72",
                "invoice_line_ids/name": "x",
                "invoice_line_ids/price_unit": "1",
                "invoice_line_ids/quantity": "1",
            }
        ]
        amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertAlmostEqual(amounts.get(65), 18726.13, places=2)
        self.assertAlmostEqual(amounts.get(63), 1012.59, places=2)


if __name__ == "__main__":
    unittest.main()
