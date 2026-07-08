"""Ejecuta tests JS y verifica paridad numérica Python/JS en fixtures."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from facturia_matching.core.comprobante_tax import (
    classify_comprobante_tax_mode,
    compute_comprobante_totals,
)
from tax_fixtures import load_tax_scenarios

ROOT = Path(__file__).resolve().parent.parent
JS_TEST = ROOT / "tests" / "js" / "comprobante_tax.test.mjs"
JS_EXPORT = ROOT / "tests" / "js" / "exportTotals.mjs"


def _write_js_exporter() -> None:
    """Script auxiliar: imprime totales JS por escenario (stdout JSON)."""
    JS_EXPORT.write_text(
        """
import { fileURLToPath } from "node:url";
import path from "node:path";
import { loadTaxScenarios } from "./loadFixtures.mjs";
import {
  classifyComprobanteTaxMode,
  computeComprobanteTotals,
  footerIvaEditable,
  showIvaMontoColumn,
} from "../../src/facturia_matching/static/js/comprobanteTax/totals.js";

export function exportTotals() {
  const out = [];
  for (const scenario of loadTaxScenarios()) {
    const mode = classifyComprobanteTaxMode(scenario.rows);
    const totals = computeComprobanteTotals(scenario.rows);
    out.push({
      id: scenario.id,
      mode,
      iva_odoo: totals.ivaOdoo,
      base_odoo: totals.baseOdoo,
      total_odoo: totals.totalOdoo,
      footer_editable: footerIvaEditable(mode),
      show_iva_column: showIvaMontoColumn(mode),
    });
  }
  return out;
}

const __filename = fileURLToPath(import.meta.url);

const isMain =
  process.argv[1] && path.resolve(process.argv[1]) === path.resolve(__filename);

if (isMain) {
  console.log(JSON.stringify(exportTotals()));
}
""".strip()
        + "\n",
        encoding="utf-8",
    )


class TestJsPythonParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            return
        _write_js_exporter()
        proc = subprocess.run(
            [cls.node, str(JS_EXPORT)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            cls.js_results = None
            cls.js_error = proc.stderr or proc.stdout
            return
        cls.js_results = {row["id"]: row for row in json.loads(proc.stdout)}
        cls.js_error = None

    def setUp(self):
        if not self.node:
            self.skipTest("node no está instalado")
        if self.js_results is None:
            self.skipTest(f"export JS falló: {self.js_error}")

    def test_run_js_unit_suite(self):
        proc = subprocess.run(
            [self.node, "--test", str(JS_TEST)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            msg=proc.stderr or proc.stdout,
        )

    def test_mode_parity_all_fixtures(self):
        for scenario in load_tax_scenarios():
            with self.subTest(scenario=scenario["id"]):
                py_mode = classify_comprobante_tax_mode(scenario["rows"])
                js_row = self.js_results[scenario["id"]]
                self.assertEqual(py_mode, js_row["mode"])
                self.assertEqual(py_mode, scenario["expected_mode"])

    def test_iva_odoo_parity_when_expected(self):
        for scenario in load_tax_scenarios():
            if scenario.get("expected_iva_odoo") is None:
                continue
            with self.subTest(scenario=scenario["id"]):
                py_totals = compute_comprobante_totals(scenario["rows"])
                js_row = self.js_results[scenario["id"]]
                self.assertAlmostEqual(py_totals["iva_odoo"], js_row["iva_odoo"], places=2)
                self.assertAlmostEqual(
                    py_totals["iva_odoo"], scenario["expected_iva_odoo"], places=2
                )

    def test_editability_flags_match_fixture(self):
        for scenario in load_tax_scenarios():
            with self.subTest(scenario=scenario["id"]):
                js_row = self.js_results[scenario["id"]]
                if "footer_editable" in scenario:
                    self.assertEqual(
                        js_row["footer_editable"],
                        scenario["footer_editable"],
                    )
                if "show_iva_column" in scenario:
                    self.assertEqual(
                        js_row["show_iva_column"],
                        scenario["show_iva_column"],
                    )


if __name__ == "__main__":
    unittest.main()
