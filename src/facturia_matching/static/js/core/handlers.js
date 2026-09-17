import { renderSummary, scheduleAutoSave, rematchPurchase, rematchProductUom, selectProductUom } from "../api/index.js";
import { addOtroImpuesto, removeOtroImpuesto } from "../rows/index.js";
import {
  renderComprobantes,
  updateComprobanteFooters,
  setViewMode,
  setUnifiedOneLine,
  shiftCarousel,
} from "../comprobanteView/index.js";
import {
  collapseGroupAtRow,
  comprobanteHasMultipleLines,
  expandSoloEncabezadoAtRow,
  prepareSoloEncabezadoRow,
} from "../singleLine/index.js";
import { renderOcPickerAfterTable } from "../ocPicker/index.js";

function syncActionButtons(refs, state) {
  const hasRows = !!(state.rows && state.rows.length);
  refs.btnDescargar.disabled = !hasRows;
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
    onToggleSoloEncabezado: (rIdx, checked) => {
      const row = state.rows[rIdx];
      if (!row) return;
      if (checked) {
        if (comprobanteHasMultipleLines(state.rows, rIdx)) {
          const res = collapseGroupAtRow(state.rows, rIdx, state);
          if (!res.changed) {
            prepareSoloEncabezadoRow(row, state);
          }
        } else {
          prepareSoloEncabezadoRow(row, state);
        }
      } else {
        expandSoloEncabezadoAtRow(state.rows, rIdx);
      }
      renderSummary(refs, state);
      renderNow();
      scheduleAutoSave(state, refs, setStatusBound);
    },
    onCollapseComprobante: (rIdx) => {
      handlers.onToggleSoloEncabezado(rIdx, true);
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
    onSetUnifiedOneLine: (on) => setUnifiedOneLine(state, refs, handlers, on),
    onCarouselPrev: () => shiftCarousel(state, refs, handlers, -1),
    onCarouselNext: () => shiftCarousel(state, refs, handlers, 1),
  };

  return { handlers, renderNow };
}
