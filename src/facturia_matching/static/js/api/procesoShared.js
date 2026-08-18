import {
  mergeEtiquetaOptions,
  mergeProductOptions,
  normalizeDateFieldsInRows,
  normalizeNumericFieldsInRows,
  dropInvalidCatalogIds,
} from "../utils/index.js";
import {
  migrateRowKeys,
  propagateAccountDown,
  ensureAddOtroImpuestoActionColumn,
  restoreExtraOtroImpuestoColumns,
  resetExtraOtroImpuestoColumns,
} from "../rows/index.js";
import {
  migrateFacIvaMontos,
  migrateLegacyComprobanteIva,
  propagateSingleFooterIvaToLines,
  sanitizeInflatedLineAmounts,
} from "../comprobanteTax/index.js";
import { renderComprobantes, updateComprobanteFooters } from "../comprobanteView/index.js";
import { PURCHASE_COLUMN_KEYS, odooImportButtonLabel, updateOdooTenantBadge } from "./bootstrap.js";
import { renderSummary, scheduleAutoSave } from "./autoSave.js";

function cachePurchaseColumnDefs(state) {
  if (state.purchaseColumnDefs?.length) return;
  state.purchaseColumnDefs = (state.columns || []).filter((c) =>
    PURCHASE_COLUMN_KEYS.includes(c.key)
  );
}

const QTY_KEY = "invoice_line_ids/quantity";
const PRICE_KEY = "invoice_line_ids/price_unit";
const UM_KEY = "__um_empresa";
const TRAILING_PURCHASE_KEYS = ["__qty_pedido", "__qty_recibido", "__oc_match_note"];

function defForKey(state, key) {
  return (state.purchaseColumnDefs || []).find((c) => c.key === key);
}

function insertUmBetweenQtyAndPrice(state, umDef) {
  if (!umDef) return;
  const qtyIdx = state.columns.findIndex((c) => c.key === QTY_KEY);
  if (qtyIdx >= 0) {
    state.columns.splice(qtyIdx + 1, 0, umDef);
    return;
  }
  const priceIdx = state.columns.findIndex((c) => c.key === PRICE_KEY);
  const at = priceIdx >= 0 ? priceIdx : state.columns.length;
  state.columns.splice(at, 0, umDef);
}

function insertTrailingPurchaseColumns(state, trailingDefs) {
  if (!trailingDefs.length) return;
  const subIdx = state.columns.findIndex((c) => c.key === "__subtotal");
  const totalIdx = state.columns.findIndex((c) => c.key === "__total_linea");
  const insertAt = subIdx >= 0 ? subIdx : totalIdx >= 0 ? totalIdx : state.columns.length;
  state.columns.splice(insertAt, 0, ...trailingDefs);
}

export function syncPurchaseColumns(state, purchaseMatching = {}) {
  cachePurchaseColumnDefs(state);
  const fromFlag = !!(purchaseMatching.enabled && purchaseMatching.show_purchase_columns);
  // Tras F5 sin candidatos en memoria el flag puede venir false; igual mostrar
  // si las filas ya tienen UM / vínculo OC (misma regla que compute_show_purchase_columns).
  const fromRows =
    !!purchaseMatching.enabled &&
    (state.rows || []).some(
      (r) =>
        String(r?.__um_empresa || "").trim() ||
        String(r?.__oc_line_id || "").trim() ||
        String(r?.__oc_match_note || "").trim().startsWith("OC ")
    );
  const showCols = fromFlag || fromRows;

  state.columns = state.columns.filter((c) => !PURCHASE_COLUMN_KEYS.includes(c.key));
  if (showCols) {
    insertUmBetweenQtyAndPrice(state, defForKey(state, UM_KEY));
    insertTrailingPurchaseColumns(
      state,
      TRAILING_PURCHASE_KEYS.map((k) => defForKey(state, k)).filter(Boolean)
    );
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
  if (data.odoo_profile && !state.odooProfileLocked) {
    const prof = data.odoo_profile;
    state.odooProfile =
      prof === "aliare" ? "aliare" : prof === "sudata" ? "sudata" : "default";
    if (refs?.btnOdooImport) {
      refs.btnOdooImport.textContent = odooImportButtonLabel(state);
    }
  }
  updateOdooTenantBadge(state, refs);
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
  propagateSingleFooterIvaToLines(state.rows);
  sanitizeInflatedLineAmounts(state.rows);
  resetExtraOtroImpuestoColumns(state);
  restoreExtraOtroImpuestoColumns(state, data.extra_tax_indices);
  state.purchaseMatching = data.purchase_matching || {};
  syncPurchaseColumns(state, state.purchaseMatching);
  dropInvalidCatalogIds(state);
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
