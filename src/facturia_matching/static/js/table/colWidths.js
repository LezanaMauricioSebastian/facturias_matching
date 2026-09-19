import { ADD_OTRO_IMPUESTO_KEY, computeRowTotal } from "../rows/index.js";
import { lineBase } from "../comprobanteTax/index.js";
import { findOptionLabel, formatMoney, formatNumericForDisplay, optionLabel } from "../utils/index.js";

export const DOC_NUM_KEY = "l10n_latam_document_number";

const CELL_PAD_PX = 28;
const CELL_PAD_NUMERIC_PX = 24;
const HEADER_EXTRA_PX = 8;
const SAFETY_PX = 6;

/** Spec por columna: piso/techo + si se “ajusta” al contenido o es flexible. */
const COL_SPEC = {
  l10n_latam_document_number: { min: 100, max: 160, fit: true },
  CUIT: { min: 90, max: 120, fit: true },
  Cuit: { min: 90, max: 120, fit: true },
  l10n_latam_document_type_id: { min: 140, max: 280, flex: true },
  invoice_date: { min: 88, max: 110, fit: true },
  invoice_date_due: { min: 96, max: 120, fit: true },
  x_studio_category: { min: 120, max: 280, flex: true },
  "invoice_line_ids/name": { min: 140, max: 440, flex: true },
  "invoice_line_ids/product_id": { min: 140, max: 360, flex: true },
  journal_id: { min: 120, max: 260, flex: true },
  Proveedor: { min: 120, max: 280, flex: true },
  partner_id: { min: 120, max: 280, flex: true },
  "invoice_line_ids/account_id": { min: 130, max: 280, flex: true },
  "invoice_line_ids/quantity": { min: 44, max: 88, fit: true, ignoreHeader: true },
  "invoice_line_ids/price_unit": { min: 52, max: 150, fit: true, ignoreHeader: true },
  // Select nativo necesita espacio para valor + flecha; min 48 dejaba solo el chevron.
  iva_pct: { min: 88, max: 168, fit: true },
  iva_monto: { min: 88, max: 150, fit: true, ignoreHeader: true, money: true },
  otros_impuestos: { min: 120, max: 240, flex: true },
  otros_impuestos_monto: { min: 88, max: 150, fit: true, ignoreHeader: true, money: true },
  "invoice_line_ids/tax_ids": { min: 120, max: 240, flex: true },
  __subtotal: { min: 100, max: 170, fit: true, ignoreHeader: true, money: true },
  __total_linea: { min: 100, max: 170, fit: true, ignoreHeader: true, money: true },
  __um_empresa: { min: 56, max: 100, fit: true },
  __oc_match_note: { min: 100, max: 260, flex: true },
  [ADD_OTRO_IMPUESTO_KEY]: { min: 36, max: 40, fit: true },
};

const DEFAULT_SPEC = { min: 90, max: 240, flex: true };

let _measureCtx = null;

function measureTextPx(text) {
  const s = String(text ?? "");
  if (!s) return 0;
  if (typeof document === "undefined") {
    return Math.ceil(s.length * 7.2);
  }
  if (!_measureCtx) {
    const canvas = document.createElement("canvas");
    _measureCtx = canvas.getContext("2d");
  }
  if (!_measureCtx) return Math.ceil(s.length * 7.2);
  _measureCtx.font = '11px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
  return Math.ceil(_measureCtx.measureText(s).width);
}

function specFor(key, label) {
  if (COL_SPEC[key]) return COL_SPEC[key];
  if (label && COL_SPEC[label]) return COL_SPEC[label];
  if (key === "otros_impuestos" || /^otros_impuestos_\d+$/.test(key)) {
    return { min: 120, max: 240, flex: true };
  }
  if (key === "otros_impuestos_monto" || /^otros_impuestos_\d+_monto$/.test(key)) {
    return { min: 88, max: 150, fit: true, ignoreHeader: true, money: true };
  }
  return DEFAULT_SPEC;
}

function displayForCell(state, col, row) {
  const key = col.key;
  const raw = row?.[key];
  if (col.type === "checkbox") return col.label || "Solo";
  if (col.type === "header_action") return "+";
  if (col.type === "computed") {
    if (key === "__subtotal") return formatMoney(lineBase(row));
    return formatMoney(computeRowTotal(row, "header"));
  }
  if (key === "__um_empresa") {
    return String(row.__um_empresa || row.__um_empresa_id || "UM").trim();
  }
  if (col.type === "selection" || col.options_key) {
    const optKey = col.options_key;
    const opts = state.options?.[optKey] || [];
    const val = (raw ?? "").toString();
    if (!val) return "Buscar…";
    return findOptionLabel(opts, val) || optionLabel({ value: val, label: val }) || val;
  }
  if (col.type === "numeric") {
    const shown = formatNumericForDisplay(raw, key);
    return shown || "0";
  }
  const text = (raw ?? "").toString().trim();
  return text || (col.type === "text" ? "…" : "");
}

function clampWidth(spec, contentPx) {
  const pad = spec.ignoreHeader ? CELL_PAD_NUMERIC_PX : CELL_PAD_PX;
  return Math.min(spec.max, Math.max(spec.min, contentPx + pad + SAFETY_PX));
}

/**
 * Anchos dinámicos según el contenido visible de las filas (clamp min/max).
 * `fit`: se fija al contenido y no come espacio libre.
 * `flex`: min según contenido; puede crecer (Etiqueta, Producto, etc.).
 */
export function buildColWidths(cols, state, rowIndices) {
  const out = {};
  for (const c of cols) {
    const spec = specFor(c.key, c.label);
    // Cantidad / Precio / montos: el título no manda; manda el valor.
    let contentPx = spec.ignoreHeader ? 0 : measureTextPx(c.label) + HEADER_EXTRA_PX;
    for (const rIdx of rowIndices) {
      const row = state.rows?.[rIdx];
      contentPx = Math.max(contentPx, measureTextPx(displayForCell(state, c, row)));
    }
    out[c.key] = {
      width: clampWidth(spec, contentPx),
      fit: !!spec.fit,
      flex: !!spec.flex,
      ignoreHeader: !!spec.ignoreHeader,
      money: !!spec.money,
    };
  }
  return out;
}

/** @deprecated usar buildColWidths; se mantiene por compat si algo lo importa. */
export function buildColMinWidth(cols) {
  const widths = {};
  for (const c of cols) {
    const spec = specFor(c.key, c.label);
    widths[c.key] = spec.min;
    if (c.label) widths[c.label] = spec.min;
  }
  return widths;
}

function applyColWidthStyles(el, width) {
  if (!el) return;
  el.style.minWidth = `${width}px`;
  el.style.width = `${width}px`;
  el.style.maxWidth = `${width}px`;
}

function cellMeasureText(td) {
  if (!td) return "";
  const input = td.querySelector("input:not([type=checkbox]), select");
  if (input instanceof HTMLInputElement) return input.value || "";
  if (input instanceof HTMLSelectElement) {
    const opt = input.options[input.selectedIndex];
    return (opt?.text || input.value || "").trim();
  }
  return (td.textContent || "").trim();
}

/**
 * Recalcula anchos fit en vivo (al tipear precio/cantidad) para que
 * Precio / Subtotal / Total no queden cortados con ellipsis.
 */
export function refreshFitColWidths(rootEl) {
  if (!rootEl) return;
  rootEl.querySelectorAll("table").forEach((table) => {
    const headers = [...table.querySelectorAll("thead th")];
    headers.forEach((th, colIdx) => {
      if (!th.classList.contains("colFit")) return;
      const sampleTd = table.querySelector(`tbody tr > :nth-child(${colIdx + 1})`);
      let key = null;
      if (th.classList.contains("colQty")) key = "invoice_line_ids/quantity";
      else if (th.classList.contains("colPrice")) key = "invoice_line_ids/price_unit";
      else if (th.classList.contains("colIvaPct")) key = "iva_pct";
      else if (
        sampleTd?.hasAttribute("data-subtotal-r") ||
        sampleTd?.hasAttribute("data-total-r") ||
        th.classList.contains("colMoney")
      ) {
        key = sampleTd?.hasAttribute("data-total-r") ? "__total_linea" : "__subtotal";
      }
      const spec = key ? specFor(key) : { min: 72, max: 160, ignoreHeader: true };
      let contentPx = th.classList.contains("colHeaderClip")
        ? 0
        : measureTextPx(th.textContent) + HEADER_EXTRA_PX;
      table.querySelectorAll("tbody tr").forEach((tr) => {
        const td = tr.children[colIdx];
        contentPx = Math.max(contentPx, measureTextPx(cellMeasureText(td)));
      });
      const width = clampWidth(spec, contentPx);
      applyColWidthStyles(th, width);
      table.querySelectorAll("tbody tr").forEach((tr) => applyColWidthStyles(tr.children[colIdx], width));
    });
  });
}

/** Atributos class+style para th/td según ancho dinámico. */
export function colCellAttrs(colWidths, key, label, extraClass = "") {
  const info = colWidths?.[key] || (label ? colWidths?.[label] : null);
  const classes = [extraClass];
  if (info?.fit) classes.push("colNarrow", "colFit");
  if (info?.flex) classes.push("colFlex");
  if (info?.ignoreHeader) classes.push("colHeaderClip");
  if (info?.money) classes.push("colMoney");
  if (key === "invoice_line_ids/quantity") classes.push("colQty");
  if (key === "invoice_line_ids/price_unit") classes.push("colPrice");
  if (key === "iva_pct") classes.push("colIvaPct");
  if (key === "__um_empresa") classes.push("colUm");
  if (key === ADD_OTRO_IMPUESTO_KEY) classes.push("headerAddTaxCell");

  const cls = classes.filter(Boolean).join(" ").trim();
  const parts = [];
  if (info?.width) {
    if (info.fit) {
      parts.push(`min-width:${info.width}px`, `width:${info.width}px`, `max-width:${info.width}px`);
    } else {
      parts.push(`min-width:${info.width}px`);
    }
  }
  const classAttr = cls ? ` class="${cls}"` : "";
  const titleAttr =
    info?.ignoreHeader && label ? ` title="${String(label).replaceAll('"', "&quot;")}"` : "";
  const style = parts.length ? ` style="${parts.join(";")}"` : "";
  return `${classAttr}${titleAttr}${style}`;
}
