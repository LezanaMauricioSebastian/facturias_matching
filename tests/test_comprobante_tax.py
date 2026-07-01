"""Tests: clasificación IVA por comprobante y totales."""

import json
import unittest

from facturia_matching.odoo.import_ import (
    _tax_ids_for_odoo_line,
    collect_expected_tax_amounts_from_group,
)
from facturia_matching.core.comprobante_tax import (
    _explicit_fac_iva_montos,
    classify_comprobante_tax_mode,
    compute_comprobante_totals,
    fac_iva_monto,
    fac_iva_montos,
    line_base,
    line_iva_monto,
    line_iva_suggested,
    reconcile_fac_iva_for_import,
    sanitize_inflated_line_amounts,
    sum_line_iva_montos,
    sum_otros_impuestos,
    sync_fac_iva_montos_from_lines,
)
from tax_fixtures import scenario_by_id


class TestComprobanteTax(unittest.TestCase):
    def test_header_mode_when_only_fac_iva(self):
        rows = [
            {
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "964,37",
                "iva_pct": "0",
                "__fac_subtotal": "97719.14",
                "__fac_iva_monto": "20521.22",
            },
            {
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "12786,04",
                "iva_pct": "0",
            },
        ]
        self.assertEqual(classify_comprobante_tax_mode(rows), "header")
        totals = compute_comprobante_totals(rows)
        self.assertEqual(totals["iva_fac"], 20521.22)
        self.assertEqual(totals["iva_odoo"], 20521.22)
        self.assertAlmostEqual(totals["base_fac"], 97719.14)
        self.assertAlmostEqual(totals["base_odoo"], 97719.14)
        self.assertAlmostEqual(totals["total_odoo"], 97719.14 + 20521.22)

    def test_line_mode_when_sum_matches_header(self):
        rows = [
            {
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "1000",
                "iva_pct": "21",
                "__fac_iva_monto": "420",
            },
            {
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "1000",
                "iva_pct": "21",
            },
        ]
        self.assertEqual(classify_comprobante_tax_mode(rows), "line")
        self.assertAlmostEqual(line_iva_suggested(rows[0]), 210.0)
        totals = compute_comprobante_totals(rows)
        self.assertEqual(totals["mode"], "line")
        self.assertAlmostEqual(totals["iva_odoo"], 420.0, places=2)
        self.assertAlmostEqual(totals["base_odoo"], 2000.0, places=2)
        self.assertAlmostEqual(totals["total_odoo"], 2420.0, places=2)

    def test_single_line_with_rate_uses_header_when_iva_differs(self):
        """Una línea con % IVA que no cierra → encabezado (IVA del pie FacturIA)."""
        rows = [
            {
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "17768,6",
                "iva_pct": "10,5",
                "__fac_subtotal": "17768.60",
                "__fac_iva_monto": "7736.40",
            },
        ]
        self.assertEqual(classify_comprobante_tax_mode(rows), "header")
        totals = compute_comprobante_totals(rows)
        self.assertEqual(totals["mode"], "header")
        self.assertEqual(totals["iva_odoo"], 7736.40)
        self.assertFalse(totals["warnings"])

    def test_mixed_mode_when_lines_do_not_close(self):
        rows = [
            {
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "964,37",
                "iva_pct": "21",
                "__fac_iva_monto": "20521.22",
            },
            {
                "invoice_line_ids/quantity": "2840",
                "invoice_line_ids/price_unit": "12628,72",
                "iva_pct": "0",
            },
        ]
        self.assertEqual(classify_comprobante_tax_mode(rows), "mixed")
        totals = compute_comprobante_totals(rows)
        self.assertTrue(totals["warnings"])

    def test_header_mode_uses_fac_subtotal_not_inflated_lines(self):
        """Línea con qty/precio desproporcionados no debe inflar el preview Odoo."""
        rows = [
            {
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "964,37",
                "iva_pct": "0",
                "__fac_subtotal": "110024.13",
                "__fac_iva_monto": "20521.22",
            },
            {
                "invoice_line_ids/quantity": "2840",
                "invoice_line_ids/price_unit": "12628,72",
                "iva_pct": "0",
            },
        ]
        self.assertEqual(classify_comprobante_tax_mode(rows), "header")
        totals = compute_comprobante_totals(rows)
        self.assertAlmostEqual(totals["base_odoo"], 110024.13)
        self.assertAlmostEqual(totals["total_odoo"], 130545.35)
        self.assertFalse(totals["warnings"])

    def test_sanitize_inflated_line_qty(self):
        rows = [
            {
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "964,37",
                "__fac_subtotal": "110024.13",
                "__comprobante_idx": 0,
            },
            {
                "invoice_line_ids/quantity": "2840",
                "invoice_line_ids/price_unit": "12628,72",
                "__comprobante_idx": 0,
            },
        ]
        self.assertEqual(sanitize_inflated_line_amounts(rows), 1)
        self.assertEqual(rows[1]["invoice_line_ids/quantity"], "1")
        self.assertAlmostEqual(line_base(rows[1]), 12628.72)

    def test_fac_iva_montos_from_json(self):
        rows = [
            {
                "__fac_iva_montos": '{"21": "18726.13", "10.5": "1012.59"}',
                "invoice_line_ids/name": "A",
                "invoice_line_ids/price_unit": "1",
            }
        ]
        montos = fac_iva_montos(rows)
        self.assertEqual(montos.get("21"), 18726.13)
        self.assertEqual(montos.get("10.5"), 1012.59)

    def test_fac_iva_from_legacy_row(self):
        rows = [{"iva_monto": "57255.38", "__iva_monto_manual": True}]
        self.assertEqual(fac_iva_monto(rows), 57255.38)

    def test_line_mode_with_fac_iva_montos_uses_explicit_sum(self):
        scenario = scenario_by_id("proceso4_line_single_rate")
        totals = compute_comprobante_totals(scenario["rows"])
        self.assertEqual(totals["mode"], "line")
        self.assertAlmostEqual(totals["iva_odoo"], 57255.38, places=2)

    def test_line_iva_monto_manual_override(self):
        row = {
            "invoice_line_ids/quantity": "1",
            "invoice_line_ids/price_unit": "1000",
            "iva_pct": "21",
            "iva_monto": "250",
            "__iva_monto_manual": True,
        }
        self.assertAlmostEqual(line_iva_monto(row), 250.0, places=2)
        self.assertAlmostEqual(line_iva_suggested(row), 210.0, places=2)

    def test_sum_line_iva_montos_with_manual(self):
        scenario = scenario_by_id("line_manual_iva_override")
        self.assertAlmostEqual(sum_line_iva_montos(scenario["rows"]), 460.0, places=2)

    def test_explicit_fac_iva_montos_ignores_total_key(self):
        rows = [{"__fac_iva_montos": '{"21": "100", "_total": "999"}'}]
        montos = _explicit_fac_iva_montos(rows)
        self.assertEqual(montos, {"21": 100.0})
        self.assertNotIn("_total", montos)

    def test_fac_iva_montos_header_fallback_single_rate(self):
        rows = [
            {
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "1000",
                "iva_pct": "21",
                "__fac_iva_monto": "500",
            }
        ]
        self.assertEqual(classify_comprobante_tax_mode(rows), "header")
        montos = fac_iva_montos(rows)
        self.assertEqual(montos, {"21": 500.0})

    def test_base_mismatch_warning(self):
        rows = [
            {
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "1000",
                "iva_pct": "21",
                "__fac_subtotal": "50000",
                "__fac_iva_monto": "420",
            },
            {
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "1000",
                "iva_pct": "21",
            },
        ]
        totals = compute_comprobante_totals(rows)
        self.assertEqual(totals["mode"], "line")
        self.assertTrue(any("Base FacturIA" in w for w in totals.get("warnings", [])))

    def test_sum_otros_impuestos_multiple_slots(self):
        rows = [
            {
                "otros_impuestos_monto": "10",
                "otros_impuestos_2_monto": "20",
                "otros_impuestos_3_monto": "5",
            }
        ]
        self.assertAlmostEqual(sum_otros_impuestos(rows), 35.0, places=2)

    def test_lines_with_rate_no_header_iva(self):
        scenario = scenario_by_id("lines_with_rate_no_header")
        self.assertEqual(classify_comprobante_tax_mode(scenario["rows"]), "line")
        totals = compute_comprobante_totals(scenario["rows"])
        self.assertAlmostEqual(totals["iva_odoo"], 210.0, places=2)

    def test_manual_iva_single_line_stays_line_mode(self):
        """Regresión: iva_monto en fila sin __iva_monto_manual (import servidor) → line."""
        rows = [
            {
                "iva_pct": "21",
                "iva_monto": "60000",
                "__fac_iva_monto": "60000",
                "__fac_iva_montos": '{"21": "60000"}',
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "272644.68",
                "invoice_line_ids/name": "Item",
            }
        ]
        self.assertEqual(classify_comprobante_tax_mode(rows), "line")
        self.assertEqual(_tax_ids_for_odoo_line(rows[0], rows), [63])
        amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertEqual(amounts.get(63), 60000.0)

    def test_sync_fac_iva_montos_from_lines_without_manual_flag(self):
        rows = [
            {
                "iva_pct": "21",
                "iva_monto": "60000",
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "272644.68",
                "invoice_line_ids/name": "Item",
            }
        ]
        reconcile_fac_iva_for_import(rows)
        self.assertEqual(classify_comprobante_tax_mode(rows), "line")
        montos = json.loads(rows[0]["__fac_iva_montos"])
        self.assertEqual(float(montos.get("21")), 60000.0)

    def test_reconcile_fac_iva_when_line_differs_from_stale_header(self):
        """Regresión proceso 4: iva_monto 60000 pero __fac_iva_monto 6000 en import."""
        rows = [
            {
                "iva_pct": "21",
                "iva_monto": "60.000,00",
                "__fac_iva_monto": "6000",
                "__fac_iva_montos": '{"21":"6.000,00"}',
                "__iva_monto_manual": True,
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "272.644,68",
                "invoice_line_ids/name": "Consumos",
            }
        ]
        self.assertEqual(classify_comprobante_tax_mode(rows), "line")
        reconcile_fac_iva_for_import(rows)
        self.assertEqual(float(rows[0]["__fac_iva_monto"].replace(",", ".")), 60000.0)
        amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertEqual(amounts.get(63), 60000.0)


if __name__ == "__main__":
    unittest.main()
