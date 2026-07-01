import { loadTaxScenarios } from "./loadFixtures.mjs";
import { classifyComprobanteTaxMode, computeComprobanteTotals } from "../../src/facturia_matching/static/js/comprobanteTax/totals.js";
import { computeIvaBreakdown } from "../../src/facturia_matching/static/js/comprobanteTax/ivaBreakdown.js";
import { footerIvaEditable, showIvaMontoColumn } from "../../src/facturia_matching/static/js/comprobanteTax/totals.js";

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
console.log(JSON.stringify(out));
