import { showIvaMontoColumn } from "../comprobanteTax/index.js";
import { otrosImpuestoKey } from "../utils/index.js";

export function otroImpuestoNFromNameKey(key) {
  if (key === "otros_impuestos") return 1;
  const m = /^otros_impuestos_(\d+)$/.exec(key);
  return m ? parseInt(m[1], 10) : 0;
}

export function columnsForTaxMode(columns, taxMode, { soloEncabezado = false, oneLine = false } = {}) {
  const amountsOnRow = !!(oneLine || soloEncabezado);
  return columns.filter((c) => {
    // Con 1 línea (sin pie): montos en la fila. Con varias: montos solo en el pie.
    if (c.key === "iva_monto") return showIvaMontoColumn(taxMode, amountsOnRow);
    if (c.key === "otros_impuestos_monto") return amountsOnRow;
    if (/^otros_impuestos_\d+_monto$/.test(c.key)) return amountsOnRow;
    return true;
  });
}

export { otrosImpuestoKey };
