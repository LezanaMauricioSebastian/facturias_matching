import { apiContextBody, apiOdooQueryParams, buildApiQuery } from "../utils/index.js";
import { groupBounds } from "../singleLine/index.js";
import { renderComprobantes } from "../comprobanteView/index.js";
import { clearAutoSaveTimer } from "./autoSave.js";
import {
  applyProcesoPayload,
  applyExcelUserChrome,
  loadExcelPadronOptions,
  purchaseStatusPart,
  updateSummaryFromState,
} from "./procesoShared.js";
import { fetchProcesoPayload } from "./proceso.js";

const UOM_ROW_KEYS = [
  "__um_proveedor",
  "__um_empresa",
  "__um_empresa_id",
  "__qty_original",
  "__qty_escalada",
  "__um_factor",
  "__um_note",
  "__product_suggested",
  "invoice_line_ids/quantity",
  "invoice_line_ids/product_id",
];

function cacheProductUoms(state, productId, uoms) {
  if (!state.uomOptionsByProductId) state.uomOptionsByProductId = {};
  const pid = String(productId || "").trim();
  if (!pid || !Array.isArray(uoms)) return;
  state.uomOptionsByProductId[pid] = uoms.map((u) => ({
    id: String(u.id ?? u.value ?? ""),
    name: String(u.name ?? u.label ?? ""),
  }));
}

function applyUomRowUpdate(row, updated) {
  for (const k of UOM_ROW_KEYS) {
    if (updated[k] !== undefined) row[k] = updated[k];
  }
}

export async function rematchPurchase(state, refs, setStatusFn, handlers, rowIdx) {
  const pn = String(state.processNumber || refs.processNumberEl?.value || "").trim();
  if (!pn) return;

  const [s, e] = groupBounds(state.rows, rowIdx);
  const rawIdx = state.rows[s]?.__comprobante_idx;
  const compIdx = rawIdx !== undefined && rawIdx !== null ? Number(rawIdx) : 0;
  const compKey = String(compIdx);

  // Limpieza optimista: al cambiar proveedor se pierde la OC anterior.
  for (let i = s; i < e; i++) {
    const row = state.rows[i];
    if (!row) continue;
    row.__overwrite_oc_price = "";
  }
  if (state.purchaseMatching) {
    const pm = state.purchaseMatching;
    if (pm.oc_searched_by_comprobante) delete pm.oc_searched_by_comprobante[compKey];
    if (pm.selected_oc_by_comprobante) delete pm.selected_oc_by_comprobante[compKey];
    if (pm.oc_candidates_by_comprobante) delete pm.oc_candidates_by_comprobante[compKey];
    if (pm.oc_provider_has_ocs_by_comprobante) delete pm.oc_provider_has_ocs_by_comprobante[compKey];
  }
  handlers?.onRerender?.();

  setStatusFn("Actualizando OCs del proveedor…");
  state.skipAutoSave = true;
  try {
    const body = { rows: state.rows, comprobante_idx: compIdx, ...apiContextBody(state) };
    const res = await fetch(`/api/proceso/${encodeURIComponent(pn)}/rematch-purchase`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || "No se pudo actualizar OCs");
    applyProcesoPayload(state, refs, data, pn, state.empresa);
    updateSummaryFromState(refs, state);
    if (handlers?.onRerender) handlers.onRerender();
    const pm = data.purchase_matching || {};
    const hasOcs = !!(pm.oc_provider_has_ocs_by_comprobante || {})[compKey];
    const pmPart = purchaseStatusPart(pm);
    if (pm.enabled && hasOcs) {
      setStatusFn(`Proveedor con OCs — usá «Buscar OCs similares».${pmPart}`, "ok");
    } else if (pm.enabled) {
      setStatusFn(`Proveedor sin OCs en Odoo.${pmPart}`, "ok");
    } else {
      setStatusFn(`OCs actualizadas.${pmPart}`, "ok");
    }
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
    handlers?.onRerender?.();
  } finally {
    state.skipAutoSave = false;
  }
}

function setOcSearchButtonLoading(comprobanteIdx, loading) {
  const key = String(comprobanteIdx);
  const root = document;
  for (const btn of root.querySelectorAll(`[data-search-oc="${key}"], [data-open-oc="${key}"]`)) {
    btn.disabled = !!loading;
    if (btn.classList.contains("ocResearchBtn")) {
      btn.title = loading ? "Buscando…" : "Buscar de nuevo";
      continue;
    }
    if (loading) {
      if (!btn.dataset.labelBefore) btn.dataset.labelBefore = (btn.textContent || "").trim();
      btn.textContent = "Buscando…";
    } else if (btn.dataset.labelBefore) {
      btn.textContent = btn.dataset.labelBefore;
      delete btn.dataset.labelBefore;
    }
  }
}

export async function searchOc(state, refs, setStatusFn, handlers, comprobanteIdx) {
  const pn = String(state.processNumber || refs.processNumberEl?.value || "").trim();
  if (!pn) return false;

  const compKey = String(comprobanteIdx);
  if (!state._ocSearching) state._ocSearching = {};
  if (state._ocSearching[compKey]) return false;
  state._ocSearching[compKey] = true;

  setOcSearchButtonLoading(comprobanteIdx, true);
  setStatusFn("Buscando OCs similares…");
  state.skipAutoSave = true;
  try {
    const body = { rows: state.rows, comprobante_idx: comprobanteIdx, ...apiContextBody(state) };
    const res = await fetch(`/api/proceso/${encodeURIComponent(pn)}/search-oc`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || "No se pudo buscar OCs");
    applyProcesoPayload(state, refs, data, pn, state.empresa);
    updateSummaryFromState(refs, state);
    if (handlers?.onRerender) handlers.onRerender();
    const pmPart = purchaseStatusPart(data.purchase_matching || {});
    setStatusFn(`OCs encontradas.${pmPart}`, "ok");
    return true;
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
    handlers?.onRerender?.();
    return false;
  } finally {
    delete state._ocSearching[compKey];
    state.skipAutoSave = false;
    setOcSearchButtonLoading(comprobanteIdx, false);
  }
}

export async function selectOc(state, refs, setStatusFn, handlers, comprobanteIdx, orderId) {
  const pn = String(state.processNumber || refs.processNumberEl?.value || "").trim();
  if (!pn) return;
  setStatusFn("Aplicando OC seleccionada…");
  state.skipAutoSave = true;
  try {
    const body = { comprobante_idx: comprobanteIdx, order_id: orderId, ...apiContextBody(state) };
    const res = await fetch(`/api/proceso/${encodeURIComponent(pn)}/select-oc`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || "No se pudo aplicar la OC");
    applyProcesoPayload(state, refs, data, pn, state.empresa);
    updateSummaryFromState(refs, state);
    if (handlers?.onRerender) handlers.onRerender();
    else renderComprobantes(state, refs, handlers);
    const pmPart = purchaseStatusPart(data.purchase_matching || {});
    setStatusFn(`OC aplicada.${pmPart}`, "ok");
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
  } finally {
    state.skipAutoSave = false;
  }
}

export async function fetchProductUoms(state, productId) {
  const pn = String(state.processNumber || "").trim();
  const pid = String(productId || "").trim();
  if (!pn || !pid) return [];
  const cached = state.uomOptionsByProductId?.[pid];
  if (Array.isArray(cached) && cached.length) return cached;
  const qs = buildApiQuery({
    product_id: pid,
    ...(state.empresa ? { empresa: state.empresa } : {}),
    ...apiOdooQueryParams(state),
  });
  const res = await fetch(`/api/proceso/${encodeURIComponent(pn)}/product-uoms${qs}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data?.detail || "No se pudieron cargar las UMs");
  cacheProductUoms(state, pid, data.uoms || []);
  return state.uomOptionsByProductId[pid] || [];
}

export async function rematchProductUom(state, refs, setStatusFn, handlers, rowIdx) {
  const pn = String(state.processNumber || refs.processNumberEl?.value || "").trim();
  if (!pn) return;
  const row = state.rows?.[rowIdx];
  if (!row) return;

  const productId = String(row["invoice_line_ids/product_id"] || "").trim();
  // Optimista: limpia sugerencia; si no hay producto, limpia UM localmente.
  row.__product_suggested = "";
  if (!productId) {
    row.__um_empresa = "";
    row.__um_empresa_id = "";
    row.__um_factor = "";
    row.__um_note = "";
    handlers?.onRerender?.();
    return;
  }

  setStatusFn?.("Actualizando UM del producto…");
  try {
    const body = {
      row_index: rowIdx,
      product_id: productId,
      row: { ...row },
      ...apiContextBody(state),
    };
    const res = await fetch(`/api/proceso/${encodeURIComponent(pn)}/rematch-uom`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || "No se pudo actualizar la UM");
    applyUomRowUpdate(row, data.row || {});
    cacheProductUoms(state, productId, data.uoms || []);
    handlers?.onRerender?.();
    const um = row.__um_empresa || "";
    if (um) setStatusFn?.(`UM: ${um}`, "ok");
    else setStatusFn?.("Producto sin UM inferida", "ok");
  } catch (e) {
    setStatusFn?.(e?.message || String(e), "bad");
    handlers?.onRerender?.();
  }
}

export async function selectProductUom(state, refs, setStatusFn, handlers, rowIdx, uomId) {
  const pn = String(state.processNumber || refs.processNumberEl?.value || "").trim();
  if (!pn) return;
  const row = state.rows?.[rowIdx];
  if (!row) return;

  const productId = String(row["invoice_line_ids/product_id"] || "").trim();
  const uid = String(uomId || "").trim();
  if (!productId || !uid) return;

  setStatusFn?.("Actualizando UM…");
  try {
    const body = {
      row_index: rowIdx,
      product_id: productId,
      uom_id: uid,
      row: { ...row },
      ...apiContextBody(state),
    };
    const res = await fetch(`/api/proceso/${encodeURIComponent(pn)}/rematch-uom`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || "No se pudo actualizar la UM");
    applyUomRowUpdate(row, data.row || {});
    cacheProductUoms(state, productId, data.uoms || []);
    handlers?.onRerender?.();
    const um = row.__um_empresa || "";
    if (um) setStatusFn?.(`UM: ${um}`, "ok");
    else setStatusFn?.("UM actualizada", "ok");
  } catch (e) {
    setStatusFn?.(e?.message || String(e), "bad");
    handlers?.onRerender?.();
  }
}

export async function rematchearExcelPadron(state, refs, setStatusFn, handlers) {
  const pn = String(state.processNumber || refs.processNumberEl?.value || "").trim();
  const empresa = String(state.empresa || refs.companyNumberEl?.value || "").trim();
  if (!pn) {
    setStatusFn?.("Indicá un número de proceso.", "bad");
    return;
  }
  const msg =
    "¿Re-matchear contra el padrón Excel actual? Se vuelve a leer el Sheet " +
    "y se recalculan proveedor, productos y conceptos.";
  if (!window.confirm(msg)) return;

  setStatusFn("Re-matcheando con padrón Excel…");
  state.skipAutoSave = true;
  clearAutoSaveTimer(state);
  if (refs.btnRematchExcel) refs.btnRematchExcel.disabled = true;
  if (refs.btnRevertir) refs.btnRevertir.disabled = true;
  try {
    state.excelUser = true;
    const { res, data } = await fetchProcesoPayload(state, pn, empresa, {
      excel_user: "1",
      empresa,
      proceso: pn,
    });
    if (!res.ok) throw new Error(data?.detail || "No se pudo re-matchear");
    applyProcesoPayload(state, refs, data, pn, empresa);
    applyExcelUserChrome(state, refs);
    try {
      state.padronLoading = true;
      state.productosLoading = true;
      if (handlers?.onRerender) handlers.onRerender();
      await loadExcelPadronOptions(state, { force: true });
      applyExcelUserChrome(state, refs);
    } catch (e) {
      state.padronLoading = false;
      state.productosLoading = false;
      setStatusFn(e?.message || String(e), "bad");
    }
    updateSummaryFromState(refs, state);
    if (handlers?.onRerender) handlers.onRerender();
    else renderComprobantes(state, refs, handlers);
    const sheetErr = data.excel_padron?.sheet_error || state.excelPadron?.sheet_error;
    if (sheetErr) {
      setStatusFn(`Padrón Excel: ${sheetErr}`, "bad");
    } else {
      const nProv = state.options?.proveedores?.length || 0;
      setStatusFn(`Re-match listo · ${nProv} proveedores del Sheet.`, "ok");
    }
    if (refs.btnRevertir) refs.btnRevertir.disabled = false;
    if (refs.btnRematchExcel) refs.btnRematchExcel.disabled = false;
    if (refs.btnDescargar && state.rows?.length) refs.btnDescargar.disabled = false;
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
    if (refs.btnRevertir && (state.rows?.length || pn)) refs.btnRevertir.disabled = false;
    if (refs.btnRematchExcel && (state.rows?.length || pn)) refs.btnRematchExcel.disabled = false;
  } finally {
    state.skipAutoSave = false;
  }
}

export async function revertirOriginal(state, refs, setStatusFn, handlers) {
  const pn = String(state.processNumber || refs.processNumberEl?.value || "").trim();
  if (!pn || !(state.rows && state.rows.length)) return;
  const msg = state.excelUser
    ? "¿Restaurar el estado original del proceso? Se descartará la conversión guardada " +
      "y se volverá a generar desde FacturIA (con el padrón Excel)."
    : "¿Restaurar el estado original del proceso? Se descartará la conversión guardada " +
      "y se volverá a generar desde FacturIA.";
  if (!window.confirm(msg)) return;

  setStatusFn("Restaurando estado original…");
  state.skipAutoSave = true;
  clearAutoSaveTimer(state);
  if (refs.btnRevertir) refs.btnRevertir.disabled = true;
  if (refs.btnRematchExcel) refs.btnRematchExcel.disabled = true;
  try {
    const body = apiContextBody(state);
    const res = await fetch(`/api/proceso/${encodeURIComponent(pn)}/revert`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || "No se pudo restaurar");
    applyProcesoPayload(state, refs, data, pn, state.empresa);
    if (state.excelUser) {
      applyExcelUserChrome(state, refs);
      try {
        state.padronLoading = true;
        state.productosLoading = true;
        if (handlers?.onRerender) handlers.onRerender();
        await loadExcelPadronOptions(state, { force: true });
        applyExcelUserChrome(state, refs);
      } catch (e) {
        state.padronLoading = false;
        state.productosLoading = false;
        setStatusFn(e?.message || String(e), "bad");
      }
    }
    updateSummaryFromState(refs, state);
    if (handlers?.onRerender) handlers.onRerender();
    else renderComprobantes(state, refs, handlers);
    const pmPart = state.excelUser ? "" : purchaseStatusPart(data.purchase_matching || {});
    setStatusFn(`Estado original restaurado.${pmPart}`, "ok");
    if (refs.btnRevertir) refs.btnRevertir.disabled = false;
    if (refs.btnRematchExcel && state.excelUser) refs.btnRematchExcel.disabled = false;
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
    if (refs.btnRevertir && state.rows?.length) refs.btnRevertir.disabled = false;
    if (refs.btnRematchExcel && state.excelUser && state.rows?.length) {
      refs.btnRematchExcel.disabled = false;
    }
  } finally {
    state.skipAutoSave = false;
  }
}
