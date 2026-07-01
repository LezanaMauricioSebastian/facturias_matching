import { buildApiQuery, mergeEtiquetaOptions, mergeProductOptions, resolveOdooProfileParam, apiOdooQueryParams } from "../utils/index.js";
import { renderComprobantes } from "../comprobanteView/index.js";
import { clearAutoSaveTimer } from "./autoSave.js";
import {
  applyProcesoPayload,
  purchaseStatusPart,
  resolveHandlers,
  syncPurchaseColumns,
  updateSummaryFromState,
} from "./procesoShared.js";

export async function buscarProceso(state, refs, setStatusFn, handlers, urlOverrides = {}) {
  const empresa = String(urlOverrides.empresa ?? refs.companyNumberEl?.value ?? "").trim();
  const pn = String(urlOverrides.proceso ?? refs.processNumberEl?.value ?? "").trim();
  const odooProfile = String(
    urlOverrides.odoo_profile ?? state.odooProfile ?? ""
  ).trim();
  const odooCloud = String(urlOverrides.odoo_cloud ?? "").trim();
  if (odooCloud || odooProfile) {
    state.odooProfile = resolveOdooProfileParam(odooProfile, odooCloud);
  }
  if (!pn) return;

  setStatusFn("Buscando proceso y ejecutando matching…");
  refs.btnBuscar.disabled = true;
  refs.btnDescargar.disabled = true;
  if (refs.btnOdooImport) refs.btnOdooImport.disabled = true;
  if (refs.btnRevertir) refs.btnRevertir.disabled = true;
  state.padronLoading = false;
  state.productosLoading = false;
  state.skipAutoSave = true;
  clearAutoSaveTimer(state);

  try {
    const apiUrl = `/api/proceso/${encodeURIComponent(pn)}${buildApiQuery({
      empresa,
      ...apiOdooQueryParams(state),
    })}`;
    const res = await fetch(apiUrl);
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || "Error desconocido");

    applyProcesoPayload(state, refs, data, pn, empresa);

    const etiquetaOpts = data.etiqueta_options ?? data.product_options;
    if (Array.isArray(etiquetaOpts) && etiquetaOpts.length) {
      state.options.etiquetas = mergeEtiquetaOptions(state.options.etiquetas, etiquetaOpts);
    }

    if (state.rows.length > 0 && !(state.options.productos && state.options.productos.length)) {
      state.productosLoading = true;
    } else {
      state.productosLoading = false;
    }

    updateSummaryFromState(refs, state);
    const safeHandlers = resolveHandlers(handlers, state, refs, setStatusFn);
    const rerender = safeHandlers.onRerender || (() => renderComprobantes(state, refs, safeHandlers));
    rerender();

    if (state.rows.length > 0) {
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
      const pmPart = purchaseStatusPart(pm);
      setStatusFn(`Listo para editar y confirmar.${pmPart}`, "ok");
      refs.btnDescargar.disabled = false;
      if (refs.btnOdooImport) refs.btnOdooImport.disabled = false;
      if (refs.btnRevertir) refs.btnRevertir.disabled = false;
    }
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
    state.rows = [];
    state.source = "";
    state.saveStatus = "";
    syncPurchaseColumns(state, { enabled: false });
    state.padronLoading = false;
    state.productosLoading = false;
    const safeHandlers = resolveHandlers(handlers, state, refs, setStatusFn);
    renderComprobantes(state, refs, safeHandlers);
    if (refs.btnOdooImport) refs.btnOdooImport.disabled = true;
    if (refs.btnRevertir) refs.btnRevertir.disabled = true;
  } finally {
    refs.btnBuscar.disabled = false;
    state.skipAutoSave = false;
  }
}
