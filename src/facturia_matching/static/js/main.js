import { createState } from "./state.js";
import { getDomRefs, setStatus } from "./dom.js";
import { loadMetaAndOptions, odooImportButtonLabel, buscarProceso, descargarCsv, importarOdooTest, revertirOriginal, scheduleAutoSave, buildSummaryText, rematchPurchase } from "./api.js";
import { addOtroImpuesto, removeOtroImpuesto } from "./rows.js";
import { renderTable } from "./table.js";
import { validateRows } from "./validation.js";
import { collapseGroupAtRow } from "./singleLine.js";
import { getUrlParams, isEmbedMode } from "./utils.js";
import { renderOcPickerAfterTable, wireOcPicker } from "./ocPicker.js";

const state = createState();
const refs = getDomRefs();

function setStatusBound(msg, kind) {
  setStatus(refs.statusEl, msg, kind);
}

function summaryText(refs, state) {
  return buildSummaryText(refs, state);
}

async function init() {
  if (isEmbedMode()) {
    document.body.classList.add("embed-mode");
  }

  setStatusBound("Cargando configuración…");
  refs.btnBuscar.disabled = true;
  refs.btnDescargar.disabled = true;
  try {
    await loadMetaAndOptions(state);
    if (refs.btnOdooImportTest) {
      refs.btnOdooImportTest.textContent = odooImportButtonLabel(state);
    }
    setStatusBound("");
    refs.btnBuscar.disabled = false;
  } catch (e) {
    setStatusBound(e?.message || String(e), "bad");
    refs.btnBuscar.disabled = true;
  }

  const renderNow = () => {
    renderTable(state, refs, handlers);
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
    onAutoSave: () => scheduleAutoSave(state, refs, setStatusBound),
    onDeleteRow: (idx) => {
      state.rows.splice(idx, 1);
      refs.summaryEl.textContent = summaryText(refs, state);
      refs.btnDescargar.disabled = !(state.rows && state.rows.length);
      if (refs.btnOdooImportTest) {
        refs.btnOdooImportTest.disabled = !(state.rows && state.rows.length);
      }
      if (refs.btnRevertir) {
        refs.btnRevertir.disabled = !(state.rows && state.rows.length);
      }
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
      refs.summaryEl.textContent = summaryText(refs, state);
      renderNow();
      scheduleAutoSave(state, refs, setStatusBound);
    },
    onRematchPurchase: (rIdx) => {
      rematchPurchase(state, refs, setStatusBound, handlers, rIdx);
    },
  };

  wireOcPicker(state, refs, handlers, setStatusBound);

  refs.btnBuscar.addEventListener("click", () => buscarProceso(state, refs, setStatusBound, handlers));
  refs.btnDescargar.addEventListener("click", () => descargarCsv(state, setStatusBound, validateRows, refs));
  refs.btnOdooImportTest.addEventListener("click", () =>
    importarOdooTest(state, setStatusBound, validateRows, refs)
  );
  if (refs.btnRevertir) {
    refs.btnRevertir.addEventListener("click", () =>
      revertirOriginal(state, refs, setStatusBound, handlers)
    );
  }
  refs.tableWrap.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-add-otro-impuesto]");
    if (!btn || btn.disabled) return;
    handlers.onAddOtroImpuesto();
  });
  refs.processNumberEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") buscarProceso(state, refs, setStatusBound, handlers);
  });

  const urlParams = getUrlParams();
  if (urlParams.proceso) {
    refs.processNumberEl.value = urlParams.proceso;
    if (refs.btnBuscar && !refs.btnBuscar.disabled) {
      await buscarProceso(state, refs, setStatusBound, handlers, urlParams);
    }
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}

