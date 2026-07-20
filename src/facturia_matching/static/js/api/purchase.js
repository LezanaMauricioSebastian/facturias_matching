import { apiContextBody } from "../utils/index.js";
import { groupBounds } from "../singleLine/index.js";
import { renderComprobantes } from "../comprobanteView/index.js";
import { clearAutoSaveTimer } from "./autoSave.js";
import {
  applyProcesoPayload,
  purchaseStatusPart,
  updateSummaryFromState,
} from "./procesoShared.js";

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

export async function searchOc(state, refs, setStatusFn, handlers, comprobanteIdx) {
  const pn = String(state.processNumber || refs.processNumberEl?.value || "").trim();
  if (!pn) return;

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
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
    handlers?.onRerender?.();
  } finally {
    state.skipAutoSave = false;
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

export async function revertirOriginal(state, refs, setStatusFn, handlers) {
  const pn = String(state.processNumber || refs.processNumberEl?.value || "").trim();
  if (!pn || !(state.rows && state.rows.length)) return;
  const msg =
    "¿Restaurar el estado original del proceso? Se descartará la conversión guardada " +
    "y se volverá a generar desde FacturIA.";
  if (!window.confirm(msg)) return;

  setStatusFn("Restaurando estado original…");
  state.skipAutoSave = true;
  clearAutoSaveTimer(state);
  if (refs.btnRevertir) refs.btnRevertir.disabled = true;
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
    updateSummaryFromState(refs, state);
    if (handlers?.onRerender) handlers.onRerender();
    else renderComprobantes(state, refs, handlers);
    const pmPart = purchaseStatusPart(data.purchase_matching || {});
    setStatusFn(`Estado original restaurado.${pmPart}`, "ok");
    if (refs.btnRevertir) refs.btnRevertir.disabled = false;
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
    if (refs.btnRevertir && state.rows?.length) refs.btnRevertir.disabled = false;
  } finally {
    state.skipAutoSave = false;
  }
}
