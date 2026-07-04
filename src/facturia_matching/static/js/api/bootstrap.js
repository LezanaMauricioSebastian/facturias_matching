import {
  buildApiQuery,
  normalizeIvaPctValue,
  syncOdooProfileState,
  hasExplicitOdooProfileOverride,
  activeOdooProfile,
} from "../utils/index.js";
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
  return odooTenantBadgeLabel(state);
}

/** Etiqueta chica del tenant Odoo activo (ej. Odoo Central Ticket). */
export function odooTenantBadgeLabel(state) {
  const profile = activeOdooProfile(state);
  if (hasExplicitOdooProfileOverride(state)) {
    if (profile === "aliare") return "Odoo Aliare";
    if (profile === "sudata") return "Odoo Sudata";
    return "Odoo Dinner";
  }

  const empresa = String(state?.empresa || "").trim();
  const labels = state?.empresaOdooLabels || {};
  if (empresa && labels[empresa]) return labels[empresa];

  if (profile === "aliare") return "Odoo Aliare";
  if (profile === "sudata") return "Odoo Sudata";
  return "Odoo Dinner";
}

export function updateOdooTenantBadge(state, refs) {
  const badge = refs?.odooTenantBadge;
  if (!badge) return;
  const profile = activeOdooProfile(state);
  const label = odooTenantBadgeLabel(state);
  badge.textContent = label;
  badge.dataset.profile = profile;
  badge.hidden = false;
  badge.title = `Destino de importación: ${label}`;
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
  state.empresaOdooProfiles = boot?.empresa_odoo_profiles || {};
  state.empresaOdooLabels = boot?.empresa_odoo_labels || {};
  if (empresa) state.empresa = empresa;
  syncOdooProfileState(state, urlParams);
  if (!state.odooProfileLocked) {
    const bootProfile = boot?.odoo_profile;
    state.odooProfile =
      bootProfile === "aliare" ? "aliare" : bootProfile === "sudata" ? "sudata" : "default";
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
