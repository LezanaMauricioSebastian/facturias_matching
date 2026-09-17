import { showIvaMontoColumn } from "../comprobanteTax/index.js";
import { otrosImpuestoKey } from "../utils/index.js";

/** Encabezado duplicado en el chrome de factura (modo carrusel). */
export const CAROUSEL_CHROME_KEYS = new Set([
  "l10n_latam_document_type_id",
  "l10n_latam_document_number",
  "invoice_date",
  "invoice_date_due",
  "partner_id",
  "CUIT",
  "Nombre de Proveedor",
  "x_studio_category", // Rubros → chrome
  "journal_id", // Diario → chrome
  "invoice_line_ids/account_id", // Cuenta → chrome
]);

/** Columnas que no aportan al look de factura en carrusel. */
export const CAROUSEL_HIDE_KEYS = new Set([
  ...CAROUSEL_CHROME_KEYS,
  "__oc_match_note", // Notas OC/UM
  "__qty_pedido", // Cant. pedida
  "__qty_recibido", // Cant. recibida
]);

export function otroImpuestoNFromNameKey(key) {
  if (key === "otros_impuestos") return 1;
  const m = /^otros_impuestos_(\d+)$/.exec(key);
  return m ? parseInt(m[1], 10) : 0;
}

export function columnsForTaxMode(columns, taxMode, { soloEncabezado = false, oneLine = false, hideChromeKeys = false } = {}) {
  const amountsOnRow = !!(oneLine || soloEncabezado);
  return columns.filter((c) => {
    if (hideChromeKeys && CAROUSEL_HIDE_KEYS.has(c.key)) return false;
    // Con 1 línea (sin pie): montos en la fila. Con varias: montos solo en el pie.
    if (c.key === "iva_monto") return showIvaMontoColumn(taxMode, amountsOnRow);
    if (c.key === "otros_impuestos_monto") return amountsOnRow;
    if (/^otros_impuestos_\d+_monto$/.test(c.key)) return amountsOnRow;
    return true;
  });
}

export { otrosImpuestoKey };
