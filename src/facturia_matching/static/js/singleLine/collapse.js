/**
 * Modo "Solo encabezado": una fila por comprobante.
 * Totales a nivel factura vienen del backend (__fac_*); listas de claves en app.py.
 */
import { formatNumberEsAR, normalizeNumericValue, toNumberLoose } from "../utils/index.js";
import { ensureOtroImpuestoColumns } from "../rows/index.js";
import { groupBounds } from "./groups.js";

/**
 * Colapsa el comprobante que empieza en `rIdx` (debe ser la primera fila del grupo).
 * @param {object|null} state — opcional; si se pasa, crea columnas de otros impuestos extra
 * @returns {{ changed: boolean, removed: number }}
 */
export function collapseGroupAtRow(rows, rIdx, state = null) {
  const [s, e] = groupBounds(rows, rIdx);
  if (rIdx !== s || e - s <= 1) return { changed: false, removed: 0 };

  const first = rows[s];
  const subFromFac = String(first.__fac_subtotal ?? "").trim();
  let priceUnit = subFromFac ? normalizeNumericValue(subFromFac, "invoice_line_ids/price_unit") : "";
  if (!priceUnit) {
    let sum = 0;
    for (let j = s; j < e; j++) {
      sum +=
        toNumberLoose(rows[j]["invoice_line_ids/quantity"]) *
        toNumberLoose(rows[j]["invoice_line_ids/price_unit"]);
    }
    priceUnit = formatNumberEsAR(Math.round(sum * 1e6) / 1e6, 6, 0);
  }

  first["invoice_line_ids/quantity"] = "1";
  first["invoice_line_ids/price_unit"] = priceUnit;

  first["invoice_line_ids/product_id"] = "";
  delete first["Nombre de producto"];
  delete first["__item_codigo"];
  delete first["__oc_line_id"];
  delete first["__oc_order_id"];
  delete first["__selected_oc_order_id"];
  delete first["__selected_oc_name"];
  delete first["__oc_line_name"];
  delete first["__oc_match_score"];
  delete first["__qty_pedido"];
  delete first["__qty_recibido"];
  delete first["__qty_facturado_po"];
  delete first["__qty_original"];
  delete first["__qty_escalada"];
  delete first["__um_factor"];
  if (!String(first["invoice_line_ids/name"] ?? "").trim()) {
    first["invoice_line_ids/name"] = "Factura compactada";
  }

  const ivaFromFac = String(first.__fac_iva_monto ?? "").trim();
  if (ivaFromFac) {
    first.__fac_iva_monto = normalizeNumericValue(ivaFromFac, "iva_monto");
  }
  first.iva_monto = "";
  delete first.__iva_monto_manual;

  const percs = first.__fac_percepciones;
  if (Array.isArray(percs)) {
    for (const p of percs) {
      const mk = p?.ui_monto_key;
      const monto = p?.monto;
      if (!mk || monto == null || String(monto).trim() === "") continue;
      let n = 1;
      const m = /^otros_impuestos_(\d+)_monto$/.exec(mk);
      if (m) n = parseInt(m[1], 10);
      else if (mk !== "otros_impuestos_monto") continue;
      if (state) ensureOtroImpuestoColumns(state, n);
      const prevMonto = first[mk];
      if (!String(prevMonto ?? "").trim()) {
        first[mk] = normalizeNumericValue(String(monto), mk);
      }
    }
  }

  const removed = e - s - 1;
  if (removed > 0) rows.splice(s + 1, removed);
  return { changed: true, removed };
}
