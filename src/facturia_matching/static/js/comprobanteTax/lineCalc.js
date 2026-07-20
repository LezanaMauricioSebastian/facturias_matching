import { toNumberLoose } from "../utils/index.js";

const IVA_ATTACHABLE_ZERO = new Set(["IVA Exento", "IVA No Gravado"]);
/** Especiales que anulan pie 21 % (no incluir "0": es modo header FacturIA legítimo). */
const EXPLICIT_ZERO_IVA = new Set(["IVA Exento", "IVA No Gravado", "IVA No Corresponde"]);

export function lineHasContent(row) {
  return !!(
    String(row?.["invoice_line_ids/name"] ?? "").trim() ||
    toNumberLoose(row?.["invoice_line_ids/price_unit"]) ||
    toNumberLoose(row?.["invoice_line_ids/quantity"])
  );
}

export function ivaPctToRate(raw) {
  const s = String(raw ?? "")
    .trim()
    .replace(",", ".");
  if (!s || s === "0" || /no corresponde/i.test(s)) return 0;
  const m = /^(\d+(?:\.\d+)?)/.exec(s);
  return m ? parseFloat(m[1]) / 100 : 0;
}

export function isExplicitZeroIvaPct(raw) {
  const label = String(raw ?? "").trim();
  if (!label) return false;
  if (EXPLICIT_ZERO_IVA.has(label)) return true;
  return /no corresponde/i.test(label);
}

export function allContentLinesExplicitZeroIva(groupRows) {
  const content = (groupRows || []).filter(lineHasContent);
  if (!content.length) return false;
  return content.every((row) => isExplicitZeroIvaPct(row?.iva_pct));
}

export function clearFacIvaFooter(groupRows) {
  const first = groupRows?.[0];
  if (first) {
    delete first.__fac_iva_montos;
    first.__fac_iva_monto = "";
    delete first.__fac_iva_monto_manual;
  }
  for (const row of groupRows || []) {
    if (isExplicitZeroIvaPct(row?.iva_pct)) {
      row.iva_monto = "";
      delete row.__iva_monto_manual;
    }
  }
}

export function ivaPctRequiresLineTax(raw) {
  const label = String(raw ?? "").trim();
  if (IVA_ATTACHABLE_ZERO.has(label)) return true;
  return ivaPctToRate(label) > 0;
}

export function hasOtrosImpuestosSelection(groupRows) {
  for (const row of groupRows || []) {
    if (String(row?.otros_impuestos ?? "").trim()) return true;
    for (let n = 2; n <= 20; n++) {
      if (String(row?.[`otros_impuestos_${n}`] ?? "").trim()) return true;
    }
  }
  return false;
}

export function shouldShowOtrosFooter(groupRows, totals) {
  return hasOtrosImpuestosSelection(groupRows) || (totals?.otros || 0) > 0;
}

export function shouldHideIvaFooter(groupRows) {
  const content = (groupRows || []).filter(lineHasContent);
  if (content.length !== 1) return false;
  return isExplicitZeroIvaPct(content[0]?.iva_pct);
}

export function lineBase(row) {
  return (
    toNumberLoose(row?.["invoice_line_ids/quantity"]) * toNumberLoose(row?.["invoice_line_ids/price_unit"])
  );
}

export function lineIvaSuggested(row) {
  return lineBase(row) * ivaPctToRate(row?.iva_pct);
}

export function sumLineBases(groupRows) {
  return groupRows.reduce((acc, row) => acc + lineBase(row), 0);
}

export function sumLineIva(groupRows) {
  return groupRows.reduce((acc, row) => acc + lineIvaSuggested(row), 0);
}

function firstRow(groupRows) {
  return groupRows?.[0] || {};
}

export function facSubtotal(groupRows) {
  const n = toNumberLoose(firstRow(groupRows).__fac_subtotal);
  return n > 0 ? n : null;
}

export function facIvaMonto(groupRows) {
  const fromMeta = toNumberLoose(firstRow(groupRows).__fac_iva_monto);
  if (fromMeta > 0) return fromMeta;
  const first = firstRow(groupRows);
  if (first.__iva_monto_manual) {
    const legacy = toNumberLoose(first.iva_monto);
    if (legacy > 0) return legacy;
  }
  return null;
}

export function facIvaMontoManual(groupRows) {
  return !!firstRow(groupRows).__fac_iva_monto_manual;
}

export function sumOtrosImpuestos(groupRows) {
  let total = 0;
  for (const row of groupRows) {
    total += toNumberLoose(row?.otros_impuestos_monto);
    for (let n = 2; n <= 20; n++) {
      total += toNumberLoose(row?.[`otros_impuestos_${n}_monto`]);
    }
  }
  return total;
}

export function lineIvaMonto(row) {
  const explicit = toNumberLoose(row?.iva_monto);
  if (explicit > 0) return explicit;
  return lineIvaSuggested(row);
}

export function sumLineIvaMontos(groupRows) {
  return groupRows.reduce((acc, row) => acc + lineIvaMonto(row), 0);
}
