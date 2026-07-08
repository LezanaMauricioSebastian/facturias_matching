import {
  formatNumberEsAR,
  otrosImpuestoMontoKey,
  toNumberLoose,
} from "../utils/index.js";
import { lineBase, lineIvaSuggested } from "../comprobanteTax/index.js";

export function computeRowTotal(row, taxMode = "header") {
  const base = lineBase(row);
  let ivaMonto = 0;
  if (taxMode === "line") {
    const explicit = toNumberLoose(row?.iva_monto);
    const suggested = lineIvaSuggested(row);
    if (row?.__iva_monto_manual) {
      ivaMonto = explicit;
    } else if (
      explicit > 0 &&
      suggested > 0 &&
      Math.abs(explicit - suggested) > Math.max(0.02, suggested * 0.001)
    ) {
      ivaMonto = explicit;
    } else {
      ivaMonto = suggested;
      row.iva_monto = formatNumberEsAR(Math.round(ivaMonto * 100) / 100, 2, 2);
    }
  }

  let otrosMonto = toNumberLoose(row?.["otros_impuestos_monto"]);
  for (let n = 2; n <= 20; n++) {
    const mk = otrosImpuestoMontoKey(n);
    otrosMonto += toNumberLoose(row?.[mk]);
  }

  return base + ivaMonto + otrosMonto;
}
