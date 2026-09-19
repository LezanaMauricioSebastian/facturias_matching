import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { isSoloEncabezado, isEncabezadoOneLineUi } from "../../src/facturia_matching/static/js/singleLine/groups.js";
import { columnsForTaxMode } from "../../src/facturia_matching/static/js/table/columns.js";
import {
  collapseGroupAtRow,
  prepareSoloEncabezadoRow,
  expandSoloEncabezadoAtRow,
  applySoloEncabezadoToAll,
  allComprobantesAreSoloEncabezado,
} from "../../src/facturia_matching/static/js/singleLine/collapse.js";
import {
  classifyProcesoLineMode,
  mixedProcesoLineModeError,
} from "../../src/facturia_matching/static/js/singleLine/procesoMode.js";
import { computeRowTotal } from "../../src/facturia_matching/static/js/rows/totals.js";
import { lineBase } from "../../src/facturia_matching/static/js/comprobanteTax/lineCalc.js";
import { renderFooterHtml } from "../../src/facturia_matching/static/js/comprobanteView/footer.js";
import { toNumberLoose } from "../../src/facturia_matching/static/js/utils/index.js";

describe("isSoloEncabezado", () => {
  it("accepts truthy flag shapes", () => {
    assert.equal(isSoloEncabezado({ __solo_encabezado: true }), true);
    assert.equal(isSoloEncabezado({ __solo_encabezado: 1 }), true);
    assert.equal(isSoloEncabezado({ __solo_encabezado: "true" }), true);
    assert.equal(isSoloEncabezado({ __solo_encabezado: false }), false);
    assert.equal(isSoloEncabezado({}), false);
  });
});

describe("isEncabezadoOneLineUi", () => {
  it("true for tilde or __ui_one_line", () => {
    assert.equal(isEncabezadoOneLineUi({ __solo_encabezado: true }), true);
    assert.equal(isEncabezadoOneLineUi({ __ui_one_line: true }), true);
    assert.equal(isEncabezadoOneLineUi({}), false);
  });
});

describe("columnsForTaxMode + 1 línea / multi", () => {
  const columns = [
    { key: "invoice_line_ids/price_unit" },
    { key: "__subtotal" },
    { key: "iva_monto" },
    { key: "otros_impuestos_monto" },
    { key: "__total_linea" },
  ];

  it("always shows Subtotal; Total stays visible", () => {
    const without = columnsForTaxMode(columns, "header", { oneLine: false });
    assert.ok(without.some((c) => c.key === "__subtotal"));
    assert.ok(without.some((c) => c.key === "__total_linea"));
    const withOne = columnsForTaxMode(columns, "header", { oneLine: true });
    assert.ok(withOne.some((c) => c.key === "__subtotal"));
  });

  it("1 línea: muestra montos en la fila (sin pie)", () => {
    const withOne = columnsForTaxMode(columns, "header", { oneLine: true });
    assert.ok(withOne.some((c) => c.key === "iva_monto"));
    assert.ok(withOne.some((c) => c.key === "otros_impuestos_monto"));
  });

  it("multi-línea: oculta montos (van al pie)", () => {
    const without = columnsForTaxMode(columns, "header", { oneLine: false });
    assert.ok(!without.some((c) => c.key === "iva_monto"));
    assert.ok(!without.some((c) => c.key === "otros_impuestos_monto"));
  });

  it("hides otros impuestos monto columns in multi-line", () => {
    const cols = columnsForTaxMode(
      [
        { key: "otros_impuestos" },
        { key: "otros_impuestos_monto" },
        { key: "otros_impuestos_2" },
        { key: "otros_impuestos_2_monto" },
      ],
      "line",
      { oneLine: false }
    );
    assert.ok(cols.some((c) => c.key === "otros_impuestos"));
    assert.ok(cols.some((c) => c.key === "otros_impuestos_2"));
    assert.ok(!cols.some((c) => c.key === "otros_impuestos_monto"));
    assert.ok(!cols.some((c) => c.key === "otros_impuestos_2_monto"));
  });
});

describe("renderFooterHtml", () => {
  it("omits pie for 1-line comprobante", () => {
    const html = renderFooterHtml(
      { baseOdoo: 100, ivaOdoo: 21, totalOdoo: 121, ivaBreakdown: [], otrosBreakdown: [] },
      0,
      [{ __comprobante_idx: 0 }]
    );
    assert.equal(html, "");
  });

  it("renders pie for multi-line comprobante", () => {
    const html = renderFooterHtml(
      { baseOdoo: 100, ivaOdoo: 21, totalOdoo: 121, ivaBreakdown: [], otrosBreakdown: [] },
      0,
      [{ __comprobante_idx: 0 }, { __comprobante_idx: 0 }]
    );
    assert.match(html, /comprobanteFooter/);
    assert.match(html, /Base imponible/);
  });
});

describe("prepareSoloEncabezadoRow", () => {
  it("copies fac IVA and percepciones to line montos", () => {
    const row = {
      __fac_iva_monto: "64.481,27",
      __fac_percepciones: [{ ui_monto_key: "otros_impuestos_monto", monto: "1.500,00" }],
    };
    prepareSoloEncabezadoRow(row);
    assert.equal(row.__solo_encabezado, true);
    assert.equal(row.iva_monto, "64.481,27");
    assert.equal(row.otros_impuestos_monto, "1.500,00");
  });
});

describe("computeRowTotal solo encabezado", () => {
  it("uses line IVA and otros montos", () => {
    const row = {
      __solo_encabezado: true,
      "invoice_line_ids/quantity": "1",
      "invoice_line_ids/price_unit": "307053,66",
      iva_monto: "64481,27",
      otros_impuestos_monto: "1500",
    };
    const total = computeRowTotal(row, "header");
    assert.ok(Math.abs(total - (307053.66 + 64481.27 + 1500)) < 0.02);
  });

  it("uses line montos with __ui_one_line", () => {
    const row = {
      __ui_one_line: true,
      "invoice_line_ids/quantity": "1",
      "invoice_line_ids/price_unit": "100",
      iva_monto: "21",
      otros_impuestos_monto: "5",
    };
    assert.equal(computeRowTotal(row, "header"), 126);
  });
});

describe("Subtotal columna", () => {
  it("usa cantidad × precio aunque exista __fac_subtotal", () => {
    const row = {
      __solo_encabezado: true,
      __fac_subtotal: "1000",
      "invoice_line_ids/quantity": "2",
      "invoice_line_ids/price_unit": "150",
    };
    assert.equal(lineBase(row), 300);
  });

  it("recalcula al cambiar cantidad o precio", () => {
    const row = {
      __solo_encabezado: true,
      __fac_subtotal: "500",
      "invoice_line_ids/quantity": "1",
      "invoice_line_ids/price_unit": "200",
    };
    assert.equal(lineBase(row), 200);
    row["invoice_line_ids/quantity"] = "3";
    assert.equal(lineBase(row), 600);
    row["invoice_line_ids/price_unit"] = "250";
    assert.equal(lineBase(row), 750);
  });
});

describe("collapseGroupAtRow", () => {
  it("sets __solo_encabezado when collapsing", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        __fac_subtotal: "1000",
        "invoice_line_ids/quantity": "2",
        "invoice_line_ids/price_unit": "100",
        "invoice_line_ids/name": "A",
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "200",
        "invoice_line_ids/name": "B",
      },
    ];
    const res = collapseGroupAtRow(rows, 0);
    assert.equal(res.changed, true);
    assert.equal(rows.length, 1);
    assert.equal(rows[0].__solo_encabezado, true);
  });

  it("overwrites stale line IVA with FacturIA header IVA", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        __fac_subtotal: "1221278,23",
        __fac_iva_monto: "256468,43",
        __fac_percepciones: [{ ui_monto_key: "otros_impuestos_monto", monto: "22166,20" }],
        iva_monto: "37844,17",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "500000",
        "invoice_line_ids/name": "A",
      },
      {
        __comprobante_idx: 0,
        iva_monto: "100000",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "721278,23",
        "invoice_line_ids/name": "B",
      },
    ];
    collapseGroupAtRow(rows, 0);
    assert.equal(rows.length, 1);
    assert.ok(Math.abs(toNumberLoose(rows[0].iva_monto) - 256468.43) < 0.02);
    assert.ok(Math.abs(toNumberLoose(rows[0].otros_impuestos_monto) - 22166.2) < 0.02);
    const total = computeRowTotal(rows[0], "header");
    assert.ok(Math.abs(total - 1499912.86) < 0.05);
  });

  it("uses __fac_iva_montos when __fac_iva_monto is empty", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        __fac_subtotal: "1000",
        __fac_iva_montos: JSON.stringify({ "21": "210" }),
        iva_monto: "50",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "400",
        "invoice_line_ids/name": "A",
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "600",
        "invoice_line_ids/name": "B",
      },
    ];
    collapseGroupAtRow(rows, 0);
    assert.ok(Math.abs(toNumberLoose(rows[0].iva_monto) - 210) < 0.02);
  });

  it("stores backup and expand restores original lines", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        __fac_subtotal: "1000",
        "invoice_line_ids/quantity": "2",
        "invoice_line_ids/price_unit": "100",
        "invoice_line_ids/name": "A",
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "200",
        "invoice_line_ids/name": "B",
      },
    ];
    collapseGroupAtRow(rows, 0);
    assert.equal(rows.length, 1);
    assert.ok(Array.isArray(rows[0].__solo_encabezado_backup));
    assert.equal(rows[0].__solo_encabezado_backup.length, 2);

    const expanded = expandSoloEncabezadoAtRow(rows, 0);
    assert.equal(expanded.restored, 2);
    assert.equal(rows.length, 2);
    assert.equal(rows[0]["invoice_line_ids/name"], "A");
    assert.equal(rows[1]["invoice_line_ids/name"], "B");
    assert.equal(rows[0].__solo_encabezado, false);
    assert.equal(rows[0].__solo_encabezado_backup, undefined);
  });
});

describe("applySoloEncabezadoToAll / allComprobantesAreSoloEncabezado", () => {
  function multiGroupRows() {
    return [
      {
        __comprobante_idx: 0,
        __fac_subtotal: "100",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "50",
        "invoice_line_ids/name": "A1",
      },
      {
        __comprobante_idx: 0,
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "50",
        "invoice_line_ids/name": "A2",
      },
      {
        __comprobante_idx: 1,
        __fac_subtotal: "200",
        "invoice_line_ids/quantity": "2",
        "invoice_line_ids/price_unit": "40",
        "invoice_line_ids/name": "B1",
      },
      {
        __comprobante_idx: 1,
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "80",
        "invoice_line_ids/name": "B2",
      },
    ];
  }

  it("allComprobantesAreSoloEncabezado false when mixed or empty", () => {
    assert.equal(allComprobantesAreSoloEncabezado([]), false);
    const rows = multiGroupRows();
    assert.equal(allComprobantesAreSoloEncabezado(rows), false);
    prepareSoloEncabezadoRow(rows[0]);
    assert.equal(allComprobantesAreSoloEncabezado(rows), false);
  });

  it("applySoloEncabezadoToAll(true) collapses every multi-line group", () => {
    const rows = multiGroupRows();
    const res = applySoloEncabezadoToAll(rows, true);
    assert.equal(res.changed, true);
    assert.equal(rows.length, 2);
    assert.equal(rows[0].__comprobante_idx, 0);
    assert.equal(rows[1].__comprobante_idx, 1);
    assert.equal(rows[0].__solo_encabezado, true);
    assert.equal(rows[1].__solo_encabezado, true);
    assert.equal(allComprobantesAreSoloEncabezado(rows), true);
  });

  it("applySoloEncabezadoToAll(false) restores backups", () => {
    const rows = multiGroupRows();
    applySoloEncabezadoToAll(rows, true);
    assert.equal(rows.length, 2);
    const res = applySoloEncabezadoToAll(rows, false);
    assert.equal(res.changed, true);
    assert.equal(rows.length, 4);
    assert.equal(rows[0]["invoice_line_ids/name"], "A1");
    assert.equal(rows[1]["invoice_line_ids/name"], "A2");
    assert.equal(rows[2]["invoice_line_ids/name"], "B1");
    assert.equal(rows[3]["invoice_line_ids/name"], "B2");
    assert.equal(allComprobantesAreSoloEncabezado(rows), false);
  });
});

describe("proceso line mode by row count (1 línea / multi; mixed permitido)", () => {
  it("classifyProcesoLineMode detects encabezado, lineas and mixed", () => {
    assert.equal(
      classifyProcesoLineMode([
        { __comprobante_idx: 0 },
        { __comprobante_idx: 1 },
      ]),
      "encabezado"
    );
    assert.equal(
      classifyProcesoLineMode([
        { __comprobante_idx: 0 },
        { __comprobante_idx: 0 },
        { __comprobante_idx: 1 },
        { __comprobante_idx: 1 },
      ]),
      "lineas"
    );
    assert.equal(
      classifyProcesoLineMode([
        { __comprobante_idx: 0 },
        { __comprobante_idx: 1 },
        { __comprobante_idx: 1 },
      ]),
      "mixed"
    );
  });

  it("mixedProcesoLineModeError never blocks mixed line counts", () => {
    assert.equal(
      mixedProcesoLineModeError([
        { __comprobante_idx: 0 },
        { __comprobante_idx: 1 },
        { __comprobante_idx: 1 },
      ]),
      null
    );
    assert.equal(
      mixedProcesoLineModeError([
        { __comprobante_idx: 0 },
        { __comprobante_idx: 1 },
      ]),
      null
    );
  });
});
