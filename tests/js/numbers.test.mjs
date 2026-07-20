import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { toNumberLoose } from "../../src/facturia_matching/static/js/utils/numbers.js";
import { sanitizeInflatedLineAmounts } from "../../src/facturia_matching/static/js/comprobanteTax/migration.js";

describe("toNumberLoose", () => {
  it("keeps US decimals when integer part has more than 3 digits", () => {
    assert.equal(toNumberLoose("1457.256"), 1457.256);
  });

  it("still collapses es-AR thousands", () => {
    assert.equal(toNumberLoose("45.000"), 45000);
    assert.equal(toNumberLoose("1.657.755"), 1657755);
    assert.equal(toNumberLoose("1.234"), 1234);
  });

  it("parses comma decimals without ambiguity", () => {
    assert.equal(toNumberLoose("15,175"), 15.175);
    assert.equal(toNumberLoose("1457,256"), 1457.256);
  });
});

describe("sanitizeInflatedLineAmounts + FacturIA liters", () => {
  it("does not crush 15,175 L × 1457,256 into 1 × 1,46", () => {
    const rows = [
      {
        "invoice_line_ids/quantity": "15,175",
        "invoice_line_ids/price_unit": "1457,256",
        __fac_subtotal: "22113.86",
        __comprobante_idx: 0,
      },
    ];
    assert.equal(sanitizeInflatedLineAmounts(rows), 0);
    assert.equal(rows[0]["invoice_line_ids/quantity"], "15,175");
    assert.equal(rows[0]["invoice_line_ids/price_unit"], "1457,256");
  });

  it("keeps raw US price with >3 integer digits", () => {
    const rows = [
      {
        "invoice_line_ids/quantity": "15,175",
        "invoice_line_ids/price_unit": "1457.256",
        __fac_subtotal: "22113.86",
        __comprobante_idx: 0,
      },
    ];
    assert.equal(sanitizeInflatedLineAmounts(rows), 0);
    assert.equal(toNumberLoose(rows[0]["invoice_line_ids/price_unit"]), 1457.256);
  });
});
