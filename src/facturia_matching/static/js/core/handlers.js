import { renderSummary, scheduleAutoSave, rematchPurchase } from "../api/index.js";
import { addOtroImpuesto, removeOtroImpuesto } from "../rows/index.js";
import { renderComprobantes, updateComprobanteFooters } from "../comprobanteView/index.js";
import { collapseGroupAtRow } from "../singleLine/index.js";
import { renderOcPickerAfterTable } from "../ocPicker/index.js";

function syncActionButtons(refs, state) {
  const hasRows = !!(state.rows && state.rows.length);
  refs.btnDescargar.disabled = !hasRows;
  if (refs.btnOdooImport) refs.btnOdooImport.disabled = !hasRows;
  if (refs.btnRevertir) refs.btnRevertir.disabled = !hasRows;
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
      if (!window.confirm(`¿Quitar el impuesto ${n}?`)) return;
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
    onCollapseComprobante: (rIdx) => {
      const msg =
        "¿Colapsar este comprobante a una sola línea? Se eliminan las líneas adicionales. " +
        "Para deshacer, usá Restaurar original.";
      if (!window.confirm(msg)) return;
      const res = collapseGroupAtRow(state.rows, rIdx, state);
      if (!res.changed) return;
      renderSummary(refs, state);
      renderNow();
      scheduleAutoSave(state, refs, setStatusBound);
    },
    onRematchPurchase: (rIdx) => {
      rematchPurchase(state, refs, setStatusBound, handlers, rIdx);
    },
  };

  return { handlers, renderNow };
}
