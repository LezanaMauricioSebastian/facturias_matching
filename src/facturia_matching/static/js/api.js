import { mergeEtiquetaOptions, mergeProductOptions, normalizeDateFieldsInRows, normalizeIvaPctValue, normalizeNumericFieldsInRows } from "./utils.js";
import {
  migrateRowKeys,
  propagateAccountDown,
  ensureOtroImpuestoColumns,
  ensureAddOtroImpuestoActionColumn,
  restoreExtraOtroImpuestoColumns,
  resetExtraOtroImpuestoColumns,
} from "./rows.js";
import { groupBounds } from "./singleLine.js";
import { renderTable } from "./table.js";

const SOLO_ENCABEZADO_KEY = "__solo_encabezado";
const PURCHASE_COLUMN_KEYS = [
  "__qty_pedido",
  "__qty_recibido",
  "__um_proveedor",
  "__um_empresa",
  "__oc_match_note",
];
const AUTO_SAVE_DELAY_MS = 1500;

function cachePurchaseColumnDefs(state) {
  if (state.purchaseColumnDefs?.length) return;
  state.purchaseColumnDefs = (state.columns || []).filter((c) =>
    PURCHASE_COLUMN_KEYS.includes(c.key)
  );
}

function syncPurchaseColumns(state, purchaseMatching = {}) {
  cachePurchaseColumnDefs(state);
  const showCols = !!(purchaseMatching.enabled && purchaseMatching.show_purchase_columns);
  const hadPurchase = state.columns.some((c) => PURCHASE_COLUMN_KEYS.includes(c.key));

  if (showCols) {
    const missing = (state.purchaseColumnDefs || []).filter(
      (def) => !state.columns.some((c) => c.key === def.key)
    );
    if (missing.length) {
      const totalIdx = state.columns.findIndex((c) => c.key === "__total_linea");
      const insertAt = totalIdx >= 0 ? totalIdx : state.columns.length;
      state.columns.splice(insertAt, 0, ...missing);
    }
  } else if (hadPurchase) {
    state.columns = state.columns.filter((c) => !PURCHASE_COLUMN_KEYS.includes(c.key));
  }

  ensureAddOtroImpuestoActionColumn(state);
}

function purchaseStatusPart(pm) {
  if (!pm?.enabled || !pm?.show_purchase_columns) return "";
  if (pm.rows_matched || pm.oc_detected) {
    return (
      ` · OC: ${pm.rows_matched || 0}/${pm.rows_total || 0} líneas` +
      (pm.oc_detected ? ` (${pm.oc_detected})` : "")
    );
  }
  return " · OC: sin match";
}

export function buildSummaryText(refs, state) {
  const proceso = String(state.processNumber || refs.processNumberEl?.value || "").trim();
  const parts = [`Filas: ${state.rows?.length || 0}`, `Proceso: ${proceso || "—"}`];
  if (state.source === "saved") parts.push("Guardado");
  else if (state.source === "generated") parts.push("Generado");
  if (state.saveStatus === "saving") parts.push("Guardando…");
  else if (state.saveStatus === "synced") parts.push("Sincronizado");
  return parts.join(" · ");
}

function updateSummary(refs, state) {
  if (refs?.summaryEl) refs.summaryEl.textContent = buildSummaryText(refs, state);
}

function clearAutoSaveTimer(state) {
  if (state.autoSaveTimer) {
    clearTimeout(state.autoSaveTimer);
    state.autoSaveTimer = null;
  }
}

export function scheduleAutoSave(state, refs, setStatusFn) {
  if (state.skipAutoSave || !(state.rows && state.rows.length) || !state.processNumber) return;
  state.dirty = true;
  state.saveStatus = "pending";
  updateSummary(refs, state);
  clearAutoSaveTimer(state);
  state.autoSaveTimer = setTimeout(() => {
    state.autoSaveTimer = null;
    saveConversion(state, refs, setStatusFn);
  }, AUTO_SAVE_DELAY_MS);
}

export function flushAutoSave(state, refs, setStatusFn) {
  if (!state.dirty || state.skipAutoSave) return Promise.resolve();
  clearAutoSaveTimer(state);
  return saveConversion(state, refs, setStatusFn);
}

export async function saveConversion(state, refs, setStatusFn) {
  if (!(state.rows && state.rows.length) || !state.processNumber || state.saveInFlight) return;
  state.saveInFlight = true;
  state.saveStatus = "saving";
  updateSummary(refs, state);
  try {
    const body = { rows: state.rows };
    if (state.empresa) body.empresa = state.empresa;
    const res = await fetch(`/api/proceso/${encodeURIComponent(state.processNumber)}/conversion`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.detail || "No se pudo guardar");
    state.source = "saved";
    state.dirty = false;
    state.saveStatus = "synced";
    updateSummary(refs, state);
  } catch (e) {
    state.saveStatus = "error";
    updateSummary(refs, state);
    setStatusFn?.(e?.message || String(e), "bad");
  } finally {
    state.saveInFlight = false;
  }
}

function applyProcesoPayload(state, refs, data, pn, empresa) {
  state.processNumber = pn;
  state.empresa = empresa || "";
  state.source = data.source || "generated";
  state.saveStatus = state.source === "saved" ? "synced" : "";
  state.dirty = false;
  state.rows = data.rows || [];
  for (const r of state.rows) migrateRowKeys(r);
  normalizeDateFieldsInRows(state);
  normalizeNumericFieldsInRows(state);
  propagateAccountDown(state.rows);
  resetExtraOtroImpuestoColumns(state);
  restoreExtraOtroImpuestoColumns(state, data.extra_tax_indices);
  state.purchaseMatching = data.purchase_matching || {};
  syncPurchaseColumns(state, state.purchaseMatching);
}

function ensureSoloEncabezadoColumn(state) {
  if (state.columns.some((c) => c.key === SOLO_ENCABEZADO_KEY)) return;
  state.columns.unshift({
    key: SOLO_ENCABEZADO_KEY,
    label: "Solo encabezado",
    type: "checkbox",
    readonly: true,
    editable: false,
  });
}

export function odooImportButtonLabel(state) {
  return state.odooProfile === "aliare" ? "Importar a Odoo" : "Importar a Odoo TEST";
}

export function odooImportTargetName(state) {
  return state.odooProfile === "aliare" ? "Odoo" : "Odoo TEST";
}

export async function loadMetaAndOptions(state) {
  const boot = await fetch("/api/bootstrap").then((r) => r.json());
  const meta = boot?.metadata || {};
  const options = boot?.options || {};
  state.odooProfile = boot?.odoo_profile === "aliare" ? "aliare" : "default";
  state.columns = meta.columns || [];
  state.output_headers = meta.output_headers || [];
  state.columns = [...state.columns, { key: "__total_linea", label: "Total", type: "computed" }];
  ensureOtroImpuestoColumns(state, 1);
  ensureAddOtroImpuestoActionColumn(state);
  ensureSoloEncabezadoColumn(state);
  cachePurchaseColumnDefs(state);
  state.options = { ...state.options, ...(options || {}) };
  if (Array.isArray(state.options.iva_options)) {
    state.options.iva_options = state.options.iva_options.map((o) => normalizeIvaPctValue(o));
  }
}

export async function buscarProceso(state, refs, setStatusFn, handlers, urlOverrides = {}) {
  const empresa = String(urlOverrides.empresa ?? refs.companyNumberEl?.value ?? "").trim();
  const pn = String(urlOverrides.proceso ?? refs.processNumberEl?.value ?? "").trim();
  if (!pn) return;
  setStatusFn("Buscando proceso y ejecutando matching…");
  refs.btnBuscar.disabled = true;
  refs.btnDescargar.disabled = true;
  if (refs.btnOdooImportTest) refs.btnOdooImportTest.disabled = true;
  if (refs.btnRevertir) refs.btnRevertir.disabled = true;
  state.padronLoading = false;
  state.productosLoading = false;
  state.skipAutoSave = true;
  clearAutoSaveTimer(state);
  try {
    const qs = empresa ? `?empresa=${encodeURIComponent(empresa)}` : "";
    const apiUrl = `/api/proceso/${encodeURIComponent(pn)}${qs}`;
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

    updateSummary(refs, state);
    let safeHandlers = handlers;
    if (!safeHandlers) {
      safeHandlers = {
        onRerender: () => renderTable(state, refs, safeHandlers),
        onCollapseComprobante: () => {},
        onDeleteRow: () => {},
        onAutoSave: () => scheduleAutoSave(state, refs, setStatusFn),
      };
    }
    const rerender = safeHandlers.onRerender || (() => renderTable(state, refs, safeHandlers));
    rerender();

    if (state.rows.length > 0) {
      state.padronLoading = true;
      rerender();
      fetch("/api/options?padron=true")
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
      if (refs.btnOdooImportTest) refs.btnOdooImportTest.disabled = false;
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
    let safeHandlers = handlers;
    if (!safeHandlers) {
      safeHandlers = {
        onRerender: () => renderTable(state, refs, safeHandlers),
        onCollapseComprobante: () => {},
        onDeleteRow: () => {},
        onAutoSave: () => scheduleAutoSave(state, refs, setStatusFn),
      };
    }
    renderTable(state, refs, safeHandlers);
    if (refs.btnOdooImportTest) refs.btnOdooImportTest.disabled = true;
    if (refs.btnRevertir) refs.btnRevertir.disabled = true;
  } finally {
    refs.btnBuscar.disabled = false;
    state.skipAutoSave = false;
  }
}

export async function rematchPurchase(state, refs, setStatusFn, handlers, rowIdx) {
  const pn = String(state.processNumber || refs.processNumberEl?.value || "").trim();
  if (!pn || !state.purchaseMatching?.enabled) return;

  const [s] = groupBounds(state.rows, rowIdx);
  const rawIdx = state.rows[s]?.__comprobante_idx;
  const compIdx = rawIdx !== undefined && rawIdx !== null ? Number(rawIdx) : 0;

  setStatusFn("Actualizando OCs del proveedor…");
  state.skipAutoSave = true;
  try {
    const body = { rows: state.rows, comprobante_idx: compIdx };
    if (state.empresa) body.empresa = state.empresa;
    const res = await fetch(`/api/proceso/${encodeURIComponent(pn)}/rematch-purchase`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || "No se pudo actualizar OCs");
    applyProcesoPayload(state, refs, data, pn, state.empresa);
    updateSummary(refs, state);
    if (handlers?.onRerender) handlers.onRerender();
    const pmPart = purchaseStatusPart(data.purchase_matching || {});
    setStatusFn(`OCs actualizadas.${pmPart}`, "ok");
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
    handlers?.onRerender?.();
  } finally {
    state.skipAutoSave = false;
  }
}

export async function selectOc(state, refs, setStatusFn, handlers, comprobanteIdx, orderId) {
  const pn = String(state.processNumber || refs.processNumberEl?.value || "").trim();
  if (!pn) return;
  setStatusFn("Aplicando OC seleccionada…");
  state.skipAutoSave = true;
  try {
    const body = { comprobante_idx: comprobanteIdx, order_id: orderId };
    if (state.empresa) body.empresa = state.empresa;
    const res = await fetch(`/api/proceso/${encodeURIComponent(pn)}/select-oc`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || "No se pudo aplicar la OC");
    applyProcesoPayload(state, refs, data, pn, state.empresa);
    updateSummary(refs, state);
    if (handlers?.onRerender) handlers.onRerender();
    else renderTable(state, refs, handlers);
    const pmPart = purchaseStatusPart(data.purchase_matching || {});
    setStatusFn(`OC aplicada.${pmPart}`, "ok");
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
  } finally {
    state.skipAutoSave = false;
  }
}

export async function revertirOriginal(state, refs, setStatusFn, handlers) {
  const pn = String(state.processNumber || refs.processNumberEl?.value || "").trim();
  if (!pn || !(state.rows && state.rows.length)) return;
  const msg =
    "¿Restaurar el estado original del proceso? Se descartará la conversión guardada " +
    "y se volverá a generar desde FacturIA.";
  if (!window.confirm(msg)) return;

  setStatusFn("Restaurando estado original…");
  state.skipAutoSave = true;
  clearAutoSaveTimer(state);
  if (refs.btnRevertir) refs.btnRevertir.disabled = true;
  try {
    const body = state.empresa ? { empresa: state.empresa } : {};
    const res = await fetch(`/api/proceso/${encodeURIComponent(pn)}/revert`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || "No se pudo restaurar");
    applyProcesoPayload(state, refs, data, pn, state.empresa);
    updateSummary(refs, state);
    if (handlers?.onRerender) handlers.onRerender();
    else renderTable(state, refs, handlers);
    const pmPart = purchaseStatusPart(data.purchase_matching || {});
    setStatusFn(`Estado original restaurado.${pmPart}`, "ok");
    if (refs.btnRevertir) refs.btnRevertir.disabled = false;
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
    if (refs.btnRevertir && state.rows?.length) refs.btnRevertir.disabled = false;
  } finally {
    state.skipAutoSave = false;
  }
}

export async function descargarCsv(state, setStatusFn, validateFn, refs) {
  const err = validateFn(state);
  if (err) {
    setStatusFn(err, "bad");
    return;
  }
  await flushAutoSave(state, refs, setStatusFn);
  setStatusFn("Generando CSV…");
  try {
    const res = await fetch("/api/csv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows: state.rows }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data?.detail || "No se pudo generar CSV");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "resultado.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setStatusFn("CSV descargado.", "ok");
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
  }
}

export async function importarOdooTest(state, setStatusFn, validateFn, refs) {
  const err = validateFn(state);
  if (err) {
    setStatusFn(err, "bad");
    return;
  }
  if (!state.rows?.length) {
    setStatusFn("No hay filas para importar.", "bad");
    return;
  }
  const odooTarget = odooImportTargetName(state);
  const msg =
    `¿Importar estos comprobantes a ${odooTarget}? ` +
    "Se crearán facturas en borrador (con OC vinculada si hay match) y se sincronizarán OC e impuestos " +
    "(líneas y origen Odoo con la selección actual de FacturIA). " +
    "Si ya existen, se actualizan en lugar de duplicar.";
  if (!window.confirm(msg)) return;

  await flushAutoSave(state, refs, setStatusFn);
  setStatusFn(`Importando a ${odooTarget}…`);
  if (refs?.btnOdooImportTest) refs.btnOdooImportTest.disabled = true;
  try {
    const res = await fetch("/api/odoo/import/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rows: state.rows,
        skip_duplicates: true,
        update_taxes_if_exists: true,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.detail || data?.error || `No se pudo importar a ${odooTarget}`);

    const created = data.created || [];
    const updatedTaxes = data.updated_taxes || [];
    const skipped = data.skipped || [];
    const errors = data.errors || [];

    if (data.error && !created.length) {
      throw new Error(data.error);
    }

    const parts = [];
    if (created.length) {
      const names = created.map((c) => c.name || `#${c.id}`).join(", ");
      parts.push(`Creadas: ${created.length} (${names})`);
    }
    if (updatedTaxes.length) {
      const names = updatedTaxes
        .map((u) => {
          const bits = [];
          const taxN = u.tax_lines_updated ?? u.lines_updated ?? 0;
          if (taxN) bits.push(`${taxN} impuesto${taxN === 1 ? "" : "s"}`);
          const poN = u.purchase_lines_updated ?? 0;
          if (poN) bits.push(`${poN} OC`);
          if (u.invoice_origin_updated) bits.push("origen OC");
          const detail = bits.length ? bits.join(", ") : "sin cambios";
          return `${u.name || u.document_number || `#${u.move_id}`} (${detail})`;
        })
        .join(", ");
      parts.push(`Actualizadas en Odoo: ${updatedTaxes.length} (${names})`);
    }
    if (skipped.length) {
      parts.push(`Omitidas (ya existían): ${skipped.length}`);
    }
    if (errors.length) {
      const e0 = errors[0];
      parts.push(`Errores: ${errors.length} — ${e0.document_number || ""}: ${e0.error || ""}`);
    }

    const kind = errors.length ? (created.length || updatedTaxes.length ? "ok" : "bad") : "ok";
    setStatusFn(parts.join(" · ") || "Importación finalizada.", kind);
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
  } finally {
    if (refs?.btnOdooImportTest && state.rows?.length) refs.btnOdooImportTest.disabled = false;
  }
}

