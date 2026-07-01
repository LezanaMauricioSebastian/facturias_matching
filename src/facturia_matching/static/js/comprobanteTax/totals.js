import { toNumberLoose } from "../utils/index.js";
import {
  facIvaMonto,
  facSubtotal,
  lineIvaSuggested,
  sumLineBases,
  sumLineIva,
  sumLineIvaMontos,
  sumOtrosImpuestos,
  ivaPctToRate,
} from "./lineCalc.js";
import { computeIvaBreakdown, explicitFacIvaMontos } from "./ivaBreakdown.js";

const TOLERANCE = 0.02;

function lineHasContent(row) {
  return !!(
    String(row?.["invoice_line_ids/name"] ?? "").trim() ||
    toNumberLoose(row?.["invoice_line_ids/price_unit"]) ||
    toNumberLoose(row?.["invoice_line_ids/quantity"])
  );
}

export function classifyComprobanteTaxMode(groupRows) {
  if (!groupRows?.length) return "header";
  const headerIva = facIvaMonto(groupRows) || 0;
  const lineIvaSum = sumLineIvaMontos(groupRows);
  const content = groupRows.filter(lineHasContent);
  const linesWithRate = content.filter((row) => ivaPctToRate(row?.iva_pct) > 0);

  if (headerIva <= 0 && !linesWithRate.length) return "header";

  if (
    linesWithRate.length &&
    linesWithRate.length === content.length &&
    headerIva > 0 &&
    Math.abs(lineIvaSum - headerIva) <= Math.max(TOLERANCE, headerIva * 0.001)
  ) {
    return "line";
  }

  if (headerIva > 0 && !linesWithRate.length) return "header";

    if (headerIva > 0 && linesWithRate.length) {
    if (Math.abs(lineIvaSum - headerIva) <= Math.max(TOLERANCE, headerIva * 0.001)) return "line";
    if (content.length === 1) {
      const row = linesWithRate[0];
      if (row?.__iva_monto_manual) return "line";
      const explicit = toNumberLoose(row?.iva_monto);
      const suggested = lineIvaSuggested(row);
      if (
        explicit > 0 &&
        suggested > 0 &&
        Math.abs(explicit - suggested) > Math.max(TOLERANCE, suggested * 0.001)
      ) {
        return "line";
      }
      return "header";
    }
    return "mixed";
  }

  if (linesWithRate.length && headerIva <= 0) return "line";

  return "header";
}

/** Monto IVA por línea cuando el impuesto se detecta en particular (modo line). */
export function showIvaMontoColumn(mode) {
  return mode === "line";
}

/** IVA general del comprobante: editable solo en el pie (modo encabezado/mixto). */
export function footerIvaEditable(mode) {
  return mode !== "line";
}

export function footerIvaDisplayValue(groupRows, totals) {
  if (totals?.mode === "line") return sumLineIvaMontos(groupRows);
  const breakdown = computeIvaBreakdown(groupRows, totals);
  if (breakdown.length) return breakdown.reduce((acc, row) => acc + (row.amount || 0), 0);
  const stored = facIvaMonto(groupRows);
  if (stored != null && stored > 0) return stored;
  return totals?.ivaOdoo || 0;
}

export function computeComprobanteTotals(groupRows, mode) {
  const taxMode = mode || classifyComprobanteTaxMode(groupRows);
  const baseLines = sumLineBases(groupRows);
  const baseFac = facSubtotal(groupRows);
  const ivaFac = facIvaMonto(groupRows);
  const lineIvaSum = sumLineIva(groupRows);
  const otros = sumOtrosImpuestos(groupRows);
  const breakdown = computeIvaBreakdown(groupRows, { mode: taxMode });

  let ivaOdoo = 0;
  if (taxMode === "line") {
    ivaOdoo = sumLineIvaMontos(groupRows);
  } else {
    const explicitMontos = explicitFacIvaMontos(groupRows);
    if (explicitMontos) {
      ivaOdoo = Object.values(explicitMontos).reduce((acc, v) => acc + v, 0);
    } else if (ivaFac != null && ivaFac > 0) {
      ivaOdoo = ivaFac;
    } else {
      ivaOdoo = ivaFac || 0;
    }
  }

  let baseOdoo;
  if (taxMode === "header" && baseFac != null) {
    baseOdoo = baseFac;
  } else {
    baseOdoo = baseLines;
  }
  const totalFac = (baseFac ?? baseLines) + (ivaFac || 0) + otros;
  const totalOdoo = baseOdoo + ivaOdoo + otros;

  return {
    mode: taxMode,
    baseLines,
    baseFac,
    baseOdoo,
    ivaFac,
    ivaOdoo,
    ivaBreakdown: breakdown,
    lineIvaSum,
    otros,
    totalFac,
    totalOdoo,
  };
}

export { TOLERANCE };
