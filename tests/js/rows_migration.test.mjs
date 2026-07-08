import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { propagateAccountDown } from "../../src/facturia_matching/static/js/rows/migration.js";

describe("propagateAccountDown", () => {
  it("copies account to all lines of the same comprobante", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        "l10n_latam_document_number": "00011-00036204",
        "invoice_line_ids/account_id": "147",
        "invoice_line_ids/name": "linea 1",
      },
      {
        __comprobante_idx: 0,
        "l10n_latam_document_number": "",
        "invoice_line_ids/account_id": "",
        "invoice_line_ids/name": "linea 2",
      },
      {
        __comprobante_idx: 0,
        "l10n_latam_document_number": "",
        "invoice_line_ids/account_id": "",
        "invoice_line_ids/name": "linea 3",
      },
      {
        __comprobante_idx: 0,
        "l10n_latam_document_number": "",
        "invoice_line_ids/account_id": "",
        "invoice_line_ids/name": "linea 4",
      },
      {
        __comprobante_idx: 0,
        "l10n_latam_document_number": "",
        "invoice_line_ids/account_id": "",
        "invoice_line_ids/name": "linea 5",
      },
    ];
    propagateAccountDown(rows);
    for (let i = 1; i < rows.length; i++) {
      assert.equal(rows[i]["invoice_line_ids/account_id"], "147", `row ${i}`);
    }
  });

  it("does not overwrite an explicit account on a line", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        "l10n_latam_document_number": "00011-00036204",
        "invoice_line_ids/account_id": "147",
      },
      {
        __comprobante_idx: 0,
        "l10n_latam_document_number": "",
        "invoice_line_ids/account_id": "200",
      },
      {
        __comprobante_idx: 0,
        "l10n_latam_document_number": "",
        "invoice_line_ids/account_id": "",
      },
    ];
    propagateAccountDown(rows);
    assert.equal(rows[1]["invoice_line_ids/account_id"], "200");
    assert.equal(rows[2]["invoice_line_ids/account_id"], "147");
  });

  it("keeps accounts scoped per comprobante", () => {
    const rows = [
      {
        __comprobante_idx: 0,
        "l10n_latam_document_number": "00011-00036204",
        "invoice_line_ids/account_id": "147",
      },
      {
        __comprobante_idx: 0,
        "l10n_latam_document_number": "",
        "invoice_line_ids/account_id": "",
      },
      {
        __comprobante_idx: 1,
        "l10n_latam_document_number": "00012-00089408",
        "invoice_line_ids/account_id": "88",
      },
      {
        __comprobante_idx: 1,
        "l10n_latam_document_number": "",
        "invoice_line_ids/account_id": "",
      },
    ];
    propagateAccountDown(rows);
    assert.equal(rows[1]["invoice_line_ids/account_id"], "147");
    assert.equal(rows[3]["invoice_line_ids/account_id"], "88");
  });
});
