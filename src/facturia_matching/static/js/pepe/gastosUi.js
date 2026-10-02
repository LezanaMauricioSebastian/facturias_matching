/** @module pepe/gastosUi — grilla editable layout Gastos (?pepe=1). */

import { lineBase } from "../comprobanteTax/index.js";
import { formatNumericForDisplay, matchedExcelAlias, parseDateLoose, toNumberLoose } from "../utils/index.js";

export const PEPE_DEFAULT_ESTADO_DEUDA = "Pagado";

export const PEPE_ESTADOS_DEUDA_OPTIONS = [
  { id: "Pagado", name: "Pagado" },
  { id: "Debe", name: "Debe" },
];

/** Categoría gasto en planilla Pepe (hoja Gastos). Incluye las del Sheet real. */
export const PEPE_CATEGORIAS_GASTO_OPTIONS = [
  { id: "Gastos Fijos", name: "Gastos Fijos" },
  { id: "Gastos Var", name: "Gastos Var" },
  { id: "CMV", name: "CMV" },
  { id: "Financieros", name: "Financieros" },
  { id: "Impuestos", name: "Impuestos" },
  { id: "Retiro Socios", name: "Retiro Socios" },
];

const MESES_ES = [
  "enero",
  "febrero",
  "marzo",
  "abril",
  "mayo",
  "junio",
  "julio",
  "agosto",
  "septiembre",
  "octubre",
  "noviembre",
  "diciembre",
];

/** Columnas de la hoja Gastos (editables en UI). */
export const PEPE_GASTOS_COL_DEFS = [
  {
    key: "__pepe_mes",
    label: "Mes",
    type: "selection",
    options_key: "meses",
    editable: true,
  },
  {
    key: "__pepe_sucursal",
    label: "Sucursal",
    type: "selection",
    options_key: "sucursales",
    editable: true,
  },
  {
    key: "partner_id",
    label: "Proveedor",
    type: "selection",
    options_key: "proveedores",
    editable: true,
  },
  {
    key: "__excel_concepto",
    label: "Concepto",
    type: "selection",
    options_key: "conceptos",
    editable: true,
  },
  { key: "invoice_date", label: "Fecha", type: "text", editable: true },
  { key: "__pepe_monto", label: "Monto", type: "numeric", editable: true },
  { key: "invoice_date_due", label: "Fecha de pago", type: "text", editable: true },
  {
    key: "__pepe_mes_pago",
    label: "Mes de pago",
    type: "selection",
    options_key: "meses",
    editable: true,
  },
  {
    key: "__excel_forma_pago",
    label: "Forma de pago",
    type: "selection",
    options_key: "formas_pago",
    editable: true,
  },
  {
    key: "__excel_categoria",
    label: "Categoría gasto",
    type: "selection",
    options_key: "categorias_gasto",
    editable: true,
  },
  { key: "__pepe_observacion", label: "Observación", type: "text", editable: true },
  {
    key: "__pepe_estado_deuda",
    label: "Estado de Deuda",
    type: "selection",
    options_key: "estados_deuda",
    editable: true,
  },
];

export function isPepeGastosMode(state) {
  const alias = String(state?.excelAlias || matchedExcelAlias() || "")
    .trim()
    .toLowerCase();
  return alias === "pepe";
}

/** Mes en español; acepta dd/mm/yyyy y dd/mm/yy. */
export function monthNameEsFromDate(raw) {
  const parts = parseDateLoose(raw);
  if (parts && parts.mm >= 1 && parts.mm <= 12) return MESES_ES[parts.mm - 1];
  const s = String(raw ?? "").trim();
  const m = /^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$/.exec(s);
  if (!m) return "";
  const month = parseInt(m[2], 10);
  if (!(month >= 1 && month <= 12)) return "";
  return MESES_ES[month - 1] || "";
}

function headerRowFor(rows, row) {
  const idx = row?.__comprobante_idx;
  if (idx == null || idx === "") return row;
  return rows.find((r) => r?.__comprobante_idx === idx) || row;
}

function ensurePepeOptions(state) {
  state.options = state.options || {};
  state.options.estados_deuda = PEPE_ESTADOS_DEUDA_OPTIONS.map((o) => ({ ...o }));
  const byId = new Map();
  for (const o of PEPE_CATEGORIAS_GASTO_OPTIONS) byId.set(o.id, { ...o });
  for (const o of state.options.categorias_gasto || []) {
    const id = String(o?.id ?? o?.name ?? "").trim();
    if (id) byId.set(id, { id, name: String(o?.name || id) });
  }
  for (const row of state.rows || []) {
    const v = String(row?.__excel_categoria || "").trim();
    if (v && !byId.has(v)) byId.set(v, { id: v, name: v });
  }
  state.options.categorias_gasto = [...byId.values()];
  if (!Array.isArray(state.options.formas_pago)) state.options.formas_pago = [];
  if (!Array.isArray(state.options.meses)) state.options.meses = [];
  if (!Array.isArray(state.options.sucursales)) state.options.sucursales = [];
}

/**
 * Rellena campos Gastos en cada fila (solo si quedan vacíos) y default Estado=Pagado.
 */
export function hydratePepeGastosRows(state) {
  if (!isPepeGastosMode(state)) return;
  ensurePepeOptions(state);
  const rows = state.rows || [];
  for (const row of rows) {
    const header = headerRowFor(rows, row);
    const fecha = String(header?.invoice_date || row?.invoice_date || "").trim();
    const fechaPago = String(header?.invoice_date_due || row?.invoice_date_due || "").trim();

    if (!String(row.__pepe_mes || "").trim()) {
      row.__pepe_mes = monthNameEsFromDate(fecha);
    }
    if (row.__pepe_sucursal == null) row.__pepe_sucursal = "";
    if (!String(row.partner_id || "").trim()) {
      const prov = String(
        row.__excel_proveedor ||
          header.__excel_proveedor ||
          row["Nombre de Proveedor"] ||
          header["Nombre de Proveedor"] ||
          ""
      ).trim();
      if (prov) {
        row.partner_id = prov;
        row["Nombre de Proveedor"] = prov;
        row.__excel_proveedor = prov;
      }
    }
    if (!String(row.__excel_forma_pago || "").trim()) {
      row.__excel_forma_pago = String(header.__excel_forma_pago || "").trim();
    }
    if (!String(row.__excel_categoria || "").trim()) {
      // Copiar del header (p.ej. CMV inferido del historial Gastos).
      row.__excel_categoria = String(header.__excel_categoria || "").trim();
    }
    if (!String(row.__pepe_mes_pago || "").trim()) {
      row.__pepe_mes_pago = monthNameEsFromDate(fechaPago);
    }
    if (row.__pepe_observacion == null) row.__pepe_observacion = "";
    if (!String(row.__pepe_estado_deuda || "").trim()) {
      row.__pepe_estado_deuda = PEPE_DEFAULT_ESTADO_DEUDA;
    }
    if (!String(row.__pepe_monto || "").trim()) {
      const n = lineBase(row);
      row.__pepe_monto = n ? formatNumericForDisplay(n, "__pepe_monto") : "";
    }
  }
  ensurePepeOptions(state);
}

/** Valor exportable de Monto (siempre con $ es-AR vía formatMoney en export). */
export function pepeMontoNumber(row) {
  const raw = String(row?.__pepe_monto ?? "").trim();
  if (raw) return toNumberLoose(raw);
  return lineBase(row);
}
