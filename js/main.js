import { createState } from "./state.js";
import { getDomRefs, setStatus } from "./dom.js";
import { loadMetaAndOptions, buscarProceso, descargarCsv, importarOdooTest } from "./api.js";
import { ensureOtroImpuestoColumns, currentMaxOtroImpuestoN } from "./rows.js";
import { renderTable } from "./table.js";
import { validateRows } from "./validation.js";
import { collapseGroupAtRow } from "./singleLine.js";

const state = createState();
const refs = getDomRefs();

function setStatusBound(msg, kind) {
  setStatus(refs.statusEl, msg, kind);
}

async function init() {
  setStatusBound("Cargando configuración…");
  refs.btnBuscar.disabled = true;
  refs.btnDescargar.disabled = true;
  try {
    await loadMetaAndOptions(state);
    setStatusBound("");
    refs.btnBuscar.disabled = false;
  } catch (e) {
    setStatusBound(e?.message || String(e), "bad");
    refs.btnBuscar.disabled = true;
  }

  const renderNow = () => {
    renderTable(state, refs, handlers);
  };

  const handlers = {
    onRerender: () => renderNow(),
    onDeleteRow: (idx) => {
      state.rows.splice(idx, 1);
      refs.summaryEl.textContent = `Filas: ${state.rows.length} · Proceso: ${refs.processNumberEl.value.trim()}`;
      refs.btnAddOtroImpuesto.disabled = !(state.rows && state.rows.length);
      refs.btnDescargar.disabled = !(state.rows && state.rows.length);
      if (refs.btnOdooImportTest) {
        refs.btnOdooImportTest.disabled = !(state.rows && state.rows.length);
      }
      renderNow();
    },
    onCollapseComprobante: (rIdx) => {
      const msg =
        "¿Colapsar este comprobante a una sola línea? Se eliminan las líneas adicionales. " +
        "Para deshacer, volvé a buscar el proceso.";
      if (!window.confirm(msg)) return;
      const res = collapseGroupAtRow(state.rows, rIdx, state);
      if (!res.changed) return;
      refs.summaryEl.textContent = `Filas: ${state.rows.length} · Proceso: ${refs.processNumberEl.value.trim()}`;
      renderNow();
    },
  };

  refs.btnBuscar.addEventListener("click", () => buscarProceso(state, refs, setStatusBound, handlers));
  refs.btnDescargar.addEventListener("click", () => descargarCsv(state, setStatusBound, validateRows));
  refs.btnOdooImportTest.addEventListener("click", () =>
    importarOdooTest(state, setStatusBound, validateRows, refs)
  );
  refs.btnAddOtroImpuesto.addEventListener("click", () => {
    const next = currentMaxOtroImpuestoN(state.columns) + 1;
    ensureOtroImpuestoColumns(state, next);
    renderNow();
  });
  refs.processNumberEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") buscarProceso(state, refs, setStatusBound, handlers);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}

