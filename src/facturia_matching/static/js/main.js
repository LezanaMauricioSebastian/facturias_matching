import { createState } from "./core/state.js";
import { getDomRefs, setStatus } from "./core/dom.js";
import {
  loadMetaAndOptions,
  odooImportButtonLabel,
  updateOdooTenantBadge,
  buscarProceso,
  descargarCsv,
  importarOdoo,
  revertirOriginal,
} from "./api/index.js";
import { validateRows } from "./validation/index.js";
import { getUrlParams, isEmbedMode } from "./utils/index.js";
import { wireOcPicker } from "./ocPicker/index.js";
import { createHandlers } from "./core/handlers.js";

async function init() {
  const state = createState();
  const refs = getDomRefs();
  const setStatusBound = (msg, kind) => setStatus(refs.statusEl, msg, kind);
  const { handlers } = createHandlers({ state, refs, setStatusBound });

  if (isEmbedMode()) {
    document.body.classList.add("embed-mode");
  }

  const urlParams = getUrlParams();

  setStatusBound("Cargando configuración…");
  refs.btnBuscar.disabled = true;
  refs.btnDescargar.disabled = true;
  try {
    await loadMetaAndOptions(state, urlParams);
    if (refs.btnOdooImport) {
      refs.btnOdooImport.textContent = odooImportButtonLabel(state);
    }
    updateOdooTenantBadge(state, refs);
    setStatusBound("");
    refs.btnBuscar.disabled = false;
  } catch (e) {
    setStatusBound(e?.message || String(e), "bad");
    refs.btnBuscar.disabled = true;
  }

  wireOcPicker(state, refs, handlers, setStatusBound);

  refs.btnBuscar.addEventListener("click", () => buscarProceso(state, refs, setStatusBound, handlers));
  refs.btnDescargar.addEventListener("click", () => descargarCsv(state, setStatusBound, validateRows, refs));
  refs.btnOdooImport.addEventListener("click", () =>
    importarOdoo(state, setStatusBound, validateRows, refs)
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
