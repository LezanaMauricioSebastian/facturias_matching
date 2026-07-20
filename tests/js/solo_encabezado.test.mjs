import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { isSoloEncabezado } from "../../src/facturia_matching/static/js/singleLine/groups.js";
import { columnsForTaxMode } from "../../src/facturia_matching/static/js/table/columns.js";
import { collapseGroupAtRow, prepareSoloEncabezadoRow } from "../../src/facturia_matching/static/js/singleLine/collapse.js";
import { computeRowTotal } from "../../src/facturia_matching/static/js/rows/totals.js";

describe("isSoloEncabezado", () => {
  it("accepts truthy flag shapes", () => {
    assert.equal(isSoloEncabezado({ __solo_encabezado: true }), true);
    assert.equal(isSoloEncabezado({ __solo_encabezado: 1 }), true);
    assert.equal(isSoloEncabezado({ __solo_encabezado: "true" }), true);
    assert.equal(isSoloEncabezado({ __solo_encabezado: false }), false);
    assert.equal(isSoloEncabezado({}), false);
  });
});

describe("columnsForTaxMode + Solo encabezado", () => {
  const columns = [
    { key: "invoice_line_ids/price_unit" },
    { key: "__subtotal" },
    { key: "iva_monto" },
    { key: "otros_impuestos_monto" },
    { key: "__total_linea" },
  ];

  it("hides Subtotal unless soloEncabezado", () => {
    const without = columnsForTaxMode(columns, "header", { soloEncabezado: false });
    assert.ok(!without.some((c) => c.key === "__subtotal"));
    const withSolo = columnsForTaxMode(columns, "header", { soloEncabezado: true });
    assert.ok(withSolo.some((c) => c.key === "__subtotal"));
  });

  it("shows IVA and otros montos columns in solo encabezado", () => {
    const withSolo = columnsForTaxMode(columns, "header", { soloEncabezado: true });
    assert.ok(withSolo.some((c) => c.key === "iva_monto"));
    assert.ok(withSolo.some((c) => c.key === "otros_impuestos_monto"));
    const without = columnsForTaxMode(columns, "header", { soloEncabezado: false });
    assert.ok(!without.some((c) => c.key === "iva_monto"));
    assert.ok(!without.some((c) => c.key === "otros_impuestos_monto"));
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
});
