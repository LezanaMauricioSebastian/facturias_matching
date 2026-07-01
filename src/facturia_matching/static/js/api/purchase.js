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
  if (!pn || !state.purchaseMatching?.enabled) return;

  const [s] = groupBounds(state.rows, rowIdx);
  const rawIdx = state.rows[s]?.__comprobante_idx;
  const compIdx = rawIdx !== undefined && rawIdx !== null ? Number(rawIdx) : 0;

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
    const pmPart = purchaseStatusPart(data.purchase_matching || {});
    setStatusFn(`OCs actualizadas.${pmPart}`, "ok");
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
