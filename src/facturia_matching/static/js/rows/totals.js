import {
  formatNumberEsAR,
  otrosImpuestoKey,
  otrosImpuestoMontoKey,
  toNumberLoose,
} from "../utils/index.js";
import { lineBase, lineIvaSuggested } from "../comprobanteTax/index.js";
import { isEncabezadoOneLineUi } from "../singleLine/index.js";

/**
 * Solo montos de slots con impuesto asignado en la línea.
 * Los montos FacturIA hidratados en la 1ª fila (sin label) alimentan el pie,
 * no deben inflar la columna Total de esa fila.
 */
function sumAssignedOtrosMontos(row) {
  let otrosMonto = 0;
  for (let n = 1; n <= 20; n++) {
    if (row?.[`__otros_pie_mirror_${n}`]) continue;
    const lab = String(row?.[otrosImpuestoKey(n)] ?? "").trim();
    if (!lab) continue;
    otrosMonto += toNumberLoose(row?.[otrosImpuestoMontoKey(n)]);
  }
  return otrosMonto;
}

export function computeRowTotal(row, taxMode = "header") {
  const base = lineBase(row);
  let ivaMonto = 0;
  const encabezadoUi = isEncabezadoOneLineUi(row);
  if (encabezadoUi) {
    const explicit = toNumberLoose(row?.iva_monto);
    const fromFac = toNumberLoose(row?.__fac_iva_monto);
    ivaMonto = explicit > 0 ? explicit : fromFac;
  } else if (taxMode === "line" || taxMode === "mixed") {
    const explicit = toNumberLoose(row?.iva_monto);
    const suggested = lineIvaSuggested(row);
    if (row?.__iva_monto_manual) {
      ivaMonto = explicit;
    } else if (
      explicit > 0 &&
      suggested > 0 &&
      Math.abs(explicit - suggested) > Math.max(0.02, suggested * 0.001)
    ) {
      // Monto fijo (FacturIA ≠ sugerido). Tras editar precio/qty la UI limpia
      // iva_monto si no hay __iva_monto_manual para que siga al %.
      ivaMonto = explicit;
    } else {
      ivaMonto = suggested;
      row.iva_monto = formatNumberEsAR(Math.round(ivaMonto * 100) / 100, 2, 2);
    }
  }

  // Encabezado 1 línea (sin pie): una fila = todo el comprobante → sumar todos los montos.
  // Multi-línea: solo slots con impuesto asignado (no storage FacturIA del pie).
  const otrosMonto = encabezadoUi
    ? (() => {
        let s = toNumberLoose(row?.["otros_impuestos_monto"]);
        for (let n = 2; n <= 20; n++) s += toNumberLoose(row?.[otrosImpuestoMontoKey(n)]);
        return s;
      })()
    : sumAssignedOtrosMontos(row);

  return base + ivaMonto + otrosMonto;
}

/**
 * Tras editar precio/cantidad: si el IVA de línea no es manual, limpia el monto
 * sticky para que computeRowTotal use el sugerido (qty × precio × %).
 */
export function clearStickyLineIvaOnPriceQtyEdit(row) {
  if (!row || row.__iva_monto_manual) return;
  row.iva_monto = "";
}
