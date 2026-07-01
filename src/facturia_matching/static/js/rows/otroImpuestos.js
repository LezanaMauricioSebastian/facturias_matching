import { otrosImpuestoKey, otrosImpuestoMontoKey } from "../utils/index.js";

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
    label: "Impuesto",
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

export function removeOtroImpuesto(state, n) {
  if (n < 2) return false;
  const nameKey = otrosImpuestoKey(n);
  const montoKey = otrosImpuestoMontoKey(n);
  state.columns = state.columns.filter((c) => c.key !== nameKey && c.key !== montoKey);
  for (const r of state.rows) {
    delete r[nameKey];
    delete r[montoKey];
  }
  ensureAddOtroImpuestoActionColumn(state);
  return true;
}

export function resetExtraOtroImpuestoColumns(state) {
  const maxN = currentMaxOtroImpuestoN(state.columns);
  for (let n = maxN; n >= 2; n--) {
    removeOtroImpuesto(state, n);
  }
}

export function restoreExtraOtroImpuestoColumns(state, indices) {
  if (!Array.isArray(indices)) return;
  for (const n of indices) {
    const num = parseInt(n, 10);
    if (num >= 2) ensureOtroImpuestoColumns(state, num);
  }
  ensureAddOtroImpuestoActionColumn(state);
}

export function ensureOtroImpuestoColumns(state, n) {
  const nameKey = otrosImpuestoKey(n);
  const montoKey = otrosImpuestoMontoKey(n);
  const hasName = state.columns.some((c) => c.key === nameKey);
  const hasMonto = state.columns.some((c) => c.key === montoKey);
  const actionIdx = state.columns.findIndex((c) => c.key === ADD_OTRO_IMPUESTO_KEY);
  const insertAt =
    actionIdx >= 0 ? actionIdx : findAddOtroImpuestoInsertAt(state.columns);
  if (!hasMonto) {
    const label = n === 1 ? "Monto Otros Impuestos" : `Monto Otros Impuestos (${n})`;
    state.columns.splice(insertAt, 0, { key: montoKey, label, type: "numeric" });
  }
  if (!hasName) {
    const label = n === 1 ? "Otros Impuestos" : `Otros Impuestos (${n})`;
    const nameInsertAt = insertAt + (hasMonto ? 1 : 0);
    state.columns.splice(nameInsertAt, 0, { key: nameKey, label, type: "selection", options_key: "otros_impuestos_options" });
  }
  for (const r of state.rows) {
    if (r[nameKey] == null) r[nameKey] = "";
    if (r[montoKey] == null) r[montoKey] = "";
  }
}
