import { showIvaMontoColumn } from "../comprobanteTax/index.js";
import { otrosImpuestoKey } from "../utils/index.js";

export function otroImpuestoNFromNameKey(key) {
  if (key === "otros_impuestos") return 1;
  const m = /^otros_impuestos_(\d+)$/.exec(key);
  return m ? parseInt(m[1], 10) : 0;
}

export function columnsForTaxMode(columns, taxMode, { soloEncabezado = false } = {}) {
  return columns.filter((c) => {
    if (c.key === "iva_monto") return showIvaMontoColumn(taxMode, soloEncabezado);
    if (c.key === "__subtotal") return soloEncabezado;
    if (c.key === "otros_impuestos_monto") return soloEncabezado;
    if (/^otros_impuestos_\d+_monto$/.test(c.key)) return soloEncabezado;
    return true;
  });
}

export { otrosImpuestoKey };
