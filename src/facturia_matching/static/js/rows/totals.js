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
    if (row?.__iva_monto_manual) {
      ivaMonto = toNumberLoose(row?.iva_monto);
    } else {
      ivaMonto = lineIvaSuggested(row);
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
