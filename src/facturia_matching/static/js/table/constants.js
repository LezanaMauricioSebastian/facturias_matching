import { ADD_OTRO_IMPUESTO_KEY } from "../rows/index.js";

export const DOC_NUM_KEY = "l10n_latam_document_number";

/** Anchos mínimos por columna (key o label legacy). */
export function buildColMinWidth(cols) {
  const colMinWidth = {
    l10n_latam_document_number: 260,
    "Número de Documento": 260,
    CUIT: 220,
    Cuit: 220,
    "Tipo de Documento": 260,
    l10n_latam_document_type_id: 260,
    "Fecha factura": 260,
    "Fecha de vencimiento": 260,
    Rubros: 280,
    x_studio_category: 280,
    invoice_date: 260,
    invoice_date_due: 260,
    "invoice_line_ids/name": 420,
    "invoice_line_ids/product_id": 320,
    journal_id: 220,
    Proveedor: 220,
    "invoice_line_ids/account_id": 260,
    "invoice_line_ids/quantity": 140,
    "invoice_line_ids/price_unit": 200,
    iva_pct: 140,
    iva_monto: 160,
    otros_impuestos: 240,
    otros_impuestos_monto: 200,
    "invoice_line_ids/tax_ids": 220,
    __solo_encabezado: 130,
    __um_proveedor: 110,
    __um_empresa: 110,
    __oc_match_note: 220,
    [ADD_OTRO_IMPUESTO_KEY]: 44,
  };
  for (const c of cols) {
    if (c.key === "otros_impuestos" || /^otros_impuestos_\d+$/.test(c.key)) colMinWidth[c.key] = 240;
    if (c.key === "otros_impuestos_monto" || /^otros_impuestos_\d+_monto$/.test(c.key)) colMinWidth[c.key] = 200;
  }
  return colMinWidth;
}
