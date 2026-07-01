import { buildApiQuery, normalizeIvaPctValue, resolveOdooProfileParam, activeOdooProfile } from "../utils/index.js";
import {
  ensureOtroImpuestoColumns,
  ensureAddOtroImpuestoActionColumn,
} from "../rows/index.js";

const SOLO_ENCABEZADO_KEY = "__solo_encabezado";

function ensureSoloEncabezadoColumn(state) {
  if (state.columns.some((c) => c.key === SOLO_ENCABEZADO_KEY)) return;
  state.columns.unshift({
    key: SOLO_ENCABEZADO_KEY,
    label: "Solo encabezado",
    type: "checkbox",
    readonly: true,
    editable: false,
  });
}

export function odooImportButtonLabel() {
  return "Importar a Odoo";
}

export function odooImportTargetName(state) {
  const profile = activeOdooProfile(state);
  if (profile === "aliare") return "Odoo Aliare";
  if (profile === "sudata") return "Odoo Sudata";
  return "Odoo Dinner";
}

export async function loadMetaAndOptions(state, urlParams = {}) {
  const empresa = urlParams.empresa || "";
  const odoo_profile = urlParams.odoo_profile || "";
  const odoo_cloud = urlParams.odoo_cloud || "";
  const boot = await fetch(
    `/api/bootstrap${buildApiQuery({ empresa, odoo_profile, odoo_cloud })}`
  ).then((r) => r.json());
  const meta = boot?.metadata || {};
  const options = boot?.options || {};
  const bootProfile = boot?.odoo_profile;
  state.odooProfile =
    bootProfile === "aliare" ? "aliare" : bootProfile === "sudata" ? "sudata" : "default";
  if (odoo_cloud || odoo_profile) {
    state.odooProfile = resolveOdooProfileParam(odoo_profile, odoo_cloud);
  }
  state.columns = meta.columns || [];
  state.output_headers = meta.output_headers || [];
  state.columns = [...state.columns, { key: "__total_linea", label: "Total", type: "computed" }];
  ensureOtroImpuestoColumns(state, 1);
  ensureAddOtroImpuestoActionColumn(state);
  ensureSoloEncabezadoColumn(state);
  state.purchaseColumnDefs = (state.columns || []).filter((c) =>
    PURCHASE_COLUMN_KEYS.includes(c.key)
  );
  state.options = { ...state.options, ...(options || {}) };
  if (Array.isArray(state.options.iva_options)) {
    state.options.iva_options = state.options.iva_options.map((o) => normalizeIvaPctValue(o));
  }
}

/** Claves de columnas OC; usadas también en procesoShared. */
export const PURCHASE_COLUMN_KEYS = [
  "__qty_pedido",
  "__qty_recibido",
  "__um_proveedor",
  "__um_empresa",
  "__oc_match_note",
];
