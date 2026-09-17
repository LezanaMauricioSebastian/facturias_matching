import {
  mergeEtiquetaOptions,
  mergeProductOptions,
  normalizeDateFieldsInRows,
  normalizeNumericFieldsInRows,
  dropInvalidCatalogIds,
  buildApiQuery,
  currentEmpresa,
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
import { clearFacturiaRawCache, setActiveProcessTab } from "../facturiaRaw/tab.js";

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

/** Carga proveedores/productos del Sheet en state.options (combobox). */
export async function loadExcelPadronOptions(state, { force = true } = {}) {
  const empresa = currentEmpresa(state);
  const companyId =
    state?.excelPadron?.company_id != null && state.excelPadron.company_id !== ""
      ? state.excelPadron.company_id
      : empresa && /^\d+$/.test(empresa)
        ? Number(empresa)
        : 0;
  const url = `/api/padron-excel/data${buildApiQuery({
    company_id: companyId,
    empresa: empresa || undefined,
    force: force ? "1" : "0",
  })}`;
  const res = await fetch(url);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data?.detail || "No se pudo cargar el padrón Excel");
  }

  const proveedores = [];
  const cuitMap = {};
  const seenProv = new Set();
  for (const p of data.proveedores || []) {
    const name = String(p?.razon_social || p?.nombre_fantasia || "").trim();
    if (!name || seenProv.has(name.toLowerCase())) continue;
    seenProv.add(name.toLowerCase());
    proveedores.push({ id: name, name });
    const cuit = String(p?.cuit || "").trim();
    if (cuit) cuitMap[name] = cuit;
  }

  const productos = [];
  const seenProd = new Set();
  for (const p of data.productos || []) {
    const name = String(p?.nombre || p?.match || "").trim();
    if (!name || seenProd.has(name.toLowerCase())) continue;
    seenProd.add(name.toLowerCase());
    productos.push({ id: name, name });
  }

  const conceptos = [];
  const seenConc = new Set();
  for (const c of data.conceptos || []) {
    const name = String(typeof c === "string" ? c : c?.nombre || c?.name || "").trim();
    if (!name || seenConc.has(name.toLowerCase())) continue;
    seenConc.add(name.toLowerCase());
    conceptos.push({ id: name, name });
  }

  state.options = {
    ...state.options,
    proveedores,
    productos,
    conceptos,
    proveedores_cuit_map: cuitMap,
  };
  state.excelPadron = {
    ...(state.excelPadron || {}),
    company_id: companyId,
    sheet_error: data.sheet_error || null,
    row_count: data.row_count || null,
  };
  state.padronLoading = false;
  state.productosLoading = false;
  syncExcelConceptoColumn(state);
  return data;
}

const EXCEL_CONCEPTO_COL = {
  key: "__excel_concepto",
  label: "Concepto",
  type: "selection",
  options_key: "conceptos",
  editable: true,
  readonly: false,
};

/** Columnas útiles para cliente Excel (sin Rubros/Diario/Cuenta/OC de Odoo). */
const EXCEL_VISIBLE_KEYS = new Set([
  "__solo_encabezado",
  "l10n_latam_document_number",
  "CUIT",
  "partner_id",
  "l10n_latam_document_type_id",
  "invoice_date",
  "invoice_date_due",
  "invoice_line_ids/name",
  "invoice_line_ids/product_id",
  "__excel_concepto",
  "invoice_line_ids/quantity",
  "invoice_line_ids/price_unit",
  "__subtotal",
  "iva_pct",
  "iva_monto",
  "otros_impuestos",
  "otros_impuestos_monto",
  "__total_linea",
  "__add_otro_impuesto",
]);

function isExcelVisibleColumnKey(key) {
  const k = String(key || "");
  if (EXCEL_VISIBLE_KEYS.has(k)) return true;
  if (k.startsWith("otros_impuestos")) return true;
  return false;
}

/**
 * En excel_user: deja solo columnas del cliente + Concepto.
 * Fuera de excel: restaura el set completo de bootstrap.
 */
export function syncExcelVisibleColumns(state) {
  if (!state?.columns) return;

  if (!state.excelUser) {
    if (state._columnsExcelBase?.length) {
      state.columns = state._columnsExcelBase.map((c) => ({ ...c }));
      state._columnsExcelBase = null;
    } else {
      state.columns = state.columns.filter((c) => c.key !== "__excel_concepto");
    }
    return;
  }

  if (!state._columnsExcelBase?.length) {
    state._columnsExcelBase = state.columns
      .filter((c) => c.key !== "__excel_concepto")
      .map((c) => ({ ...c }));
  }

  const filtered = state._columnsExcelBase
    .filter((c) => isExcelVisibleColumnKey(c.key))
    .map((c) => ({ ...c }));

  // Conservar columnas dinámicas de otros impuestos ya abiertas.
  for (const c of state.columns || []) {
    const k = c.key;
    if (!isExcelVisibleColumnKey(k)) continue;
    if (filtered.some((x) => x.key === k)) continue;
    if (String(k).startsWith("otros_impuestos") || k === "__add_otro_impuesto") {
      filtered.push({ ...c });
    }
  }

  if (!filtered.some((c) => c.key === "__excel_concepto")) {
    const afterProd = filtered.findIndex((c) => c.key === "invoice_line_ids/product_id");
    const afterLabel = filtered.findIndex((c) => c.key === "invoice_line_ids/name");
    const at =
      afterProd >= 0 ? afterProd + 1 : afterLabel >= 0 ? afterLabel + 1 : filtered.length;
    filtered.splice(at, 0, { ...EXCEL_CONCEPTO_COL });
  }
  state.columns = filtered;
}

/** @deprecated usar syncExcelVisibleColumns */
export function syncExcelConceptoColumn(state) {
  syncExcelVisibleColumns(state);
}

export function applyProcesoPayload(state, refs, data, pn, empresa) {
  state.processNumber = pn;
  state.empresa = empresa || "";
  clearFacturiaRawCache(state);
  if (refs) setActiveProcessTab(refs, "edit");
  state.excelUser = !!(data.excel_user || state.excelUser);
  state.excelPadron = data.excel_padron || null;
  if (data.odoo_profile && !state.odooProfileLocked && !state.excelUser) {
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
  state.carouselIndex = 0;
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
  state.purchaseMatching = state.excelUser
    ? { enabled: false }
    : data.purchase_matching || {};
  syncPurchaseColumns(state, state.purchaseMatching);
  // En Excel los ids son nombres del Sheet; no limpiar contra catálogo Odoo.
  if (!state.excelUser) dropInvalidCatalogIds(state);
  else syncExcelConceptoColumn(state);
}

/** Oculta Import Odoo / muestra Re-matchear cuando excel_user=1. Restaurar original queda en ambos modos. */
export function applyExcelUserChrome(state, refs) {
  if (!state?.excelUser) {
    if (refs?.btnOdooImport) refs.btnOdooImport.hidden = false;
    if (refs?.btnRevertir) {
      refs.btnRevertir.textContent = "Restaurar original";
      refs.btnRevertir.title = "";
      refs.btnRevertir.hidden = false;
    }
    if (refs?.btnRematchExcel) {
      refs.btnRematchExcel.hidden = true;
      refs.btnRematchExcel.disabled = true;
    }
    syncExcelConceptoColumn(state);
    return;
  }
  if (refs?.btnOdooImport) {
    refs.btnOdooImport.hidden = true;
    refs.btnOdooImport.disabled = true;
  }
  if (refs?.btnRevertir) {
    refs.btnRevertir.textContent = "Restaurar original";
    refs.btnRevertir.title = "Descarta la conversión guardada y regenera desde FacturIA";
    refs.btnRevertir.hidden = false;
  }
  if (refs?.btnRematchExcel) {
    refs.btnRematchExcel.hidden = false;
    refs.btnRematchExcel.title =
      "Vuelve a leer el Sheet y recalcula proveedores / productos / conceptos";
    const hasRows = !!(state.rows && state.rows.length);
    refs.btnRematchExcel.disabled = !hasRows && !String(state.processNumber || "").trim();
  }
  if (refs?.actionTitle) {
    refs.actionTitle.textContent =
      "Matching con padrón Excel/Sheets — revisá y descargá el CSV.";
  }
  syncExcelConceptoColumn(state);
  updateOdooTenantBadge(state, refs);
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
