import { createState } from "./state.js";
import { getDomRefs, setStatus } from "./dom.js";
import { loadMetaAndOptions, buscarProceso, descargarCsv, importarOdooTest } from "./api.js";
import { addOtroImpuesto } from "./rows.js";
import { renderTable } from "./table.js";
import { validateRows } from "./validation.js";
import { collapseGroupAtRow } from "./singleLine.js";
import { getUrlParams, isEmbedMode } from "./utils.js";

const state = createState();
const refs = getDomRefs();

function setStatusBound(msg, kind) {
  setStatus(refs.statusEl, msg, kind);
}

function summaryText(refs, rowCount) {
  const proceso = refs.processNumberEl.value.trim();
  return `Filas: ${rowCount} · Proceso: ${proceso}`;
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
    onAddOtroImpuesto: () => {
      if (!(state.rows && state.rows.length)) return;
      addOtroImpuesto(state);
      renderNow();
    },
    onRerender: () => renderNow(),
    onDeleteRow: (idx) => {
      state.rows.splice(idx, 1);
      refs.summaryEl.textContent = summaryText(refs, state.rows.length);
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
      refs.summaryEl.textContent = summaryText(refs, state.rows.length);
      renderNow();
    },
  };

  refs.btnBuscar.addEventListener("click", () => buscarProceso(state, refs, setStatusBound, handlers));
  refs.btnDescargar.addEventListener("click", () => descargarCsv(state, setStatusBound, validateRows));
  refs.btnOdooImportTest.addEventListener("click", () =>
    importarOdooTest(state, setStatusBound, validateRows, refs)
  );
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

