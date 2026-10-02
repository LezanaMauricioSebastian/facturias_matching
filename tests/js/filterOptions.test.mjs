import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { filterOptions } from "../../src/facturia_matching/static/js/utils/options.js";

describe("filterOptions", () => {
  const proveedores = [
    { id: 101, name: "GORDON DAN ALAN", vat: "20413168091" },
    { id: 102, name: "SALTA REFRESCOS SA", vat: "30-12345678-9" },
    { id: 103, name: "Otro Proveedor" },
  ];

  it("matches all tokens in any order (Gordo… → GORDON DAN ALAN)", () => {
    const hits = filterOptions(proveedores, "gordo dan alan");
    assert.equal(hits.length, 1);
    assert.equal(hits[0].id, 101);
  });

  it("matches reordered tokens", () => {
    const hits = filterOptions(proveedores, "alan gordon");
    assert.equal(hits.length, 1);
    assert.equal(hits[0].name, "GORDON DAN ALAN");
  });

  it("matches CUIT digits", () => {
    const hits = filterOptions(proveedores, "20413168091");
    assert.equal(hits.length, 1);
    assert.equal(hits[0].id, 101);
  });

  it("rejects when a token is missing", () => {
    const hits = filterOptions(proveedores, "gordon xyz");
    assert.equal(hits.length, 0);
  });

  it("returns the first page when query is empty", () => {
    const hits = filterOptions(proveedores, "", 2);
    assert.equal(hits.length, 2);
  });
});
