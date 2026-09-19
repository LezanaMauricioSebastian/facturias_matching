import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { validateRows } from "../../src/facturia_matching/static/js/validation/validateRows.js";

function baseState(rows, columns = []) {
  return { rows, columns };
}

function lineRow(overrides = {}) {
  return {
    __comprobante_idx: 0,
    partner_id: "10",
    journal_id: "20",
    l10n_latam_document_number: "00001-00000001",
    "invoice_line_ids/name": "Producto",
    "invoice_line_ids/quantity": "1",
    "invoice_line_ids/price_unit": "100",
    "invoice_line_ids/account_id": "30",
    iva_pct: "21",
    iva_monto: "21",
    __fac_iva_monto: "21",
    __fac_subtotal: "100",
    ...overrides,
  };
}

describe("validateRows", () => {
  it("requires partner_id on first row of comprobante", () => {
    const err = validateRows(
      baseState([lineRow({ partner_id: "" })])
    );
    assert.match(err, /Proveedor vacío/);
  });

  it("requires journal_id on first row of comprobante", () => {
    const err = validateRows(
      baseState([lineRow({ journal_id: "" })])
    );
    assert.match(err, /Diario vacío/);
  });

  it("requires iva_pct in line mode when a content line lacks it", () => {
    const rows = [
      lineRow({
        iva_pct: "21",
        iva_monto: "21",
        __fac_iva_monto: "21",
        __fac_subtotal: "100",
      }),
      lineRow({
        iva_pct: "",
        iva_monto: "",
        l10n_latam_document_number: "",
        __fac_iva_monto: "21",
      }),
    ];
    const err = validateRows(baseState(rows));
    assert.match(err, /IVA vacío/);
  });

  it("skips iva_pct requirement in header mode (IVA in footer)", () => {
    const row = lineRow({
      iva_pct: "",
      iva_monto: "",
      __fac_iva_monto: "210",
      __fac_subtotal: "1000",
    });
    const err = validateRows(baseState([row]));
    assert.equal(err, null);
  });

  it("requires account when line has content", () => {
    const err = validateRows(
      baseState([lineRow({ "invoice_line_ids/account_id": "" })])
    );
    assert.match(err, /Cuenta contable vacía/);
  });

  it("rejects invalid document number", () => {
    // Must not be normalizable (e.g. "1-2" → 00001-00000002 would pass).
    const err = validateRows(
      baseState([lineRow({ l10n_latam_document_number: "12-34-56" })])
    );
    assert.match(err, /Número de documento inválido/);
  });

  it("normalizes and accepts valid rows", () => {
    const row = lineRow({ invoice_date: "2024-01-15" });
    const err = validateRows(baseState([row]));
    assert.equal(err, null);
    assert.equal(row.invoice_date, "15/01/2024");
  });

  it("allows mixed 1-line and multi-line comprobantes in the same proceso", () => {
    const rows = [
      lineRow({ __comprobante_idx: 0 }),
      lineRow({
        __comprobante_idx: 1,
        l10n_latam_document_number: "00002-00000002",
      }),
      lineRow({
        __comprobante_idx: 1,
        l10n_latam_document_number: "",
        "invoice_line_ids/name": "linea 2",
      }),
    ];
    const err = validateRows(baseState(rows));
    assert.equal(err, null);
  });
});