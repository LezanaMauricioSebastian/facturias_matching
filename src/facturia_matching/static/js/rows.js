import {
  formatNumberEsAR,
  normalizeIvaPctValue,
  otrosImpuestoKey,
  otrosImpuestoMontoKey,
  toNumberLoose,
} from "./utils.js";

export function migrateRowKeys(row) {
  if (!row || typeof row !== "object") return;
  if (row.etiqueta != null && row["invoice_line_ids/name"] == null) {
    row["invoice_line_ids/name"] = row.etiqueta;
  }
  if (row.cuenta != null && row["invoice_line_ids/account_id"] == null) {
    row["invoice_line_ids/account_id"] = row.cuenta;
  }
  if (row.otros_impuesto_1 != null && row.otros_impuestos == null) {
    row.otros_impuestos = row.otros_impuesto_1;
  }
  for (let n = 2; n <= 20; n++) {
    const oldK = `otros_impuesto_${n}`;
    const newK = otrosImpuestoKey(n);
    if (row[oldK] != null && row[newK] == null) row[newK] = row[oldK];
  }
  if (row.iva_monto == null) row.iva_monto = "";
  if (row.otros_impuestos_monto == null) row.otros_impuestos_monto = "";
  if (row.iva_pct != null && String(row.iva_pct).trim()) {
    row.iva_pct = normalizeIvaPctValue(row.iva_pct);
  }
}

export function applyProveedorToCuit(state, rIdx) {
  const row = state.rows?.[rIdx];
  if (!row) return;
  const prov = (row.partner_id ?? "").toString();
  if (!prov) return;
  const map = state.options?.proveedores_cuit_map || {};
  const cuit = map[prov];
  if (cuit) row.CUIT = cuit;
}

export function computeRowTotal(row) {
  const qtyKey = "invoice_line_ids/quantity";
  const priceKey = "invoice_line_ids/price_unit";
  const ivaKey = "iva_pct";
  const ivaMontoKey = "iva_monto";
  const q = toNumberLoose(row?.[qtyKey]);
  const p = toNumberLoose(row?.[priceKey]);
  const iva = toNumberLoose(row?.[ivaKey]);
  const base = q * p;

  const suggestedIvaMonto = base * (iva > 0 ? iva / 100 : 0);
  const manualIvaMonto = !!row?.__iva_monto_manual;
  const ivaMonto = manualIvaMonto ? toNumberLoose(row?.[ivaMontoKey]) : suggestedIvaMonto;
  if (!manualIvaMonto) row[ivaMontoKey] = formatNumberEsAR(Math.round(ivaMonto * 100) / 100, 2, 2);

  let otrosMonto = toNumberLoose(row?.["otros_impuestos_monto"]);
  for (let n = 2; n <= 20; n++) {
    const mk = otrosImpuestoMontoKey(n);
    otrosMonto += toNumberLoose(row?.[mk]);
  }

  return base + ivaMonto + otrosMonto;
}

export function propagateAccountDown(rows) {
  for (let i = 1; i < rows.length; i++) {
    const prev = rows[i - 1];
    const cur = rows[i];
    const prevNro = String(prev?.["l10n_latam_document_number"] ?? "").trim();
    const curNro = String(cur?.["l10n_latam_document_number"] ?? "").trim();
    if (!curNro && prevNro) {
      const ak = "invoice_line_ids/account_id";
      if (!String(cur?.[ak] ?? "").trim() && String(prev?.[ak] ?? "").trim()) cur[ak] = prev[ak];
    }
  }
}

export const ADD_OTRO_IMPUESTO_KEY = "__add_otro_impuesto";

function isOtroImpuestoDataColumnKey(key) {
  return (
    key === "otros_impuestos" ||
    key === "otros_impuestos_monto" ||
    /^otros_impuestos_\d+$/.test(key) ||
    /^otros_impuestos_\d+_monto$/.test(key)
  );
}

/** Índice donde insertar columnas de impuesto / el botón: justo después del último Otros Impuestos. */
export function findAddOtroImpuestoInsertAt(columns) {
  let lastTaxIdx = -1;
  for (let i = 0; i < columns.length; i++) {
    if (isOtroImpuestoDataColumnKey(columns[i].key)) {
      lastTaxIdx = i;
    }
  }
  if (lastTaxIdx >= 0) return lastTaxIdx + 1;
  const purchaseIdx = columns.findIndex((c) => c.key === "__um_proveedor");
  if (purchaseIdx >= 0) return purchaseIdx;
  const totalIdx = columns.findIndex((c) => c.key === "__total_linea");
  return totalIdx >= 0 ? totalIdx : columns.length;
}

export function ensureAddOtroImpuestoActionColumn(state) {
  const insertAt = findAddOtroImpuestoInsertAt(state.columns);
  const existing = state.columns.findIndex((c) => c.key === ADD_OTRO_IMPUESTO_KEY);
  if (existing >= 0) {
    if (existing !== insertAt) {
      const [col] = state.columns.splice(existing, 1);
      const newInsertAt = findAddOtroImpuestoInsertAt(state.columns);
      state.columns.splice(newInsertAt, 0, col);
    }
    return;
  }
  state.columns.splice(insertAt, 0, {
    key: ADD_OTRO_IMPUESTO_KEY,
    label: "Agregar otro impuesto",
    type: "header_action",
    editable: false,
  });
}

export function addOtroImpuesto(state) {
  const maxBefore = currentMaxOtroImpuestoN(state.columns);
  const next = maxBefore + 1;
  ensureOtroImpuestoColumns(state, next);
  ensureAddOtroImpuestoActionColumn(state);
  return { maxBefore, next };
}

export function currentMaxOtroImpuestoN(columns) {
  let maxN = 1;
  for (const c of columns) {
    if (c.key === "otros_impuestos") {
      maxN = Math.max(maxN, 1);
      continue;
    }
    const m = /^otros_impuestos_(\d+)$/.exec(c.key);
    if (m) maxN = Math.max(maxN, parseInt(m[1], 10));
    const mm = /^otros_impuestos_(\d+)_monto$/.exec(c.key);
    if (mm) maxN = Math.max(maxN, parseInt(mm[1], 10));
  }
  return maxN;
}

export function ensureOtroImpuestoColumns(state, n) {
  const nameKey = otrosImpuestoKey(n);
  const montoKey = otrosImpuestoMontoKey(n);
  const hasName = state.columns.some((c) => c.key === nameKey);
  const hasMonto = state.columns.some((c) => c.key === montoKey);
  const actionIdx = state.columns.findIndex((c) => c.key === ADD_OTRO_IMPUESTO_KEY);
  const insertAt =
    actionIdx >= 0 ? actionIdx : findAddOtroImpuestoInsertAt(state.columns);
  if (!hasName) {
    const label = n === 1 ? "Otros Impuestos" : `Otros Impuestos (${n})`;
    state.columns.splice(insertAt, 0, { key: nameKey, label, type: "selection", options_key: "otros_impuestos_options" });
  }
  if (!hasMonto) {
    const label = n === 1 ? "Monto Otros Impuestos" : `Monto Otros Impuestos (${n})`;
    state.columns.splice(insertAt + (hasName ? 0 : 1), 0, { key: montoKey, label, type: "numeric" });
  }
  for (const r of state.rows) {
    if (r[nameKey] == null) r[nameKey] = "";
    if (r[montoKey] == null) r[montoKey] = "";
  }
}

