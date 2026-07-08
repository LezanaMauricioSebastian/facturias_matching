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
