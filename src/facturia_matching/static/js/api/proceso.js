import {
  buildApiQuery,
  mergeEtiquetaOptions,
  mergeProductOptions,
  syncOdooProfileState,
  apiOdooQueryParams,
  apiExcelQueryParams,
  currentEmpresa,
  isDebugMode,
  isExcelUserMode,
} from "../utils/index.js";
import { renderComprobantes } from "../comprobanteView/index.js";
import { clearAutoSaveTimer } from "./autoSave.js";
import {
  applyProcesoPayload,
  applyExcelUserChrome,
  loadExcelPadronOptions,
  purchaseStatusPart,
  resolveHandlers,
  syncPurchaseColumns,
  updateSummaryFromState,
} from "./procesoShared.js";

/**
 * Solo GET /api/proceso — sin tocar DOM.
 * Sirve para solapar con bootstrap en deep-link (?proceso=).
 */
export async function fetchProcesoPayload(state, pn, empresa, urlOverrides = {}) {
  const emp = String(empresa || currentEmpresa(state, urlOverrides) || "").trim();
  if (emp) state.empresa = emp;
  syncOdooProfileState(state, urlOverrides);
  state.excelUser = !!(state.excelUser || isExcelUserMode(urlOverrides));
  const apiUrl = `/api/proceso/${encodeURIComponent(pn)}${buildApiQuery({
    empresa: emp || undefined,
    ...apiOdooQueryParams(state),
    ...apiExcelQueryParams(state, urlOverrides),
  })}`;
  const t0 = performance.now();
  const res = await fetch(apiUrl);
  const data = await res.json();
  if (isDebugMode()) {
    console.log(
      `[timing] GET /api/proceso/${pn} ${(performance.now() - t0).toFixed(0)}ms`,
      {
        empresa: empresa || null,
        ok: res.ok,
        rows: data?.rows?.length ?? null,
        source: data?.source || null,
        excel_user: data?.excel_user || null,
      }
    );
  }
  return { res, data };
}

export async function buscarProceso(state, refs, setStatusFn, handlers, urlOverrides = {}, opts = {}) {
  const empresa = String(
    urlOverrides.empresa ?? refs.companyNumberEl?.value ?? currentEmpresa(state, urlOverrides) ?? ""
  ).trim();
  const pn = String(urlOverrides.proceso ?? refs.processNumberEl?.value ?? "").trim();
  if (empresa) state.empresa = empresa;
  syncOdooProfileState(state, urlOverrides);
  state.excelUser = !!(state.excelUser || isExcelUserMode(urlOverrides));
  if (!pn) return;

  setStatusFn("Buscando proceso y ejecutando matching…");
  refs.btnBuscar.disabled = true;
  refs.btnDescargar.disabled = true;
  if (refs.btnOdooImport) refs.btnOdooImport.disabled = true;
  if (refs.btnRevertir) refs.btnRevertir.disabled = true;
  if (refs.btnRematchExcel) refs.btnRematchExcel.disabled = true;
  state.padronLoading = false;
  state.productosLoading = false;
  state.skipAutoSave = true;
  clearAutoSaveTimer(state);

  try {
    let res;
    let data;
    if (opts.prefetched) {
      ({ res, data } = opts.prefetched);
    } else {
      ({ res, data } = await fetchProcesoPayload(state, pn, empresa, urlOverrides));
    }
    if (!res.ok) throw new Error(data?.detail || "Error desconocido");

    applyProcesoPayload(state, refs, data, pn, empresa);
    applyExcelUserChrome(state, refs);

    const etiquetaOpts = data.etiqueta_options ?? data.product_options;
    if (Array.isArray(etiquetaOpts) && etiquetaOpts.length) {
      state.options.etiquetas = mergeEtiquetaOptions(state.options.etiquetas, etiquetaOpts);
    }

    if (state.excelUser) {
      state.padronLoading = true;
      state.productosLoading = true;
    } else if (
      state.rows.length > 0 &&
      !(state.options.productos && state.options.productos.length)
    ) {
      state.productosLoading = true;
    } else {
      state.productosLoading = false;
    }

    updateSummaryFromState(refs, state);
    const safeHandlers = resolveHandlers(handlers, state, refs, setStatusFn);
    const rerender = safeHandlers.onRerender || (() => renderComprobantes(state, refs, safeHandlers));
    rerender();

    if (state.excelUser) {
      try {
        await loadExcelPadronOptions(state, { force: true });
        applyExcelUserChrome(state, refs);
        rerender();
      } catch (e) {
        state.padronLoading = false;
        state.productosLoading = false;
        setStatusFn(e?.message || String(e), "bad");
        rerender();
      }
    } else if (state.rows.length > 0) {
      state.padronLoading = true;
      rerender();
      const optQs = buildApiQuery({
        padron: "true",
        ...apiOdooQueryParams(state),
      }).replace(/^\?/, "");
      fetch(`/api/options?${optQs}`)
        .then(async (r) => {
          if (!r.ok) throw new Error("No se pudo cargar el padrón");
          return await r.json();
        })
        .then((more) => {
          const prevProd = state.options?.productos;
          const prevEtiquetas = state.options?.etiquetas;
          state.options = { ...state.options, ...(more || {}) };
          state.options.productos = mergeProductOptions(prevProd, state.options?.productos);
          state.options.etiquetas = mergeEtiquetaOptions(prevEtiquetas, state.options?.etiquetas);
          state.padronLoading = false;
          state.productosLoading = false;
          rerender();
        })
        .catch(() => {
          state.padronLoading = false;
          state.productosLoading = false;
          rerender();
        });
    }

    if (state.rows.length === 0) {
      setStatusFn("Sin filas para ese proceso.", "bad");
    } else {
      const pm = data.purchase_matching || {};
      const sheetErr = data.excel_padron?.sheet_error;
      let msg = state.excelUser
        ? "Listo para editar (padrón Excel)."
        : "Listo para editar y confirmar.";
      if (sheetErr) {
        msg = `Padrón Excel: ${sheetErr}`;
        setStatusFn(msg, "bad");
      } else {
        const pmPart = state.excelUser ? "" : purchaseStatusPart(pm);
        setStatusFn(`${msg}${pmPart}`, "ok");
      }
      refs.btnDescargar.disabled = false;
      if (refs.btnOdooImport && !state.excelUser) refs.btnOdooImport.disabled = false;
      if (refs.btnRevertir) refs.btnRevertir.disabled = false;
      if (refs.btnRematchExcel && state.excelUser) refs.btnRematchExcel.disabled = false;
    }
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
    state.rows = [];
    state.carouselIndex = 0;
    state.source = "";
    state.saveStatus = "";
    syncPurchaseColumns(state, { enabled: false });
    state.padronLoading = false;
    state.productosLoading = false;
    const safeHandlers = resolveHandlers(handlers, state, refs, setStatusFn);
    renderComprobantes(state, refs, safeHandlers);
    if (refs.btnOdooImport) refs.btnOdooImport.disabled = true;
    if (refs.btnRevertir) refs.btnRevertir.disabled = true;
    if (refs.btnRematchExcel) refs.btnRematchExcel.disabled = true;
    applyExcelUserChrome(state, refs);
  } finally {
    refs.btnBuscar.disabled = false;
    state.skipAutoSave = false;
  }
}
