/**
 * Modo "Solo encabezado": una fila por comprobante.
 * Totales a nivel factura vienen del backend (__fac_*); listas de claves en app.py.
 */
import { formatNumberEsAR, normalizeNumericValue, toNumberLoose } from "../utils/index.js";
import { ensureOtroImpuestoColumns } from "../rows/index.js";
import { groupBounds } from "./groups.js";

const BACKUP_KEY = "__solo_encabezado_backup";

function cloneRows(rows) {
  return JSON.parse(JSON.stringify(rows));
}

/** Total IVA FacturIA: `__fac_iva_monto` o suma de `__fac_iva_montos`. */
function resolveFacIvaMonto(row) {
  const direct = String(row?.__fac_iva_monto ?? "").trim();
  if (direct) return direct;
  const raw = row?.__fac_iva_montos;
  if (!raw) return "";
  try {
    const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
    if (!parsed || typeof parsed !== "object") return "";
    let sum = 0;
    for (const [k, v] of Object.entries(parsed)) {
      if (k === "_total") continue;
      sum += toNumberLoose(v);
    }
    if (sum <= 0) return "";
    return formatNumberEsAR(Math.round(sum * 100) / 100, 2, 2);
  } catch {
    return "";
  }
}

function applyFacPercepcionesToRow(row, state = null, { force = false } = {}) {
  const percs = row.__fac_percepciones;
  if (!Array.isArray(percs)) return;
  for (const p of percs) {
    const mk = p?.ui_monto_key;
    const monto = p?.monto;
    if (!mk || monto == null || String(monto).trim() === "") continue;
    let n = 1;
    const m = /^otros_impuestos_(\d+)_monto$/.exec(mk);
    if (m) n = parseInt(m[1], 10);
    else if (mk !== "otros_impuestos_monto") continue;
    // Solo slot 1 abre columna; montos 2..N alimentan el pie sin columnas vacías.
    if (state && n <= 1) ensureOtroImpuestoColumns(state, 1);
    const prevMonto = row[mk];
    if (force || !String(prevMonto ?? "").trim()) {
      row[mk] = normalizeNumericValue(String(monto), mk);
    }
  }
}

/**
 * Copia montos del encabezado FacturIA a la fila.
 * @param {{ force?: boolean }} [opts] — `force` pisa iva/otros de línea (necesario al colapsar).
 */
export function syncSoloEncabezadoMontos(row, state = null, opts = {}) {
  const force = !!opts.force;
  if (state) ensureOtroImpuestoColumns(state, 1);
  const ivaFromFac = resolveFacIvaMonto(row);
  if (ivaFromFac) {
    const normalized = normalizeNumericValue(ivaFromFac, "iva_monto");
    row.__fac_iva_monto = normalized;
    if (force || !String(row.iva_monto ?? "").trim()) {
      row.iva_monto = normalized;
      row.__iva_monto_manual = true;
    }
  }
  applyFacPercepcionesToRow(row, state, { force });
}

/** Copia montos del encabezado FacturIA a la fila y activa Solo encabezado. */
export function prepareSoloEncabezadoRow(row, state = null, opts = {}) {
  syncSoloEncabezadoMontos(row, state, { force: true, ...opts });
  row.__solo_encabezado = true;
}

/**
 * Colapsa el comprobante que empieza en `rIdx` (debe ser la primera fila del grupo).
 * Guarda las filas originales en `__solo_encabezado_backup` para poder restaurar al destildar.
 * @param {object|null} state — opcional; si se pasa, crea columnas de otros impuestos extra
 * @returns {{ changed: boolean, removed: number }}
 */
export function collapseGroupAtRow(rows, rIdx, state = null) {
  const [s, e] = groupBounds(rows, rIdx);
  if (rIdx !== s || e - s <= 1) return { changed: false, removed: 0 };

  const backup = cloneRows(rows.slice(s, e));
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
  delete first["__overwrite_oc_price"];
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

  // No conservar IVA/otros de la 1ª línea: al compactar mandan los montos FacturIA.
  first.iva_monto = "";
  delete first.__iva_monto_manual;

  const ivaFromFac = resolveFacIvaMonto(first);
  if (ivaFromFac) {
    first.__fac_iva_monto = normalizeNumericValue(ivaFromFac, "iva_monto");
  }

  prepareSoloEncabezadoRow(first, state, { force: true });
  first[BACKUP_KEY] = backup;

  const removed = e - s - 1;
  if (removed > 0) rows.splice(s + 1, removed);
  return { changed: true, removed };
}

/**
 * Destilda Solo encabezado: restaura las líneas del backup si existen.
 * @returns {{ changed: boolean, restored: number }}
 */
export function expandSoloEncabezadoAtRow(rows, rIdx) {
  const row = rows[rIdx];
  if (!row) return { changed: false, restored: 0 };

  const backup = row[BACKUP_KEY];
  if (Array.isArray(backup) && backup.length > 1) {
    const restored = cloneRows(backup).map((r) => {
      delete r[BACKUP_KEY];
      r.__solo_encabezado = false;
      return r;
    });
    rows.splice(rIdx, 1, ...restored);
    return { changed: true, restored: restored.length };
  }

  row.__solo_encabezado = false;
  delete row[BACKUP_KEY];
  return { changed: true, restored: 0 };
}
