import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  buildExcelPreviewCsv,
  buildPepeGastosCsv,
  csvBodyOnly,
  excelPreviewCellValue,
  excelPreviewColumns,
  PEPE_GASTOS_COLUMNS,
  pepeGastosValuesFromRow,
} from "../../src/facturia_matching/static/js/api/export.js";

describe("csvBodyOnly", () => {
  it("strips the header row and keeps the body", () => {
    const csv = "a,b\n1,2\n3,4\n";
    assert.equal(csvBodyOnly(csv), "1,2\n3,4\n");
  });

  it("strips UTF-8 BOM before the header", () => {
    const csv = "\ufeffcol1,col2\nrow1,row2\n";
    assert.equal(csvBodyOnly(csv), "row1,row2\n");
  });

  it("handles CRLF", () => {
    const csv = "h1,h2\r\nv1,v2\r\n";
    assert.equal(csvBodyOnly(csv), "v1,v2\r\n");
  });

  it("returns empty when there is only a header", () => {
    assert.equal(csvBodyOnly("a,b"), "");
    assert.equal(csvBodyOnly("a,b\n"), "");
  });
});

describe("buildExcelPreviewCsv", () => {
  const state = {
    excelUser: true,
    columns: [
      { key: "partner_id", label: "Proveedor", type: "selection", options_key: "proveedores" },
      { key: "invoice_line_ids/name", label: "Descripción", type: "text" },
      { key: "invoice_line_ids/quantity", label: "Cantidad", type: "numeric" },
      { key: "__add_otro_impuesto", label: "+", type: "header_action" },
      { key: "__solo_encabezado", label: "Solo", type: "checkbox" },
    ],
    options: {
      proveedores: [{ id: "p1", name: "ACME SA" }],
    },
    rows: [
      {
        partner_id: "p1",
        "Nombre de Proveedor": "ACME Match Excel",
        "invoice_line_ids/name": 'Cable, "rojo"',
        "invoice_line_ids/quantity": "2",
      },
    ],
  };

  it("skips UI-only columns", () => {
    const keys = excelPreviewColumns(state).map((c) => c.key);
    assert.deepEqual(keys, ["partner_id", "invoice_line_ids/name", "invoice_line_ids/quantity"]);
  });

  it("uses excel match name for proveedor", () => {
    assert.equal(
      excelPreviewCellValue(state, state.columns[0], state.rows[0], 0),
      "ACME Match Excel"
    );
  });

  it("builds preview CSV with labels and escaped cells", () => {
    const csv = buildExcelPreviewCsv(state, { includeHeader: true });
    assert.ok(csv.startsWith("\ufeff"));
    assert.match(csv, /Proveedor,Descripción,Cantidad/);
    assert.match(csv, /ACME Match Excel/);
    assert.match(csv, /"Cable, ""rojo"""/);
    assert.doesNotMatch(csv, /tax_ids|__add_otro_impuesto/);
  });

  it("body-only omits header and BOM", () => {
    const full = buildExcelPreviewCsv(state, { includeHeader: true });
    const body = csvBodyOnly(full);
    assert.ok(!body.startsWith("\ufeff"));
    assert.ok(!body.startsWith("Proveedor"));
    assert.match(body, /ACME Match Excel/);
  });
});

describe("Pepe Gastos CSV", () => {
  const state = {
    excelUser: true,
    excelAlias: "pepe",
    options: { proveedores: [] },
    rows: [
      {
        __comprobante_idx: 1,
        invoice_date: "02/01/2026",
        invoice_date_due: "15/01/2026",
        __excel_proveedor: "AADI CAPIF",
        __excel_concepto: "Servicios",
        __excel_forma_pago: "Santander",
        __excel_categoria: "Gastos Fijos",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "99000",
        "invoice_line_ids/name": "Canon",
      },
    ],
  };

  it("has the 12 Gastos columns", () => {
    assert.equal(PEPE_GASTOS_COLUMNS.length, 12);
    assert.equal(PEPE_GASTOS_COLUMNS[0], "Mes");
    assert.equal(PEPE_GASTOS_COLUMNS[11], "Estado de Deuda");
  });

  it("maps a proceso row to Pepe values", () => {
    const vals = pepeGastosValuesFromRow(state, state.rows[0], 0);
    assert.equal(vals[0], "enero");
    assert.equal(vals[2], "AADI CAPIF");
    assert.equal(vals[3], "Servicios");
    assert.equal(vals[4], "02/01/2026");
    assert.match(vals[5], /99\.000/);
    assert.equal(vals[8], "Santander");
    assert.equal(vals[9], "Gastos Fijos");
    assert.equal(vals[11], "Pagado");
  });

  it("buildExcelPreviewCsv uses Pepe layout when excelAlias=pepe", () => {
    const csv = buildExcelPreviewCsv(state, { includeHeader: true });
    assert.match(csv, /Mes,Sucursal,Proveedor,Concepto,Fecha,Monto/);
    assert.match(csv, /AADI CAPIF/);
    assert.match(csv, /Santander/);
  });

  it("buildPepeGastosCsv works explicitly", () => {
    const csv = buildPepeGastosCsv(state, { includeHeader: true });
    assert.ok(csv.startsWith("\ufeff"));
    assert.match(csv, /Categoría gasto,Observación,Estado de Deuda/);
  });
});
