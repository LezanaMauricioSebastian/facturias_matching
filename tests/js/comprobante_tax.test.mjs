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
  persistRealignedFooterRates,
  serializeFacIvaMontos,
} from "../../src/facturia_matching/static/js/comprobanteTax/ivaBreakdown.js";
import {
  lineIvaMonto,
  lineIvaSuggested,
  sumLineIvaMontos,
  shouldHideIvaFooter,
  shouldShowOtrosFooter,
  hasOtrosImpuestosSelection,
  ivaPctRequiresLineTax,
  clearFacIvaFooter,
  allContentLinesExplicitZeroIva,
} from "../../src/facturia_matching/static/js/comprobanteTax/lineCalc.js";
import {
  computeOtrosBreakdown,
  ensureOtrosLabelOnFirstRow,
  setOtrosFooterAmount,
  missingFacOtrosAssignments,
} from "../../src/facturia_matching/static/js/comprobanteTax/otrosBreakdown.js";
import { migrateLegacyComprobanteIva, migrateFacIvaMontos, propagateSingleFooterIvaToLines } from "../../src/facturia_matching/static/js/comprobanteTax/migration.js";
import {
  computeRowTotal,
  clearStickyLineIvaOnPriceQtyEdit,
} from "../../src/facturia_matching/static/js/rows/totals.js";
import { toNumberLoose } from "../../src/facturia_matching/static/js/utils/index.js";

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
  it("amounts only in pie: Monto IVA column always hidden, footer editable", () => {
    assert.equal(showIvaMontoColumn("line"), false);
    assert.equal(showIvaMontoColumn("header"), false);
    assert.equal(showIvaMontoColumn("mixed"), false);
    assert.equal(showIvaMontoColumn("line", true), false);
    assert.equal(footerIvaEditable("line"), true);
    assert.equal(footerIvaEditable("header"), true);
    assert.equal(footerIvaEditable("mixed"), true);
  });
});

describe("proceso4 regression", () => {
  it("footer breakdown editable in line mode (override from pie)", () => {
    const scenario = scenarioById("proceso4_line_single_rate");
    const mode = classifyComprobanteTaxMode(scenario.rows);
    const breakdown = computeIvaBreakdown(scenario.rows, { mode });
    assert.ok(breakdown.length > 0);
    assert.ok(breakdown.every((row) => row.editable === true));
  });

  it("line mode footer override becomes authoritative for totals", () => {
    const rows = structuredClone(scenarioById("proceso4_line_single_rate").rows);
    serializeFacIvaMontos(rows, { 21: "50000" });
    rows[0].__fac_iva_monto_manual = true;
    const totals = computeComprobanteTotals(rows);
    assert.ok(Math.abs(totals.ivaOdoo - 50000) <= 0.02);
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

  it("migrateLegacyComprobanteIva keeps modern line Monto IVA (PDF Salta reload)", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "COCA",
        "invoice_line_ids/quantity": "10",
        "invoice_line_ids/price_unit": "11658.03",
        iva_pct: "21",
        iva_monto: "24481.86",
        __iva_monto_manual: true,
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "SPRITE",
        "invoice_line_ids/quantity": "4",
        "invoice_line_ids/price_unit": "5033.29",
        iva_pct: "21",
        iva_monto: "4227.96",
        __iva_monto_manual: true,
      },
    ];
    migrateLegacyComprobanteIva(rows);
    assert.equal(rows[0].iva_monto, "24481.86");
    assert.equal(rows[0].__iva_monto_manual, true);
    assert.equal(rows[1].iva_monto, "4227.96");
    assert.equal(rows[1].__iva_monto_manual, true);
    const mode = classifyComprobanteTaxMode(rows);
    assert.ok(mode === "line" || mode === "mixed", `mode=${mode}`);
    assert.equal(showIvaMontoColumn(mode, false), false);
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

  it("propagates single footer IVA to empty line iva_pct", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        __fac_iva_monto: "2183.37",
        __fac_iva_montos: '{"21":"2183.37"}',
        "invoice_line_ids/name": "Servicio",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "10397",
        iva_pct: "",
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "Otro",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "100",
        iva_pct: "0",
      },
    ];
    const n = propagateSingleFooterIvaToLines(rows);
    assert.equal(n, 2);
    assert.equal(rows[0].iva_pct, "21");
    assert.equal(rows[1].iva_pct, "21");
  });

  it("does not propagate when footer has multiple IVA rates", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        __fac_iva_montos: '{"21":"100","10.5":"50"}',
        "invoice_line_ids/name": "A",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "1000",
        iva_pct: "",
      },
    ];
    assert.equal(propagateSingleFooterIvaToLines(rows), 0);
    assert.equal(rows[0].iva_pct, "");
  });

  it("does not overwrite Exento when propagating single footer IVA", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        __fac_iva_montos: '{"21":"100"}',
        "invoice_line_ids/name": "Exento",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "1000",
        iva_pct: "IVA Exento",
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "Gravado",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "500",
        iva_pct: "",
      },
    ];
    assert.equal(propagateSingleFooterIvaToLines(rows), 1);
    assert.equal(rows[0].iva_pct, "IVA Exento");
    assert.equal(rows[1].iva_pct, "21");
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

describe("header footer IVA fixed when price changes", () => {
  it("keeps line iva_monto and footer breakdown when price changes", () => {
    const rows = [
      {
        iva_pct: "21",
        iva_monto: "72399,60",
        __fac_subtotal: "344760",
        __fac_iva_monto: "72399.60",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "777",
      },
    ];
    const mode = classifyComprobanteTaxMode(rows);
    const breakdown = computeIvaBreakdown(rows, { mode });
    assert.equal(mode, "line");
    assert.ok(Math.abs(breakdown[0].amount - 72399.6) <= 0.02);
    assert.equal(computeComprobanteTotals(rows, mode).ivaOdoo, 72399.6);
  });

  it("header mode footer uses __fac_iva_monto when price no longer matches rate", () => {
    const rows = [
      {
        iva_pct: "21",
        iva_monto: "163,17",
        __fac_subtotal: "344760",
        __fac_iva_monto: "72399.60",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "777",
      },
    ];
    const mode = classifyComprobanteTaxMode(rows);
    const breakdown = computeIvaBreakdown(rows, { mode });
    assert.equal(mode, "header");
    assert.ok(Math.abs(breakdown[0].amount - 72399.6) <= 0.02);
  });

  it("single_line_rate_mismatch footer uses header IVA not suggested", () => {
    const scenario = scenarioById("single_line_rate_mismatch");
    const breakdown = computeIvaBreakdown(scenario.rows, { mode: "header" });
    assert.ok(breakdown.length > 0);
    assert.ok(Math.abs(breakdown[0].amount - 7736.4) <= 0.02);
  });
});

describe("IVA Exento / No Gravado", () => {
  it("ivaPctRequiresLineTax distinguishes special zero labels", () => {
    assert.equal(ivaPctRequiresLineTax("IVA Exento"), true);
    assert.equal(ivaPctRequiresLineTax("IVA No Gravado"), true);
    assert.equal(ivaPctRequiresLineTax("IVA No Corresponde"), true);
    assert.equal(ivaPctRequiresLineTax("0"), false);
    assert.equal(ivaPctRequiresLineTax("21"), true);
  });

  it("shouldHideIvaFooter for single line IVA Exento or No Gravado", () => {
    const exento = [
      {
        iva_pct: "IVA Exento",
        "invoice_line_ids/name": "X",
        "invoice_line_ids/price_unit": "100",
        "invoice_line_ids/quantity": "1",
      },
    ];
    const noGravado = [{ ...exento[0], iva_pct: "IVA No Gravado" }];
    const noCorresponde = [{ ...exento[0], iva_pct: "IVA No Corresponde" }];
    const twoLines = [exento[0], { ...exento[0], "invoice_line_ids/name": "Y" }];
    assert.equal(shouldHideIvaFooter(exento), true);
    assert.equal(shouldHideIvaFooter(noGravado), true);
    assert.equal(shouldHideIvaFooter(noCorresponde), true);
    assert.equal(shouldHideIvaFooter(twoLines), false);
  });

  it("clears stale 21% footer when selecting IVA Exento (PDF Mauri)", () => {
    const rows = [
      {
        iva_pct: "IVA Exento",
        __fac_iva_monto: "57255.38",
        __fac_iva_montos: '{"21": "57255.38"}',
        otros_impuestos_monto: "3544.38",
        "invoice_line_ids/name": "Consumos",
        "invoice_line_ids/price_unit": "272644.68",
        "invoice_line_ids/quantity": "1",
      },
    ];
    assert.equal(allContentLinesExplicitZeroIva(rows), true);
    clearFacIvaFooter(rows);
    assert.equal(rows[0].__fac_iva_montos, undefined);
    assert.equal(rows[0].__fac_iva_monto, "");
    const totals = computeComprobanteTotals(rows);
    assert.equal(totals.ivaOdoo, 0);
    assert.ok(Math.abs(totals.totalOdoo - (272644.68 + 3544.38)) <= 0.02);
    assert.equal(computeIvaBreakdown(rows, { mode: totals.mode }).length, 0);
  });

  it("keeps footer IVA when iva_pct is empty (header mode)", () => {
    const rows = [
      {
        iva_pct: "",
        __fac_iva_monto: "57255.38",
        __fac_iva_montos: '{"21": "57255.38"}',
        "invoice_line_ids/name": "Consumos",
        "invoice_line_ids/price_unit": "272644.68",
        "invoice_line_ids/quantity": "1",
      },
    ];
    assert.equal(allContentLinesExplicitZeroIva(rows), false);
    const totals = computeComprobanteTotals(rows);
    assert.ok(Math.abs(totals.ivaOdoo - 57255.38) <= 0.02);
  });
});

describe("cambio de alícuota en la línea (Sudata 13/8/2026)", () => {
  const eliasRows = (ivaPct) => [
    {
      iva_pct: ivaPct,
      __fac_subtotal: "294299,87",
      __fac_iva_monto: "48306,18",
      __fac_iva_montos: '{"21": "48306,18"}',
      "invoice_line_ids/name": "COCA-COLA 600*12 PET",
      "invoice_line_ids/price_unit": "294299,87",
      "invoice_line_ids/quantity": "1",
      otros_impuestos: "P. IIBB CABA",
      otros_impuestos_monto: "7133,73",
    },
  ];

  it("relabels footer IVA 21% → 10,5% instead of showing both rates", () => {
    const rows = eliasRows("10,5");
    const mode = classifyComprobanteTaxMode(rows);
    const breakdown = computeIvaBreakdown(rows, { mode });
    assert.deepEqual(
      breakdown.map((b) => b.rateKey),
      ["10.5"]
    );
    assert.ok(Math.abs(breakdown[0].amount - 48306.18) <= 0.02);
    const totals = computeComprobanteTotals(rows, mode);
    assert.ok(Math.abs(totals.ivaOdoo - 48306.18) <= 0.02);
  });

  it("persists the relabeled footer so autosave drops the old rate", () => {
    const rows = eliasRows("10,5");
    assert.equal(persistRealignedFooterRates(rows), true);
    assert.deepEqual(JSON.parse(rows[0].__fac_iva_montos), { "10.5": "48306.18" });
    assert.ok(Math.abs(toNumberLoose(rows[0].__fac_iva_monto) - 48306.18) <= 0.02);
  });

  it("leaves the footer untouched when the rate still matches", () => {
    const rows = eliasRows("21");
    assert.equal(persistRealignedFooterRates(rows), false);
    assert.deepEqual(JSON.parse(rows[0].__fac_iva_montos), { "21": "48306,18" });
  });

  it("keeps footer rates the lines do not cover (subtotal > line bases)", () => {
    const rows = eliasRows("10,5");
    rows[0].__fac_subtotal = "500000";
    const breakdown = computeIvaBreakdown(rows, { mode: classifyComprobanteTaxMode(rows) });
    assert.deepEqual(
      breakdown.map((b) => b.rateKey),
      ["21", "10.5"]
    );
  });
});

describe("partial multi-rate IVA breakdown total", () => {
  it("sums all footer IVA rows when only one rate is stored in __fac_iva_montos", () => {
    const rows = [
      {
        "__fac_subtotal": "64242",
        "__fac_iva_monto": "29020.14",
        "__fac_iva_montos": '{"21": "29020.14"}',
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "138200",
        "iva_pct": "21",
      },
      {
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "22242",
        "iva_pct": "10,5",
      },
      {
        "otros_impuestos_monto": "3000",
      },
    ];
    const mode = classifyComprobanteTaxMode(rows);
    const totals = computeComprobanteTotals(rows, mode);
    const breakdown = computeIvaBreakdown(rows, { mode });
    assert.equal(mode, "mixed");
    assert.equal(breakdown.length, 2);
    assert.ok(Math.abs(breakdown.find((b) => b.rateKey === "21")?.amount - 29020.14) <= 0.02);
    assert.ok(Math.abs(breakdown.find((b) => b.rateKey === "10.5")?.amount - 2335.41) <= 0.02);
    const breakdownSum = breakdown.reduce((acc, row) => acc + (row.amount || 0), 0);
    assert.ok(Math.abs(totals.ivaOdoo - breakdownSum) <= 0.02);
    assert.ok(Math.abs(totals.ivaOdoo - 31355.55) <= 0.02);
    assert.ok(Math.abs(totals.totalOdoo - (totals.baseOdoo + totals.ivaOdoo + totals.otros)) <= 0.02);
    assert.ok(Math.abs(totals.totalOdoo - 96262.14) > 1);
  });

    it("matches screenshot: header base with partial __fac_iva_montos and extra line rate", () => {
    const rows = [
      {
        "__fac_subtotal": "64242",
        "__fac_iva_monto": "29020.14",
        "__fac_iva_montos": '{"21": "29020.14"}',
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "22242",
        "iva_pct": "10,5",
        "otros_impuestos_monto": "3000",
      },
    ];
    const mode = classifyComprobanteTaxMode(rows);
    const totals = computeComprobanteTotals(rows, mode);
    assert.equal(mode, "header");
    assert.ok(Math.abs(totals.baseOdoo - 64242) <= 0.02);
    assert.ok(Math.abs(totals.totalOdoo - 98597.55) <= 0.02);
  });

  it("keeps fac subtotal as Base when selecting IVA flips header→mixed (PDF Mauri)", () => {
    const rows = [
      {
        __fac_subtotal: "188102.36",
        __fac_iva_monto: "39501.50",
        __fac_iva_montos: '{"21":"39501,50"}',
        "invoice_line_ids/quantity": "2",
        "invoice_line_ids/price_unit": "14056",
        iva_pct: "21",
      },
      {
        "invoice_line_ids/quantity": "2",
        "invoice_line_ids/price_unit": "18097",
        iva_pct: "",
      },
      {
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "12421",
        iva_pct: "",
      },
    ];
    const mode = classifyComprobanteTaxMode(rows);
    const totals = computeComprobanteTotals(rows, mode);
    assert.equal(mode, "mixed");
    assert.ok(Math.abs(totals.baseOdoo - 188102.36) <= 0.02);
    assert.ok(Math.abs(totals.baseLines - 76727) <= 0.02);
    assert.ok(Math.abs(totals.ivaOdoo - 39501.5) <= 0.02);
  });
});

describe("otros impuestos footer visibility", () => {
  it("hidden without selection and zero amount", () => {
    const rows = [{ otros_impuestos: "", otros_impuestos_monto: "" }];
    assert.equal(hasOtrosImpuestosSelection(rows), false);
    assert.equal(shouldShowOtrosFooter(rows, { otros: 0 }), false);
  });

  it("visible with selection and zero amount", () => {
    const rows = [{ otros_impuestos: "Percepción IIBB CABA Sufrida" }];
    assert.equal(hasOtrosImpuestosSelection(rows), true);
    assert.equal(shouldShowOtrosFooter(rows, { otros: 0 }), true);
  });

  it("visible when amount is positive even without selection label", () => {
    const rows = [{ otros_impuestos: "", otros_impuestos_monto: "150" }];
    assert.equal(shouldShowOtrosFooter(rows, { otros: 150 }), true);
  });

  it("visible with FacturIA percepciones meta even if slots empty in totals", () => {
    const rows = [
      {
        otros_impuestos: "",
        otros_impuestos_monto: "",
        __fac_percepciones: [{ amount_key: "percepcion_iibb", monto: "33447.37", ui_monto_key: "otros_impuestos_monto" }],
      },
    ];
    assert.equal(shouldShowOtrosFooter(rows, { otros: 0 }), true);
  });
});

describe("otros impuestos named footer breakdown", () => {
  it("shows provisional IIBB label from FacturIA when slot has amount without label", () => {
    const rows = [
      {
        otros_impuestos: "",
        otros_impuestos_monto: "33447,37",
        __fac_percepciones: [
          { amount_key: "percepcion_iibb", monto: "33447,37", ui_monto_key: "otros_impuestos_monto" },
        ],
      },
    ];
    const breakdown = computeOtrosBreakdown(rows);
    assert.equal(breakdown.length, 1);
    assert.equal(breakdown[0].label, "IIBB");
    assert.ok(Math.abs(breakdown[0].amount - 33447.37) <= 0.02);
    assert.equal(breakdown[0].slotN, 1);
  });

  it("shows all FacturIA otros in footer with no line tax selected", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "COCA",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "100",
        otros_impuestos: "",
        __fac_subtotal: "250545.47",
        __fac_iva_monto: "52614.54",
        __fac_percepciones: [
          { amount_key: "percepcion_iibb", monto: "7791.70", ui_monto_key: "otros_impuestos_monto" },
          { amount_key: "percepcion_iva", monto: "7516.36", ui_monto_key: "otros_impuestos_2_monto" },
          { amount_key: "otros_tributos", monto: "18139.31", ui_monto_key: "otros_impuestos_3_monto" },
        ],
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "SPRITE",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "50",
        otros_impuestos: "",
      },
    ];
    assert.equal(shouldShowOtrosFooter(rows, { otros: 0 }), true);
    const breakdown = computeOtrosBreakdown(rows);
    assert.equal(breakdown.length, 3);
    assert.equal(breakdown[0].label, "IIBB");
    assert.equal(breakdown[1].label, "Percepción IVA");
    assert.equal(breakdown[2].label, "Impuesto Interno");
    assert.ok(Math.abs(breakdown[0].amount - 7791.7) <= 0.02);
    assert.ok(Math.abs(breakdown[1].amount - 7516.36) <= 0.02);
    assert.ok(Math.abs(breakdown[2].amount - 18139.31) <= 0.02);
    const totals = computeComprobanteTotals(rows);
    assert.ok(Math.abs(totals.otros - (7791.7 + 7516.36 + 18139.31)) <= 0.05);
  });

  it("does not add empty pie row for unrelated tax without editing first line", () => {
    const rows = [
      {
        otros_impuestos: "",
        otros_impuestos_monto: "33447,37",
        __fac_percepciones: [
          { amount_key: "percepcion_iibb", monto: "33447,37", ui_monto_key: "otros_impuestos_monto" },
        ],
      },
    ];
    assert.equal(ensureOtrosLabelOnFirstRow(rows, "Impuesto Interno"), null);
    const breakdown = computeOtrosBreakdown(rows);
    assert.equal(breakdown.length, 1);
    assert.equal(breakdown[0].label, "IIBB");
  });

  it("fills slot 2 on first line only when that line gets a second tax", () => {
    const rows = [
      {
        otros_impuestos: "Percepción IIBB Chaco Sufrida",
        otros_impuestos_monto: "100",
        __fac_percepciones: [
          { amount_key: "percepcion_iibb", monto: "100", ui_monto_key: "otros_impuestos_monto" },
        ],
      },
    ];
    const slotN = ensureOtrosLabelOnFirstRow(rows, "Impuesto Interno", {
      selectedRow: rows[0],
    });
    assert.equal(slotN, 2);
    assert.equal(rows[0].otros_impuestos_2, "Impuesto Interno");
    assert.equal(String(rows[0].otros_impuestos), "Percepción IIBB Chaco Sufrida");
  });

  it("claims otros_tributos FacturIA when selecting Impuesto Interno (no empty duplicate)", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "COCA",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "100",
        otros_impuestos: "",
        otros_impuestos_monto: "7791.70",
        otros_impuestos_2_monto: "7516.36",
        otros_impuestos_3_monto: "18139.31",
        __fac_percepciones: [
          { amount_key: "percepcion_iibb", monto: "7791.70", ui_monto_key: "otros_impuestos_monto" },
          { amount_key: "percepcion_iva", monto: "7516.36", ui_monto_key: "otros_impuestos_2_monto" },
          { amount_key: "otros_tributos", monto: "18139.31", ui_monto_key: "otros_impuestos_3_monto" },
        ],
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "AGUA",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "50",
        otros_impuestos: "Impuesto Interno",
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "SPRITE",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "40",
        otros_impuestos: "Percepción IVA Sufrida",
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "FANTA",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "30",
        otros_impuestos: "Percepción IIBB Chaco Sufrida",
      },
    ];
    rows[0].otros_impuestos_4 = "Impuesto Interno";
    rows[0].__otros_pie_mirror_4 = true;

    const breakdown = computeOtrosBreakdown(rows);
    // Sin label en 1ª fila slot 1 → provisional IIBB; labels de otras líneas en su col 1 no pisan el pie.
    assert.equal(breakdown[0].label, "IIBB");
    assert.equal(breakdown[1].label, "Percepción IVA");
    assert.equal(breakdown[2].label, "Impuesto Interno");
    assert.equal(String(rows[0].otros_impuestos_4 ?? "").trim(), "");
    assert.equal(missingFacOtrosAssignments(rows).length, 0);
  });

  it("warns when FacturIA taxes are not assigned on lines", () => {
    const rows = [
      {
        otros_impuestos: "",
        otros_impuestos_monto: "10",
        otros_impuestos_2_monto: "20",
        __fac_percepciones: [
          { amount_key: "percepcion_iibb", monto: "10", ui_monto_key: "otros_impuestos_monto" },
          { amount_key: "otros_tributos", monto: "20", ui_monto_key: "otros_impuestos_2_monto" },
        ],
      },
      { otros_impuestos: "Percepción IIBB Chaco Sufrida" },
    ];
    const missing = missingFacOtrosAssignments(rows);
    assert.deepEqual(missing, ["Impuesto Interno"]);
  });

  it("shows Odoo line label in pie when slot is assigned", () => {
    const rows = [
      {
        otros_impuestos: "Percepción IIBB Chaco Sufrida",
        otros_impuestos_monto: "100",
        __fac_percepciones: [
          { amount_key: "percepcion_iibb", monto: "100", ui_monto_key: "otros_impuestos_monto" },
        ],
      },
    ];
    const breakdown = computeOtrosBreakdown(rows);
    assert.equal(breakdown.length, 1);
    assert.equal(breakdown[0].label, "Percepción IIBB Chaco Sufrida");
    assert.ok(Math.abs(breakdown[0].amount - 100) <= 0.02);
    assert.equal(missingFacOtrosAssignments(rows).length, 0);
  });

  it("shows selected non-IIBB tax in pie and covers FacturIA slot", () => {
    const rows = [
      {
        otros_impuestos: "Percepción Ganancias Sufrida",
        otros_impuestos_monto: "5",
        __fac_percepciones: [
          { amount_key: "percepcion_iibb", monto: "5", ui_monto_key: "otros_impuestos_monto" },
        ],
      },
    ];
    const breakdown = computeOtrosBreakdown(rows);
    assert.equal(breakdown.length, 1);
    assert.equal(breakdown[0].label, "Percepción Ganancias Sufrida");
    assert.ok(Math.abs(breakdown[0].amount - 5) <= 0.02);
    assert.deepEqual(missingFacOtrosAssignments(rows), []);
  });

  it("shows pie rows for + taxes with label even when amount is still 0", () => {
    const rows = [
      {
        otros_impuestos: "IVA Adicional 20%",
        otros_impuestos_monto: "3544.38",
        otros_impuestos_2: "Percepción IIBB Formosa Sufrida",
        otros_impuestos_2_monto: "",
        otros_impuestos_3: "Impuesto Interno",
        otros_impuestos_3_monto: "",
        __fac_percepciones: [
          { amount_key: "percepcion_iibb", monto: "3544.38", ui_monto_key: "otros_impuestos_monto" },
        ],
      },
    ];
    const breakdown = computeOtrosBreakdown(rows);
    assert.equal(breakdown.length, 3);
    assert.equal(breakdown[0].label, "IVA Adicional 20%");
    assert.ok(Math.abs(breakdown[0].amount - 3544.38) <= 0.02);
    assert.equal(breakdown[1].label, "Percepción IIBB Formosa Sufrida");
    assert.equal(breakdown[1].amount, 0);
    assert.equal(breakdown[2].label, "Impuesto Interno");
    assert.equal(breakdown[2].amount, 0);
  });

  it("setOtrosFooterAmount writes one slot without wiping others", () => {
    const rows = [
      {
        otros_impuestos: "IIBB",
        otros_impuestos_monto: "100",
        otros_impuestos_2: "Impuesto Interno",
        otros_impuestos_2_monto: "50",
      },
    ];
    setOtrosFooterAmount(rows, 2, "75,5");
    assert.equal(rows[0].otros_impuestos_monto, "100");
    assert.equal(rows[0].otros_impuestos_2_monto, "75,5");
    const breakdown = computeOtrosBreakdown(rows);
    assert.equal(breakdown.length, 2);
    assert.ok(Math.abs(breakdown[1].amount - 75.5) <= 0.02);
  });

  it("distributes footer amount proportional to base among assigned rows", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "A",
        "invoice_line_ids/quantity": "3",
        "invoice_line_ids/price_unit": "100",
        otros_impuestos: "IIBB",
        otros_impuestos_monto: "",
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "B",
        "invoice_line_ids/quantity": "2",
        "invoice_line_ids/price_unit": "100",
        otros_impuestos: "IIBB",
        otros_impuestos_monto: "",
      },
    ];
    setOtrosFooterAmount(rows, 1, "100");
    assert.ok(Math.abs(toNumberLoose(rows[0].otros_impuestos_monto) - 60) <= 0.02);
    assert.ok(Math.abs(toNumberLoose(rows[1].otros_impuestos_monto) - 40) <= 0.02);
    const breakdown = computeOtrosBreakdown(rows);
    assert.equal(breakdown.length, 1);
    assert.ok(Math.abs(breakdown[0].amount - 100) <= 0.02);
    assert.ok(Math.abs(computeRowTotal(rows[0], "header") - (300 + 60)) <= 0.02);
    assert.ok(Math.abs(computeRowTotal(rows[1], "header") - (200 + 40)) <= 0.02);
  });

  it("puts full amount on the only row that has the tax assigned", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "A",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "100",
        otros_impuestos: "IVA No Gravado",
        otros_impuestos_monto: "",
        otros_impuestos_3_monto: "18139.31",
        __fac_percepciones: [
          { amount_key: "otros_tributos", monto: "18139.31", ui_monto_key: "otros_impuestos_3_monto" },
        ],
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "B",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "100",
        otros_impuestos: "Percepción IVA Sufrida",
        otros_impuestos_monto: "",
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "C",
        "invoice_line_ids/quantity": "5",
        "invoice_line_ids/price_unit": "100",
        otros_impuestos: "Impuesto Interno",
        otros_impuestos_monto: "",
      },
    ];
    // Slot FacturIA 3 = Impuesto Interno → se reparte a líneas con Impuesto Interno
    setOtrosFooterAmount(rows, 3, "18139.31");
    assert.ok(Math.abs(toNumberLoose(rows[2].otros_impuestos_monto) - 18139.31) <= 0.02);
    const breakdown = computeOtrosBreakdown(rows);
    const tributos = breakdown.find((b) => b.label === "Impuesto Interno");
    assert.ok(tributos);
    assert.ok(Math.abs(tributos.amount - 18139.31) <= 0.02);
    assert.equal(missingFacOtrosAssignments(rows).length, 0);
  });

  it("does not fill first-row cols 2/3 from other lines' taxes", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "A",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "100",
        otros_impuestos: "Percepción IIBB Chaco Sufrida",
        otros_impuestos_monto: "10",
        otros_impuestos_2_monto: "20",
        otros_impuestos_3_monto: "30",
        __fac_percepciones: [
          { amount_key: "percepcion_iibb", monto: "10", ui_monto_key: "otros_impuestos_monto" },
          { amount_key: "percepcion_iva", monto: "20", ui_monto_key: "otros_impuestos_2_monto" },
          { amount_key: "otros_tributos", monto: "30", ui_monto_key: "otros_impuestos_3_monto" },
        ],
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "B",
        otros_impuestos: "Percepción IVA Sufrida",
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "C",
        otros_impuestos: "Impuesto Interno",
      },
    ];
    computeOtrosBreakdown(rows);
    assert.equal(String(rows[0].otros_impuestos_2 ?? "").trim(), "");
    assert.equal(String(rows[0].otros_impuestos_3 ?? "").trim(), "");
    assert.equal(rows[0].otros_impuestos, "Percepción IIBB Chaco Sufrida");
    const labels = computeOtrosBreakdown(rows).map((b) => b.label);
    // 1ª fila tiene Perc IIBB en slot 1 → pie muestra ese Odoo label; 2/3 provisionales.
    assert.deepEqual(labels, [
      "Percepción IIBB Chaco Sufrida",
      "Percepción IVA",
      "Impuesto Interno",
    ]);
  });

  it("keeps IIBB in pie when first row selects Impuesto Interno (Dinner FA-A 05215-00084885)", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "COCA-COLA 600*12",
        "invoice_line_ids/quantity": "10",
        "invoice_line_ids/price_unit": "11658,03",
        otros_impuestos: "Impuesto Interno",
        otros_impuestos_monto: "9154.93",
        otros_impuestos_2_monto: "8901.72",
        otros_impuestos_3_monto: "18962.88",
        __fac_percepciones: [
          { amount_key: "percepcion_iibb", monto: "9154.93", ui_monto_key: "otros_impuestos_monto" },
          { amount_key: "percepcion_iva", monto: "8901.72", ui_monto_key: "otros_impuestos_2_monto" },
          { amount_key: "otros_tributos", monto: "18962.88", ui_monto_key: "otros_impuestos_3_monto" },
        ],
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "SPRITE FX LS 500ML",
        otros_impuestos: "Percepción IVA Sufrida",
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "COCA-COLA ZERO 600*06",
        otros_impuestos: "Impuesto Interno",
      },
    ];
    const breakdown = computeOtrosBreakdown(rows);
    const labels = breakdown.map((b) => b.label);
    assert.equal(breakdown.length, 3);
    assert.equal(labels.filter((l) => /impuesto\s*interno/i.test(l)).length, 1);
    const iibb = breakdown.find((b) => /iibb/i.test(b.label));
    const perc = breakdown.find((b) => /perc/i.test(b.label) && /iva/i.test(b.label));
    const interno = breakdown.find((b) => /impuesto\s*interno/i.test(b.label));
    assert.ok(iibb, `IIBB missing from pie: ${labels.join(" | ")}`);
    assert.ok(perc);
    assert.ok(interno);
    assert.ok(Math.abs(iibb.amount - 9154.93) <= 0.02);
    assert.ok(Math.abs(perc.amount - 8901.72) <= 0.02);
    assert.ok(Math.abs(interno.amount - 18962.88) <= 0.02);
    assert.deepEqual(missingFacOtrosAssignments(rows), ["IIBB"]);
  });

  it("lists extra tax from a later line in the pie (IVA Adicional 20%)", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "COCA",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "100",
        otros_impuestos: "Impuesto Interno",
        otros_impuestos_monto: "9154.93",
        otros_impuestos_2_monto: "8901.72",
        otros_impuestos_3_monto: "18962.88",
        __fac_percepciones: [
          { amount_key: "percepcion_iibb", monto: "9154.93", ui_monto_key: "otros_impuestos_monto" },
          { amount_key: "percepcion_iva", monto: "8901.72", ui_monto_key: "otros_impuestos_2_monto" },
          { amount_key: "otros_tributos", monto: "18962.88", ui_monto_key: "otros_impuestos_3_monto" },
        ],
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "SPRITE",
        otros_impuestos: "Percepción IVA Sufrida",
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "ZERO",
        otros_impuestos: "Percepción IIBB Chaco Sufrida",
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "AQUARIUS",
        otros_impuestos: "IVA Adicional 20%",
      },
    ];
    const breakdown = computeOtrosBreakdown(rows);
    const labels = breakdown.map((b) => b.label);
    assert.ok(labels.some((l) => /iibb/i.test(l)), `IIBB missing: ${labels.join(" | ")}`);
    assert.ok(labels.some((l) => /perc/i.test(l) && /iva/i.test(l)));
    assert.ok(labels.some((l) => /impuesto\s*interno/i.test(l)));
    assert.ok(labels.includes("IVA Adicional 20%"), `extra tax missing: ${labels.join(" | ")}`);
    const extra = breakdown.find((b) => b.label === "IVA Adicional 20%");
    assert.equal(extra.amount, 0);
    assert.equal(labels.filter((l) => /impuesto\s*interno/i.test(l)).length, 1);
    const iibb = breakdown.find((b) => /iibb/i.test(b.label));
    const perc = breakdown.find((b) => /perc/i.test(b.label) && /iva/i.test(b.label));
    const interno = breakdown.find((b) => /impuesto\s*interno/i.test(b.label));
    assert.ok(Math.abs(iibb.amount - 9154.93) <= 0.02);
    assert.ok(Math.abs(perc.amount - 8901.72) <= 0.02);
    assert.ok(Math.abs(interno.amount - 18962.88) <= 0.02);
    assert.equal(breakdown.length, 4);
  });

  it("falls back to first content row when no line has the tax assigned", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "A",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "100",
        otros_impuestos: "",
        otros_impuestos_monto: "",
        __fac_percepciones: [
          { amount_key: "percepcion_iibb", monto: "50", ui_monto_key: "otros_impuestos_monto" },
        ],
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/name": "B",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "200",
        otros_impuestos: "",
        otros_impuestos_monto: "",
      },
    ];
    // Slot 1 provisional IIBB sin label en líneas → 1ª contenido
    setOtrosFooterAmount(rows, 1, "7791.70");
    assert.ok(Math.abs(toNumberLoose(rows[0].otros_impuestos_monto) - 7791.7) <= 0.02);
    assert.equal(String(rows[1].otros_impuestos_monto ?? "").trim(), "");
  });

  it("row Total ignores FacturIA otros montos without a tax label on that line", () => {
    // Regresión: 1ª fila hidrataba IIBB + Perc IVA + Interno y Total ~174k
    // aunque la línea solo tenía IVA 21 % + Perc IIBB Chaco.
    const row = {
      "invoice_line_ids/quantity": "1",
      "invoice_line_ids/price_unit": "100000",
      iva_pct: "21%",
      iva_monto: "21000",
      __iva_monto_manual: true,
      otros_impuestos: "Perc IIBB Chaco",
      otros_impuestos_monto: "7791.70",
      otros_impuestos_2_monto: "7516.36",
      otros_impuestos_3_monto: "18139.31",
      __fac_percepciones: [
        { amount_key: "percepcion_iibb", monto: "7791.70", ui_monto_key: "otros_impuestos_monto" },
        { amount_key: "percepcion_iva", monto: "7516.36", ui_monto_key: "otros_impuestos_2_monto" },
        { amount_key: "otros_tributos", monto: "18139.31", ui_monto_key: "otros_impuestos_3_monto" },
      ],
    };
    const total = computeRowTotal(row, "line");
    // base 100000 + IVA 21000 + solo IIBB 7791.70 (no perc/interno sin label)
    assert.ok(Math.abs(total - (100000 + 21000 + 7791.7)) <= 0.05);
    assert.ok(total < 140000);
  });

  it("line Total includes IVA; clearing IVA brings Total back to Subtotal", () => {
    const row = {
      "invoice_line_ids/quantity": "3",
      "invoice_line_ids/price_unit": "1628,06",
      iva_pct: "10,5",
    };
    const subtotal = 3 * 1628.06;
    assert.ok(Math.abs(computeRowTotal(row, "mixed") - subtotal * 1.105) <= 0.05);
    row.iva_pct = "";
    row.iva_monto = "";
    delete row.__iva_monto_manual;
    assert.ok(Math.abs(computeRowTotal(row, "mixed") - subtotal) <= 0.05);
  });
});

describe("sticky iva_monto on price edit (PDF Salta)", () => {
  it("after clearSticky + price change, iva follows suggested %", () => {
    const row = {
      iva_pct: "21%",
      "invoice_line_ids/quantity": "5",
      "invoice_line_ids/price_unit": "8628,49",
      iva_monto: "9059,91",
    };
    computeRowTotal(row, "line");
    assert.ok(Math.abs(toNumberLoose(row.iva_monto) - 9059.91) <= 0.05);

    row["invoice_line_ids/price_unit"] = "10799,93";
    clearStickyLineIvaOnPriceQtyEdit(row);
    computeRowTotal(row, "line");
    const expected = Math.round(5 * 10799.93 * 0.21 * 100) / 100;
    assert.ok(Math.abs(toNumberLoose(row.iva_monto) - expected) <= 0.05);
  });

  it("keeps manual iva_monto after price change", () => {
    const row = {
      iva_pct: "21%",
      "invoice_line_ids/quantity": "5",
      "invoice_line_ids/price_unit": "8628,49",
      iva_monto: "1000",
      __iva_monto_manual: true,
    };
    row["invoice_line_ids/price_unit"] = "10799,93";
    clearStickyLineIvaOnPriceQtyEdit(row);
    computeRowTotal(row, "line");
    assert.ok(Math.abs(toNumberLoose(row.iva_monto) - 1000) <= 0.02);
  });
});
