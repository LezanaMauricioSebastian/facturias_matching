import { buildApiQuery, apiOdooQueryParams, currentEmpresa } from "../utils/index.js";

/** Búsqueda live de proveedores en Odoo (catálogo precargado incompleto). */
export async function searchPartnersRemote(state, query, limit = 50) {
  const q = String(query || "").trim();
  if (q.length < 2 || state?.excelUser) return [];
  const empresa = currentEmpresa(state);
  const url = `/api/partners/search${buildApiQuery({
    q,
    limit,
    empresa,
    ...apiOdooQueryParams(state),
  })}`;
  const res = await fetch(url);
  if (!res.ok) return [];
  const data = await res.json().catch(() => ({}));
  return Array.isArray(data?.proveedores) ? data.proveedores : [];
}

/** Une hits remotos al catálogo en memoria (para labels / CUIT). */
export function mergePartnerOptions(state, remote) {
  if (!state.options) state.options = {};
  const prev = Array.isArray(state.options.proveedores) ? state.options.proveedores : [];
  const byId = new Map();
  for (const o of prev) {
    if (o?.id != null) byId.set(String(o.id), o);
  }
  for (const o of remote || []) {
    if (o?.id == null) continue;
    byId.set(String(o.id), o);
  }
  state.options.proveedores = [...byId.values()];
}
