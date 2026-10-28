import { apiContextBody, apiOdooQueryParams, buildApiQuery } from "../utils/index.js";
import { mergePartnerOptions } from "./partners.js";

/** Crea proveedor o producto en Odoo Aliare y lo agrega al catálogo del combobox. */
export async function createOdooCatalogItem(state, kind, { name, vat } = {}) {
  const path = kind === "product" ? "/api/products" : "/api/partners";
  const body = {
    name: String(name || "").trim(),
    ...apiContextBody(state),
  };
  if (kind !== "product" && String(vat || "").trim()) body.vat = String(vat).trim();
  const res = await fetch(`${path}${buildApiQuery(apiOdooQueryParams(state))}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data?.detail;
    const msg =
      typeof detail === "string"
        ? detail
        : data?.error || "No se pudo crear en Odoo";
    throw new Error(msg);
  }
  if (data?.id == null) throw new Error("Odoo no devolvió un id.");
  const created = {
    id: data.id,
    name: String(data.name || body.name),
  };
  if (data.vat) created.vat = data.vat;
  if (kind === "product") {
    if (!state.options) state.options = {};
    const prev = Array.isArray(state.options.productos) ? state.options.productos : [];
    state.options.productos = [...prev.filter((o) => String(o?.id) !== String(created.id)), created];
  } else {
    mergePartnerOptions(state, [created]);
  }
  return created;
}
