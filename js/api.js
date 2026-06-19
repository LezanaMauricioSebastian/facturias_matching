import { mergeProductOptions, normalizeDateFieldsInRows, normalizeIvaPctValue, normalizeNumericFieldsInRows } from "./utils.js";
import { migrateRowKeys, propagateAccountDown, ensureOtroImpuestoColumns } from "./rows.js";
import { renderTable } from "./table.js";

const SOLO_ENCABEZADO_KEY = "__solo_encabezado";

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

export async function loadMetaAndOptions(state) {
  const boot = await fetch("/api/bootstrap").then((r) => r.json());
  const meta = boot?.metadata || {};
  const options = boot?.options || {};
  state.columns = meta.columns || [];
  state.output_headers = meta.output_headers || [];
  state.columns = [...state.columns, { key: "__total_linea", label: "Total", type: "computed" }];
  ensureOtroImpuestoColumns(state, 1);
  ensureSoloEncabezadoColumn(state);
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
  state.padronLoading = false;
  state.productosLoading = false;
  try {
    const qs = empresa ? `?empresa=${encodeURIComponent(empresa)}` : "";
    const apiUrl = `/api/proceso/${encodeURIComponent(pn)}${qs}`;
    const res = await fetch(apiUrl);
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || "Error desconocido");
    state.rows = data.rows || [];
    for (const r of state.rows) migrateRowKeys(r);
    normalizeDateFieldsInRows(state);
    normalizeNumericFieldsInRows(state);
    propagateAccountDown(state.rows);

    refs.btnAddOtroImpuesto.disabled = !(state.rows && state.rows.length);

    if (Array.isArray(data.product_options) && data.product_options.length) {
      state.options.productos = data.product_options;
      state.productosLoading = false;
    } else if (state.rows.length > 0) {
      state.productosLoading = true;
    }

    refs.summaryEl.textContent = empresa
      ? `Filas: ${state.rows.length} · Empresa: ${empresa} · Proceso: ${pn}`
      : `Filas: ${state.rows.length} · Proceso: ${pn}`;
    let safeHandlers = handlers;
    if (!safeHandlers) {
      safeHandlers = {
        onRerender: () => renderTable(state, refs, safeHandlers),
        onCollapseComprobante: () => {},
        onDeleteRow: () => {},
      };
    }
    renderTable(state, refs, safeHandlers);

    if (state.rows.length > 0) {
      state.padronLoading = true;
      renderTable(state, refs, safeHandlers);
      fetch("/api/options?padron=true")
        .then(async (r) => {
          if (!r.ok) throw new Error("No se pudo cargar el padrón");
          return await r.json();
        })
        .then((more) => {
          const prevProd = state.options?.productos;
          state.options = { ...state.options, ...(more || {}) };
          state.options.productos = mergeProductOptions(prevProd, state.options?.productos);
          state.padronLoading = false;
          state.productosLoading = false;
          renderTable(state, refs, safeHandlers);
        })
        .catch(() => {
          state.padronLoading = false;
          state.productosLoading = false;
          renderTable(state, refs, safeHandlers);
        });
    }

    if (state.rows.length === 0) {
      setStatusFn("Sin filas para ese proceso.", "bad");
      refs.btnAddOtroImpuesto.disabled = true;
    } else {
      setStatusFn("Listo para editar y confirmar.", "ok");
      refs.btnDescargar.disabled = false;
      if (refs.btnOdooImportTest) refs.btnOdooImportTest.disabled = false;
    }
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
    state.rows = [];
    state.padronLoading = false;
    state.productosLoading = false;
    let safeHandlers = handlers;
    if (!safeHandlers) {
      safeHandlers = {
        onRerender: () => renderTable(state, refs, safeHandlers),
        onCollapseComprobante: () => {},
        onDeleteRow: () => {},
      };
    }
    renderTable(state, refs, safeHandlers);
    refs.btnAddOtroImpuesto.disabled = true;
    if (refs.btnOdooImportTest) refs.btnOdooImportTest.disabled = true;
  } finally {
    refs.btnBuscar.disabled = false;
  }
}

export async function descargarCsv(state, setStatusFn, validateFn) {
  const err = validateFn(state);
  if (err) {
    setStatusFn(err, "bad");
    return;
  }
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
  const msg =
    "¿Importar estos comprobantes a Odoo TEST? " +
    "Se crearán facturas en borrador y se sincronizarán los impuestos " +
    "(líneas tax de Odoo con montos de FacturIA). " +
    "Si ya existen, se actualizan en lugar de duplicar.";
  if (!window.confirm(msg)) return;

  setStatusFn("Importando a Odoo TEST…");
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
    if (!res.ok) throw new Error(data?.detail || data?.error || "No se pudo importar a Odoo TEST");

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
          const n = u.lines_updated || 0;
          return `${u.name || u.document_number || `#${u.move_id}`} (${n} línea${n === 1 ? "" : "s"})`;
        })
        .join(", ");
      parts.push(`Impuestos actualizados: ${updatedTaxes.length} (${names})`);
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

