import { createState } from "./core/state.js";
import { getDomRefs, setStatus } from "./core/dom.js";
import {
  loadMetaAndOptions,
  odooImportButtonLabel,
  updateOdooTenantBadge,
  fetchProcesoPayload,
  buscarProceso,
  descargarCsv,
  copiarCsv,
  importarOdoo,
  revertirOriginal,
  rematchearExcelPadron,
} from "./api/index.js";
import { validateRows } from "./validation/index.js";
import { getUrlParams, isEmbedMode, isExcelUserMode, syncErpImportCallbackState } from "./utils/index.js";
import { wireOcPicker } from "./ocPicker/index.js";
import { createHandlers } from "./core/handlers.js";
import { wireFacturiaTab } from "./facturiaRaw/tab.js";
import { applyExcelUserChrome } from "./api/procesoShared.js";

async function init() {
  const state = createState();
  const refs = getDomRefs();
  const setStatusBound = (msg, kind) => setStatus(refs.statusEl, msg, kind);
  const { handlers } = createHandlers({ state, refs, setStatusBound });

  if (isEmbedMode()) {
    document.documentElement.classList.add("embed-mode");
    document.body.classList.add("embed-mode");
  }

  const urlParams = getUrlParams();
  syncErpImportCallbackState(state, urlParams);
  state.excelUser = isExcelUserMode(urlParams);
  if (state.excelUser) applyExcelUserChrome(state, refs);
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
  if (refs.btnCopiarCsv) refs.btnCopiarCsv.disabled = true;
  try {
    await loadMetaAndOptions(state, urlParams);
    if (refs.btnOdooImport) {
      refs.btnOdooImport.textContent = odooImportButtonLabel(state);
    }
    updateOdooTenantBadge(state, refs);
    if (state.excelUser) {
      state._columnsExcelBase = null;
      applyExcelUserChrome(state, refs);
    }
    wireFacturiaTab(state, refs);
    if (!deepLinkProceso) setStatusBound("");
    refs.btnBuscar.disabled = false;
  } catch (e) {
    setStatusBound(e?.message || String(e), "bad");
    refs.btnBuscar.disabled = true;
    // Prefetch en vuelo: no aplicar si bootstrap falló.
    procesoPrefetch = null;
  }

  wireOcPicker(state, refs, handlers, setStatusBound);

  const wireViewMode = () => {
    const onMode = (mode) => handlers.onSetViewMode?.(mode);
    refs.btnViewLista?.addEventListener("click", () => onMode("lista"));
    refs.btnViewCarrusel?.addEventListener("click", () => onMode("carrusel"));
    refs.btnCarouselPrev?.addEventListener("click", () => handlers.onCarouselPrev?.());
    refs.btnCarouselNext?.addEventListener("click", () => handlers.onCarouselNext?.());
    refs.chkSoloEncabezado?.addEventListener("change", (e) => {
      const t = e.target;
      if (!(t instanceof HTMLInputElement)) return;
      handlers.onToggleSoloEncabezadoAll?.(t.checked);
    });
    // Sync initial toggle from persisted state.
    handlers.onSetViewMode?.(state.viewMode);
  };
  wireViewMode();

  const syncExpandButton = (expanded) => {
    const btn = refs.btnExpandView;
    if (!btn) return;
    btn.setAttribute("aria-pressed", expanded ? "true" : "false");
    btn.title = expanded ? "Reducir" : "Ampliar";
    btn.setAttribute("aria-label", expanded ? "Reducir vista" : "Ampliar vista");
    const icon = btn.querySelector(".expandViewIcon");
    if (icon) icon.textContent = expanded ? "▣" : "▢";
  };

  const setExpandedView = (on) => {
    const expanded = !!on;
    document.body.classList.toggle("view-expanded", expanded);
    document.documentElement.classList.toggle("view-expanded", expanded);
    syncExpandButton(expanded);
  };

  refs.btnExpandView?.addEventListener("click", () => {
    setExpandedView(!document.body.classList.contains("view-expanded"));
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.body.classList.contains("view-expanded")) {
      const t = e.target;
      if (
        t instanceof HTMLElement &&
        t.closest("input, textarea, select, .combobox, [contenteditable='true']")
      ) {
        return;
      }
      setExpandedView(false);
    }
  });

  document.addEventListener("keydown", (e) => {
    if (state.viewMode !== "carrusel") return;
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const t = e.target;
    if (
      t instanceof HTMLElement &&
      (t.closest("input, textarea, select, .combobox, [contenteditable='true']") ||
        t.isContentEditable)
    ) {
      return;
    }
    if (e.key === "ArrowLeft") handlers.onCarouselPrev?.();
    else handlers.onCarouselNext?.();
  });

  refs.btnBuscar.addEventListener("click", () => buscarProceso(state, refs, setStatusBound, handlers));
  refs.btnDescargar.addEventListener("click", () => descargarCsv(state, setStatusBound, validateRows, refs));
  if (refs.btnCopiarCsv) {
    refs.btnCopiarCsv.addEventListener("click", () =>
      copiarCsv(state, setStatusBound, validateRows, refs)
    );
  }
  refs.btnOdooImport.addEventListener("click", () =>
    importarOdoo(state, setStatusBound, validateRows, refs)
  );
  if (refs.btnRevertir) {
    refs.btnRevertir.addEventListener("click", () =>
      revertirOriginal(state, refs, setStatusBound, handlers)
    );
  }
  if (refs.btnRematchExcel) {
    refs.btnRematchExcel.addEventListener("click", () =>
      rematchearExcelPadron(state, refs, setStatusBound, handlers)
    );
  }
  refs.tableWrap.addEventListener("click", (e) => {
    const addBtn = e.target.closest("[data-add-otro-impuesto]");
    if (addBtn) {
      if (addBtn.disabled) return;
      handlers.onAddOtroImpuesto();
      return;
    }
    const removeBtn = e.target.closest("[data-remove-otro-impuesto]");
    if (removeBtn) {
      if (removeBtn.disabled) return;
      const n = parseInt(removeBtn.getAttribute("data-remove-otro-impuesto"), 10);
      if (!Number.isFinite(n) || n < 2) return;
      handlers.onRemoveOtroImpuesto(n);
    }
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
