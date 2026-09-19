import { renderSummary, scheduleAutoSave, rematchPurchase, rematchProductUom, selectProductUom } from "../api/index.js";
import { addOtroImpuesto, removeOtroImpuesto } from "../rows/index.js";
import {
  renderComprobantes,
  updateComprobanteFooters,
  setViewMode,
  shiftCarousel,
} from "../comprobanteView/index.js";
import { applySoloEncabezadoToAll } from "../singleLine/index.js";
import { renderOcPickerAfterTable } from "../ocPicker/index.js";

function syncActionButtons(refs, state) {
  const hasRows = !!(state.rows && state.rows.length);
  refs.btnDescargar.disabled = !hasRows;
  if (refs.btnCopiarCsv) refs.btnCopiarCsv.disabled = !hasRows;
  if (refs.btnOdooImport) {
    refs.btnOdooImport.disabled = !hasRows || !!state.excelUser;
    if (state.excelUser) refs.btnOdooImport.hidden = true;
  }
  if (refs.btnRevertir) refs.btnRevertir.disabled = !hasRows;
  if (refs.btnRematchExcel && state.excelUser) {
    refs.btnRematchExcel.disabled = !hasRows && !String(state.processNumber || "").trim();
  }
}

/**
 * Callbacks de la UI (tabla, OC picker, impuestos).
 * El objeto se referencia a sí mismo en onRematchPurchase.
 */
export function createHandlers({ state, refs, setStatusBound }) {
  const renderNow = () => {
    renderComprobantes(state, refs, handlers);
    renderOcPickerAfterTable(state, refs, handlers, setStatusBound);
  };

  const handlers = {
    onAddOtroImpuesto: () => {
      if (!(state.rows && state.rows.length)) return;
      addOtroImpuesto(state);
      renderNow();
      scheduleAutoSave(state, refs, setStatusBound);
    },
    onRemoveOtroImpuesto: (n) => {
      if (!(state.rows && state.rows.length)) return;
      // Sin confirm: en iframe FacturIA (sin allow-modals) confirm() falla en silencio
      // y la × “no hace nada”; el + sí anda porque no pide confirmación.
      if (!removeOtroImpuesto(state, n)) return;
      renderNow();
      scheduleAutoSave(state, refs, setStatusBound);
    },
    onRerender: () => renderNow(),
    onUpdateComprobanteFooters: () => updateComprobanteFooters(state, refs),
    onAutoSave: () => scheduleAutoSave(state, refs, setStatusBound),
    onDeleteRow: (idx) => {
      state.rows.splice(idx, 1);
      renderSummary(refs, state);
      syncActionButtons(refs, state);
      renderNow();
      scheduleAutoSave(state, refs, setStatusBound);
    },
    onToggleSoloEncabezadoAll: (checked) => {
      if (!(state.rows && state.rows.length)) return;
      applySoloEncabezadoToAll(state.rows, checked, state);
      renderSummary(refs, state);
      renderNow();
      scheduleAutoSave(state, refs, setStatusBound);
    },
    onRematchPurchase: (rIdx) => {
      rematchPurchase(state, refs, setStatusBound, handlers, rIdx);
    },
    onRematchProductUom: (rIdx) => {
      rematchProductUom(state, refs, setStatusBound, handlers, rIdx).then(() => {
        scheduleAutoSave(state, refs, setStatusBound);
      });
    },
    onSelectProductUom: (rIdx, uomId) => {
      selectProductUom(state, refs, setStatusBound, handlers, rIdx, uomId).then(() => {
        scheduleAutoSave(state, refs, setStatusBound);
      });
    },
    onSetViewMode: (mode) => setViewMode(state, refs, handlers, mode),
    onCarouselPrev: () => shiftCarousel(state, refs, handlers, -1),
    onCarouselNext: () => shiftCarousel(state, refs, handlers, 1),
  };

  return { handlers, renderNow };
}
