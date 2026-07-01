import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { loadTaxScenarios, scenarioById } from "./loadFixtures.mjs";
import {
  classifyComprobanteTaxMode,
  computeComprobanteTotals,
  footerIvaEditable,
  showIvaMontoColumn,
} from "../../src/facturia_matching/static/js/comprobanteTax/totals.js";
import {
  computeIvaBreakdown,
  parseFacIvaMontos,
  serializeFacIvaMontos,
} from "../../src/facturia_matching/static/js/comprobanteTax/ivaBreakdown.js";
import {
  lineIvaMonto,
  lineIvaSuggested,
  sumLineIvaMontos,
} from "../../src/facturia_matching/static/js/comprobanteTax/lineCalc.js";
import { migrateLegacyComprobanteIva, migrateFacIvaMontos } from "../../src/facturia_matching/static/js/comprobanteTax/migration.js";

describe("classifyComprobanteTaxMode (fixtures)", () => {
  for (const scenario of loadTaxScenarios()) {
    it(`${scenario.id} → ${scenario.expected_mode}`, () => {
      const mode = classifyComprobanteTaxMode(scenario.rows);
      assert.equal(mode, scenario.expected_mode);
    });
  }
});

describe("computeComprobanteTotals (fixtures)", () => {
  for (const scenario of loadTaxScenarios()) {
    if (scenario.expected_iva_odoo == null) continue;
    it(`${scenario.id} iva_odoo`, () => {
      const totals = computeComprobanteTotals(scenario.rows);
      assert.ok(Math.abs(totals.ivaOdoo - scenario.expected_iva_odoo) <= 0.02);
    });
  }
});

describe("editability matrix", () => {
  it("line mode: column visible, footer readonly", () => {
    assert.equal(showIvaMontoColumn("line"), true);
    assert.equal(footerIvaEditable("line"), false);
  });

  it("header mode: column hidden, footer editable", () => {
    assert.equal(showIvaMontoColumn("header"), false);
    assert.equal(footerIvaEditable("header"), true);
  });

  it("mixed mode: column hidden, footer editable", () => {
    assert.equal(showIvaMontoColumn("mixed"), false);
    assert.equal(footerIvaEditable("mixed"), true);
  });
});

describe("proceso4 regression", () => {
  it("footer breakdown not editable in line mode", () => {
    const scenario = scenarioById("proceso4_line_single_rate");
    const mode = classifyComprobanteTaxMode(scenario.rows);
    const breakdown = computeIvaBreakdown(scenario.rows, { mode });
    assert.ok(breakdown.length > 0);
    assert.ok(breakdown.every((row) => row.editable === false));
  });
});

describe("lineIvaMonto manual override", () => {
  it("uses manual value when flagged", () => {
    const row = {
      "invoice_line_ids/quantity": "1",
      "invoice_line_ids/price_unit": "1000",
      iva_pct: "21",
      iva_monto: "250",
      __iva_monto_manual: true,
    };
    assert.equal(lineIvaSuggested(row), 210);
    assert.equal(lineIvaMonto(row), 250);
  });

  it("sumLineIvaMontos respects manual in line mode scenario", () => {
    const scenario = scenarioById("line_manual_iva_override");
    assert.equal(sumLineIvaMontos(scenario.rows), 460);
  });
});

describe("serializeFacIvaMontos", () => {
  it("does not persist _total key in JSON", () => {
    const rows = [{ __comprobante_idx: 0 }];
    serializeFacIvaMontos(rows, { _total: "1000", 21: "500" });
    const parsed = JSON.parse(rows[0].__fac_iva_montos);
    assert.equal(parsed["21"], "500");
    assert.equal(parsed._total, undefined);
    assert.equal(rows[0].__fac_iva_monto, "500");
  });

  it("parseFacIvaMontos round-trip", () => {
    const rows = [{ __fac_iva_montos: '{"21": "100", "10.5": "50"}' }];
    const montos = parseFacIvaMontos(rows);
    assert.equal(montos["21"], "100");
    assert.equal(montos["10.5"], "50");
  });
});

describe("migrations", () => {
  it("migrateLegacyComprobanteIva moves row 0 iva to __fac_iva_monto", () => {
    const rows = [
      { iva_monto: "100", __iva_monto_manual: true, __comprobante_idx: 0 },
      { iva_monto: "50", __comprobante_idx: 0 },
    ];
    migrateLegacyComprobanteIva(rows);
    assert.equal(rows[0].__fac_iva_monto, "100");
    assert.equal(rows[0].iva_monto, "");
    assert.equal(rows[0].__iva_monto_manual, undefined);
    assert.equal(rows[1].iva_monto, "");
  });

  it("migrateFacIvaMontos infers multi-rate from lines", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        __fac_iva_monto: "31500",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "100000",
        iva_pct: "21",
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "100000",
        iva_pct: "10,5",
      },
    ];
    migrateFacIvaMontos(rows);
    const montos = parseFacIvaMontos(rows);
    assert.ok(Object.keys(montos).length >= 2);
  });
});

describe("explicit JSON vs line iva_monto", () => {
  it("line mode uses row iva_monto", () => {
    const scenario = scenarioById("explicit_json_overrides_line");
    const totals = computeComprobanteTotals(scenario.rows);
    assert.equal(totals.ivaOdoo, 999);
  });
});

describe("line mode manual iva stays line for import", () => {
  it("single line manual override is line mode", () => {
    const rows = [
      {
        iva_pct: "21",
        iva_monto: "60000",
        __iva_monto_manual: true,
        __fac_iva_monto: "60000",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "272644.68",
      },
    ];
    assert.equal(classifyComprobanteTaxMode(rows), "line");
    assert.equal(computeComprobanteTotals(rows).ivaOdoo, 60000);
  });

  it("single line explicit iva without manual flag stays line", () => {
    const rows = [
      {
        iva_pct: "21",
        iva_monto: "60000",
        __fac_iva_monto: "6000",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "272644.68",
      },
    ];
    assert.equal(classifyComprobanteTaxMode(rows), "line");
    assert.equal(computeComprobanteTotals(rows).ivaOdoo, 60000);
  });
});
