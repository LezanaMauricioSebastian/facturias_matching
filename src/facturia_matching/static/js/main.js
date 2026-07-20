import { createState } from "./core/state.js";
import { getDomRefs, setStatus } from "./core/dom.js";
import {
  loadMetaAndOptions,
  odooImportButtonLabel,
  updateOdooTenantBadge,
  fetchProcesoPayload,
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
  const deepLinkProceso = Boolean(urlParams.proceso);

  // Deep-link: solapar GET bootstrap ∥ GET proceso (apply sigue en orden).
  let procesoPrefetch = null;
  if (deepLinkProceso) {
    setStatusBound("Cargando configuración y proceso…");
    const empresa = String(urlParams.empresa || "").trim();
    const pn = String(urlParams.proceso || "").trim();
    procesoPrefetch = fetchProcesoPayload(state, pn, empresa, urlParams);
  } else {
    setStatusBound("Cargando configuración…");
  }

  refs.btnBuscar.disabled = true;
  refs.btnDescargar.disabled = true;
  try {
    await loadMetaAndOptions(state, urlParams);
    if (refs.btnOdooImport) {
      refs.btnOdooImport.textContent = odooImportButtonLabel(state);
    }
    updateOdooTenantBadge(state, refs);
    if (!deepLinkProceso) setStatusBound("");
    refs.btnBuscar.disabled = false;
  } catch (e) {
    setStatusBound(e?.message || String(e), "bad");
    refs.btnBuscar.disabled = true;
    // Prefetch en vuelo: no aplicar si bootstrap falló.
    procesoPrefetch = null;
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

  if (deepLinkProceso && refs.btnBuscar && !refs.btnBuscar.disabled) {
    refs.processNumberEl.value = urlParams.proceso;
    let prefetched = null;
    if (procesoPrefetch) {
      try {
        prefetched = await procesoPrefetch;
      } catch (e) {
        // Fall back to a fresh fetch inside buscarProceso.
        prefetched = null;
        setStatusBound(e?.message || String(e), "bad");
      }
    }
    await buscarProceso(state, refs, setStatusBound, handlers, urlParams, {
      prefetched: prefetched || undefined,
    });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
