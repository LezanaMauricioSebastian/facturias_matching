import { toNumberLoose } from "../utils/index.js";
import {
  allContentLinesExplicitZeroIva,
  facIvaMonto,
  facIvaMontoManual,
  lineHasContent,
  lineIvaMonto,
  lineIvaSuggested,
  ivaPctToRate,
} from "./lineCalc.js";

function firstRow(groupRows) {
  return groupRows?.[0] || {};
}

/** Pie IVA siempre editable; en modo line el override marca `__fac_iva_monto_manual`. */
function footerIvaEditableForBreakdown(_mode, _groupRows) {
  return true;
}

function sortRateKeys(keys) {
  return [...keys].sort((a, b) => parseFloat(b) - parseFloat(a));
}

/** "21" | "10.5" desde iva_pct o clave almacenada. */
export function normalizeIvaRateKey(ivaPct) {
  const rate = ivaPctToRate(ivaPct) * 100;
  if (rate <= 0) return null;
  return Number.isInteger(rate) ? String(rate) : String(rate);
}

export function parseFacIvaMontos(groupRows) {
  const raw = firstRow(groupRows).__fac_iva_montos;
  if (!raw) return {};
  try {
    const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

/** Montos solo desde JSON almacenado (sin inferencia por línea). */
export function explicitFacIvaMontos(groupRows) {
  const parsed = parseFacIvaMontos(groupRows);
  const out = {};
  for (const [k, v] of Object.entries(parsed)) {
    if (k === "_total") continue;
    const n = toNumberLoose(v);
    if (n > 0) out[k] = n;
  }
  return Object.keys(out).length ? out : null;
}

export function serializeFacIvaMontos(groupRows, montos) {
  const first = firstRow(groupRows);
  if (!first) return;
  const clean = {};
  for (const [k, v] of Object.entries(montos || {})) {
    if (k === "_total") continue;
    const n = toNumberLoose(v);
    if (n > 0) clean[k] = String(v).trim() || String(n);
  }
  if (Object.keys(clean).length) {
    first.__fac_iva_montos = JSON.stringify(clean);
    const total = Object.values(clean).reduce((acc, v) => acc + toNumberLoose(v), 0);
    first.__fac_iva_monto = total > 0 ? String(Math.round(total * 100) / 100) : "";
  } else {
    delete first.__fac_iva_montos;
  }
}

function suggestedByRate(groupRows, mode) {
  const out = new Map();
  for (const row of groupRows.filter(lineHasContent)) {
    const rateKey = normalizeIvaRateKey(row?.iva_pct);
    if (!rateKey) continue;
    const add = mode === "line" ? lineIvaMonto(row) : lineIvaSuggested(row);
    out.set(rateKey, (out.get(rateKey) || 0) + add);
  }
  return out;
}

function ivaRowLabel(rateKey) {
  if (rateKey === "_total") return "IVA";
  return `IVA ${String(rateKey).replace(".", ",")}%`;
}

/**
 * Desglose de IVA por alícuota (como filas separadas en Odoo).
 * `totals.mode` debe venir de classifyComprobanteTaxMode (evita import circular).
 */
export function computeIvaBreakdown(groupRows, totals) {
  const mode = totals?.mode || "header";
  // Exento / No Gravado / No Corresponde: no mostrar 21 % residual del pie FacturIA.
  if (allContentLinesExplicitZeroIva(groupRows)) {
    return [];
  }
  const stored = parseFacIvaMontos(groupRows);
  const suggested = suggestedByRate(groupRows, mode);
  const rateKeys = new Set([...suggested.keys(), ...Object.keys(stored)]);

  if (!rateKeys.size) {
    const headerAmt = facIvaMonto(groupRows);
    if (headerAmt != null && headerAmt > 0) {
      return [
        {
          rateKey: "_total",
          label: "IVA",
          amount: headerAmt,
          suggested: headerAmt,
          editable: footerIvaEditableForBreakdown(mode, groupRows),
        },
      ];
    }
    return [];
  }

  const headerAmt = facIvaMonto(groupRows);
  const singleRate = rateKeys.size === 1;

  return sortRateKeys(rateKeys).map((rateKey) => {
    const sug = suggested.get(rateKey) || 0;
    const storedAmt = toNumberLoose(stored[rateKey]);
    let amount;
    const footerManual = facIvaMontoManual(groupRows);
    if (mode === "line" && !footerManual) {
      amount = sug;
    } else if (storedAmt > 0) {
      amount = storedAmt;
    } else if (headerAmt != null && headerAmt > 0 && singleRate) {
      amount = headerAmt;
    } else {
      amount = sug;
    }
    return {
      rateKey,
      label: ivaRowLabel(rateKey),
      amount,
      suggested: sug,
      editable: footerIvaEditableForBreakdown(mode, groupRows),
    };
  });
}

export function syncFacIvaMontosFromLines(groupRows, mode) {
  if (mode !== "line" || facIvaMontoManual(groupRows)) return;
  const suggested = suggestedByRate(groupRows, mode);
  const montos = {};
  for (const [rateKey, amt] of suggested) {
    if (amt > 0) montos[rateKey] = String(Math.round(amt * 100) / 100);
  }
  if (Object.keys(montos).length) serializeFacIvaMontos(groupRows, montos);
}
