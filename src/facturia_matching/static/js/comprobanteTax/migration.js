import { groupBounds } from "../singleLine/index.js";
import { normalizeIvaPctValue, toNumberLoose } from "../utils/index.js";
import { listComprobanteGroups } from "./groups.js";
import { classifyComprobanteTaxMode, TOLERANCE } from "./totals.js";
import { facSubtotal, isExplicitZeroIvaPct, lineHasContent } from "./lineCalc.js";
import {
  computeIvaBreakdown,
  explicitFacIvaMontos,
  serializeFacIvaMontos,
} from "./ivaBreakdown.js";

export function resolveTaxModeForRow(state, rowIdx) {
  const [s, e] = groupBounds(state.rows, rowIdx);
  const groupRows = state.rows.slice(s, e);
  return classifyComprobanteTaxMode(groupRows);
}

/** Corrige qty×precio cuando desborda __fac_subtotal (código mal leído como cantidad). */
export function sanitizeInflatedLineAmounts(rows) {
  if (!Array.isArray(rows)) return 0;
  let fixed = 0;
  for (const group of listComprobanteGroups(rows)) {
    const groupRows = group.rowIndices.map((i) => rows[i]);
    const baseFac = facSubtotal(groupRows);
    if (baseFac == null || baseFac <= 0) continue;
    const cap = baseFac * 1.001 + TOLERANCE;
    for (const row of groupRows) {
      const qty = toNumberLoose(row?.["invoice_line_ids/quantity"]);
      const price = toNumberLoose(row?.["invoice_line_ids/price_unit"]);
      if (qty <= 0 || price <= 0) continue;
      if (qty * price <= cap) continue;
      if (price <= cap) {
        row["invoice_line_ids/quantity"] = "1";
        fixed += 1;
      } else if (qty <= cap) {
        row["invoice_line_ids/price_unit"] = String(Math.round((baseFac / qty) * 100) / 100);
        fixed += 1;
      } else {
        row["invoice_line_ids/quantity"] = "";
        row["invoice_line_ids/price_unit"] = "";
        fixed += 1;
      }
    }
  }
  return fixed;
}

/** Migra iva_monto legacy de fila 0 al metadata __fac_iva_monto. */
export function migrateLegacyComprobanteIva(rows) {
  if (!Array.isArray(rows)) return;
  for (const group of listComprobanteGroups(rows)) {
    const slice = group.rowIndices.map((i) => rows[i]);
    const first = slice[0];
    if (!first) continue;
    if (first.__iva_monto_manual && String(first.iva_monto ?? "").trim()) {
      if (!String(first.__fac_iva_monto ?? "").trim()) {
        first.__fac_iva_monto = first.iva_monto;
      }
      first.iva_monto = "";
      delete first.__iva_monto_manual;
    }
    for (let j = 1; j < slice.length; j++) {
      if (slice[j].iva_monto) slice[j].iva_monto = "";
      delete slice[j].__iva_monto_manual;
    }
  }
}

/** Infiere __fac_iva_montos cuando hay varias alícuotas en líneas pero solo __fac_iva_monto legacy. */
export function migrateFacIvaMontos(rows) {
  if (!Array.isArray(rows)) return;
  for (const group of listComprobanteGroups(rows)) {
    const groupRows = group.rowIndices.map((i) => rows[i]);
    const first = groupRows[0];
    if (!first || String(first.__fac_iva_montos ?? "").trim()) continue;
    const mode = classifyComprobanteTaxMode(groupRows);
    const breakdown = computeIvaBreakdown(groupRows, { mode });
    if (breakdown.length <= 1) continue;
    const montos = {};
    for (const row of breakdown) {
      if (row.rateKey !== "_total" && row.amount > 0) {
        montos[row.rateKey] = String(row.amount);
      }
    }
    if (Object.keys(montos).length) serializeFacIvaMontos(groupRows, montos);
  }
}

/** "21" | "10.5" (clave pie) → valor del selector Impuesto IVA ("21" | "10,5"). */
export function rateKeyToIvaPct(rateKey) {
  const key = String(rateKey ?? "").trim();
  if (!key || key === "_total") return "";
  return normalizeIvaPctValue(key);
}

function lineNeedsFooterIvaFill(row) {
  const cur = String(row?.iva_pct ?? "").trim();
  if (isExplicitZeroIvaPct(cur)) return false;
  return !cur || cur === "0";
}

/**
 * Si el pie tiene una sola alícuota IVA, la copia a Impuesto IVA de todas las líneas
 * del comprobante que aún no tienen tasa (vacío / "0"). No pisa Exento / No Gravado / No Corresponde.
 */
export function propagateSingleFooterIvaToLines(rows) {
  if (!Array.isArray(rows)) return 0;
  let filled = 0;
  for (const group of listComprobanteGroups(rows)) {
    const groupRows = group.rowIndices.map((i) => rows[i]);
    const explicit = explicitFacIvaMontos(groupRows);
    if (!explicit) continue;
    const keys = Object.keys(explicit);
    if (keys.length !== 1) continue;
    const ivaPct = rateKeyToIvaPct(keys[0]);
    if (!ivaPct) continue;
    for (const row of groupRows) {
      if (!lineHasContent(row) || !lineNeedsFooterIvaFill(row)) continue;
      row.iva_pct = ivaPct;
      filled += 1;
    }
  }
  return filled;
}
