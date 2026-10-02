import { flushAutoSave } from "./autoSave.js";
import { odooImportTargetName } from "./bootstrap.js";
import { lineBase } from "../comprobanteTax/index.js";
import { computeRowTotal } from "../rows/index.js";
import {
  apiContextBody,
  apiOdooQueryParams,
  buildApiQuery,
  findOptionLabel,
  formatMoney,
  formatNumericForDisplay,
  normalizeIvaPctValue,
} from "../utils/index.js";
import {
  isPepeGastosMode,
  monthNameEsFromDate,
  pepeMontoNumber,
  PEPE_DEFAULT_ESTADO_DEUDA,
} from "../pepe/gastosUi.js";

const EXCEL_CSV_SKIP_KEYS = new Set(["__add_otro_impuesto", "__solo_encabezado"]);

/** Layout hoja Gastos Pepe (hardcode; ver `padron/pepe_schema.py`). */
export const PEPE_GASTOS_COLUMNS = [
  "Mes",
  "Sucursal",
  "Proveedor",
  "Concepto",
  "Fecha",
  "Monto",
  "Fecha de pago",
  "Mes de pago",
  "Forma de pago",
  "Categoría gasto",
  "Observación",
  "Estado de Deuda",
];

function csvEscapeCell(value) {
  const s = String(value ?? "");
  if (/[",\r\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

/** Columnas de la grilla excel_user (sin acciones UI). */
export function excelPreviewColumns(state) {
  return (state?.columns || []).filter((c) => {
    if (!c?.key) return false;
    if (EXCEL_CSV_SKIP_KEYS.has(c.key)) return false;
    if (c.type === "header_action" || c.type === "checkbox") return false;
    return true;
  });
}

function taxModeForRow(state, row, rIdx) {
  const idx = row?.__comprobante_idx ?? rIdx;
  return state?.comprobanteTaxModes?.[String(idx)] || "header";
}

/** Valor de celda como se ve en la preview excel_user. */
export function excelPreviewCellValue(state, col, row, rIdx = 0) {
  const key = col.key;
  const raw = row?.[key];

  if (col.type === "computed") {
    const n = key === "__subtotal" ? lineBase(row) : computeRowTotal(row, taxModeForRow(state, row, rIdx));
    return formatMoney(n);
  }

  if (key === "partner_id") {
    const excelName = String(row?.["Nombre de Proveedor"] || row?.__excel_proveedor || "").trim();
    if (excelName) return excelName;
  }
  if (key === "invoice_line_ids/product_id") {
    const excelName = String(row?.["Nombre de producto"] || row?.__excel_producto || "").trim();
    if (excelName) return excelName;
  }

  if (col.type === "selection" || col.options_key) {
    const opts = state?.options?.[col.options_key] || [];
    const val = key === "iva_pct" ? normalizeIvaPctValue(raw) : String(raw ?? "").trim();
    if (!val) return "";
    return findOptionLabel(opts, val) || val;
  }

  if (col.type === "numeric") {
    return formatNumericForDisplay(raw, key);
  }

  return String(raw ?? "").trim();
}

function headerRowFor(state, row) {
  const rows = state?.rows || [];
  const idx = row?.__comprobante_idx;
  if (idx == null || idx === "") return row;
  const first = rows.find((r) => r?.__comprobante_idx === idx);
  return first || row;
}

function pepeProveedor(state, row, header) {
  return (
    String(row?.__excel_proveedor || "").trim() ||
    String(header?.__excel_proveedor || "").trim() ||
    String(row?.["Nombre de Proveedor"] || header?.["Nombre de Proveedor"] || "").trim() ||
    excelPreviewCellValue(
      state,
      { key: "partner_id", type: "selection", options_key: "proveedores" },
      header,
      0
    ) ||
    ""
  );
}

function pepeConcepto(row) {
  return (
    String(row?.__excel_concepto || "").trim() ||
    String(row?.["invoice_line_ids/name"] || "").trim() ||
    ""
  );
}

/** true si el export debe usar layout Gastos Pepe. */
export function usesPepeGastosExport(state) {
  return isPepeGastosMode(state);
}

/**
 * Una fila de la grilla → valores Pepe Gastos (12 cols).
 * Cabecera (fecha, proveedor, forma pago) se toma de la 1ª línea del comprobante.
 */
export function pepeGastosValuesFromRow(state, row, rIdx = 0) {
  const header = headerRowFor(state, row);
  const fecha = String(row?.invoice_date || header?.invoice_date || "").trim();
  const fechaPago = String(row?.invoice_date_due || header?.invoice_date_due || "").trim();
  const monto = formatMoney(pepeMontoNumber(row));
  const forma = String(row?.__excel_forma_pago || header?.__excel_forma_pago || "").trim();
  const categoria = String(row?.__excel_categoria || header?.__excel_categoria || "").trim();
  const mes =
    String(row?.__pepe_mes || "").trim() || monthNameEsFromDate(fecha);
  const mesPago =
    String(row?.__pepe_mes_pago || "").trim() || monthNameEsFromDate(fechaPago);
  const estado =
    String(row?.__pepe_estado_deuda || "").trim() || PEPE_DEFAULT_ESTADO_DEUDA;

  return [
    mes,
    String(row?.__pepe_sucursal || "").trim(),
    pepeProveedor(state, row, header),
    pepeConcepto(row),
    fecha,
    monto,
    fechaPago,
    mesPago,
    forma,
    categoria,
    String(row?.__pepe_observacion || "").trim(),
    estado,
  ];
}

export function buildPepeGastosCsv(state, { includeHeader = true } = {}) {
  const rows = state?.rows || [];
  const lines = [];
  if (includeHeader) {
    lines.push(PEPE_GASTOS_COLUMNS.map(csvEscapeCell).join(","));
  }
  for (let i = 0; i < rows.length; i++) {
    lines.push(pepeGastosValuesFromRow(state, rows[i], i).map(csvEscapeCell).join(","));
  }
  const body = lines.join("\r\n");
  if (!body) return includeHeader ? "\ufeff" : "";
  return (includeHeader ? "\ufeff" : "") + body + "\r\n";
}

/**
 * CSV de la grilla visible en excel_user (labels + valores de preview).
 * Con ?pepe=1: layout Gastos hardcodeado.
 * No usa el formato import Odoo de `/api/csv`.
 */
export function buildExcelPreviewCsv(state, { includeHeader = true } = {}) {
  if (usesPepeGastosExport(state)) {
    return buildPepeGastosCsv(state, { includeHeader });
  }
  const cols = excelPreviewColumns(state);
  const rows = state?.rows || [];
  const lines = [];
  if (includeHeader) {
    lines.push(cols.map((c) => csvEscapeCell(c.label || c.key)).join(","));
  }
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    lines.push(cols.map((c) => csvEscapeCell(excelPreviewCellValue(state, c, row, i))).join(","));
  }
  const body = lines.join("\r\n");
  if (!body) return includeHeader ? "\ufeff" : "";
  return (includeHeader ? "\ufeff" : "") + body + "\r\n";
}

async function fetchOdooCsvText(state) {
  const res = await fetch("/api/csv", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rows: state.rows }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data?.detail || "No se pudo generar CSV");
  }
  return await res.text();
}

/** Odoo → `/api/csv`; excel_user → columnas/valores de la preview. */
async function resolveCsvText(state) {
  if (state?.excelUser) return buildExcelPreviewCsv(state, { includeHeader: true });
  return fetchOdooCsvText(state);
}

/** Quita BOM y la primera línea (headers) para pegar solo el body. */
export function csvBodyOnly(text) {
  let raw = String(text ?? "");
  if (raw.charCodeAt(0) === 0xfeff) raw = raw.slice(1);
  const nl = raw.indexOf("\n");
  if (nl < 0) return "";
  return raw.slice(nl + 1);
}

async function writeClipboardText(text) {
  // Tras await (autosave/fetch) Chrome suele perder el user-gesture / foco y
  // writeText falla con "Document is not focused". Si falla, usamos execCommand.
  if (navigator.clipboard?.writeText && document.hasFocus()) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      /* fall through */
    }
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.left = "-9999px";
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  const ok = document.execCommand("copy");
  ta.remove();
  if (!ok) throw new Error("No se pudo copiar al portapapeles");
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
    const text = await resolveCsvText(state);
    const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = usesPepeGastosExport(state)
      ? "gastos_pepe.csv"
      : state?.excelUser
        ? "preview.csv"
        : "resultado.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setStatusFn(
      usesPepeGastosExport(state)
        ? "CSV Gastos Pepe descargado."
        : state?.excelUser
          ? "CSV de la preview descargado."
          : "CSV descargado.",
      "ok"
    );
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
  }
}

/**
 * Genera el mismo CSV que Descargar y lo deja en el portapapeles.
 * Con excel_user: columnas/valores de la grilla (no formato Odoo).
 * Con ?pepe=1: layout Gastos hardcodeado.
 * @param {{ includeHeader?: boolean }} [opts] — `false` = solo body (sin fila de encabezados).
 */
export async function copiarCsv(state, setStatusFn, validateFn, refs, opts = {}) {
  const includeHeader = opts.includeHeader !== false;
  const err = validateFn(state);
  if (err) {
    setStatusFn(err, "bad");
    return;
  }
  if (!state.rows?.length) {
    setStatusFn("No hay filas para copiar.", "bad");
    return;
  }
  await flushAutoSave(state, refs, setStatusFn);
  setStatusFn("Copiando CSV…");
  if (refs?.btnCopiarCsv) refs.btnCopiarCsv.disabled = true;
  try {
    const full = await resolveCsvText(state);
    const text = includeHeader ? full : csvBodyOnly(full);
    if (!text.trim()) {
      throw new Error("El CSV no tiene filas de datos para copiar.");
    }
    await writeClipboardText(text);
    const pepe = usesPepeGastosExport(state);
    setStatusFn(
      includeHeader
        ? pepe
          ? "CSV Gastos Pepe copiado (con encabezado). Pegalo en la planilla."
          : "CSV copiado (con encabezado). Pegalo en Excel o Google Sheets (Ctrl+V)."
        : pepe
          ? "Filas Gastos Pepe copiadas (sin encabezado). Pegalas en la planilla."
          : "CSV copiado (solo datos). Pegalo en Excel o Google Sheets (Ctrl+V).",
      "ok"
    );
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
  } finally {
    if (refs?.btnCopiarCsv && state.rows?.length) refs.btnCopiarCsv.disabled = false;
  }
}

export async function importarOdoo(state, setStatusFn, validateFn, refs) {
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
  if (refs?.btnOdooImport) refs.btnOdooImport.disabled = true;
  try {
    const res = await fetch(
      `/api/odoo/import${buildApiQuery(apiOdooQueryParams(state))}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rows: state.rows,
          skip_duplicates: true,
          update_taxes_if_exists: true,
          ...apiContextBody(state),
        }),
      }
    );
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
      parts.push(`Creadas: ${created.length}`);
    }
    if (updatedTaxes.length) {
      const labels = updatedTaxes
        .map((u) => u.name || u.document_number)
        .filter(Boolean);
      if (labels.length) {
        parts.push(`Actualizadas en Odoo: ${updatedTaxes.length} (${labels.join(", ")})`);
      } else {
        parts.push(`Actualizadas en Odoo: ${updatedTaxes.length}`);
      }
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
    if (refs?.btnOdooImport && state.rows?.length) refs.btnOdooImport.disabled = false;
  }
}
