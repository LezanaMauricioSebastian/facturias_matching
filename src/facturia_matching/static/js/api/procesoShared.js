import {
  mergeEtiquetaOptions,
  mergeProductOptions,
  normalizeDateFieldsInRows,
  normalizeNumericFieldsInRows,
} from "../utils/index.js";
import {
  migrateRowKeys,
  propagateAccountDown,
  ensureAddOtroImpuestoActionColumn,
  restoreExtraOtroImpuestoColumns,
  resetExtraOtroImpuestoColumns,
} from "../rows/index.js";
import { migrateFacIvaMontos, migrateLegacyComprobanteIva, sanitizeInflatedLineAmounts } from "../comprobanteTax/index.js";
import { renderComprobantes, updateComprobanteFooters } from "../comprobanteView/index.js";
import { PURCHASE_COLUMN_KEYS, odooImportButtonLabel } from "./bootstrap.js";
import { renderSummary, scheduleAutoSave } from "./autoSave.js";

function cachePurchaseColumnDefs(state) {
  if (state.purchaseColumnDefs?.length) return;
  state.purchaseColumnDefs = (state.columns || []).filter((c) =>
    PURCHASE_COLUMN_KEYS.includes(c.key)
  );
}

export function syncPurchaseColumns(state, purchaseMatching = {}) {
  cachePurchaseColumnDefs(state);
  const showCols = !!(purchaseMatching.enabled && purchaseMatching.show_purchase_columns);
  const hadPurchase = state.columns.some((c) => PURCHASE_COLUMN_KEYS.includes(c.key));

  if (showCols) {
    const missing = (state.purchaseColumnDefs || []).filter(
      (def) => !state.columns.some((c) => c.key === def.key)
    );
    if (missing.length) {
      const totalIdx = state.columns.findIndex((c) => c.key === "__total_linea");
      const insertAt = totalIdx >= 0 ? totalIdx : state.columns.length;
      state.columns.splice(insertAt, 0, ...missing);
    }
  } else if (hadPurchase) {
    state.columns = state.columns.filter((c) => !PURCHASE_COLUMN_KEYS.includes(c.key));
  }

  ensureAddOtroImpuestoActionColumn(state);
}

export function purchaseStatusPart(pm) {
  if (!pm?.enabled || !pm?.show_purchase_columns) return "";
  if (pm.rows_matched || pm.oc_detected) {
    return (
      ` · OC: ${pm.rows_matched || 0}/${pm.rows_total || 0} líneas` +
      (pm.oc_detected ? ` (${pm.oc_detected})` : "")
    );
  }
  return " · OC: sin match";
}

export function applyProcesoPayload(state, refs, data, pn, empresa) {
  state.processNumber = pn;
  state.empresa = empresa || "";
  if (data.odoo_profile) {
    const prof = data.odoo_profile;
    state.odooProfile =
      prof === "aliare" ? "aliare" : prof === "sudata" ? "sudata" : "default";
    if (refs?.btnOdooImport) {
      refs.btnOdooImport.textContent = odooImportButtonLabel(state);
    }
  }
  state.source = data.source || "generated";
  state.saveStatus = state.source === "saved" ? "synced" : "";
  state.dirty = false;
  state.rows = data.rows || [];
  for (const r of state.rows) migrateRowKeys(r);
  normalizeDateFieldsInRows(state);
  normalizeNumericFieldsInRows(state);
  propagateAccountDown(state.rows);
  migrateLegacyComprobanteIva(state.rows);
  migrateFacIvaMontos(state.rows);
  sanitizeInflatedLineAmounts(state.rows);
  resetExtraOtroImpuestoColumns(state);
  restoreExtraOtroImpuestoColumns(state, data.extra_tax_indices);
  state.purchaseMatching = data.purchase_matching || {};
  syncPurchaseColumns(state, state.purchaseMatching);
}

/** Handlers mínimos cuando buscarProceso se invoca sin el objeto completo de main. */
export function createFallbackHandlers(state, refs, setStatusFn) {
  const handlers = {
    onRerender: () => renderComprobantes(state, refs, handlers),
    onUpdateComprobanteFooters: () => updateComprobanteFooters(state, refs),
    onCollapseComprobante: () => {},
    onDeleteRow: () => {},
    onAutoSave: () => scheduleAutoSave(state, refs, setStatusFn),
  };
  return handlers;
}

export function resolveHandlers(handlers, state, refs, setStatusFn) {
  return handlers || createFallbackHandlers(state, refs, setStatusFn);
}

export function updateSummaryFromState(refs, state) {
  renderSummary(refs, state);
}
