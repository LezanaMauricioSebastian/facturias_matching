import { toNumberLoose, otrosImpuestoKey, otrosImpuestoMontoKey } from "../utils/index.js";
import { lineBase, lineHasContent } from "./lineCalc.js";

const FAC_AMOUNT_LABELS = {
  percepcion_iibb: "IIBB",
  percepcion_iva: "Percepción IVA",
  // FacturIA manda el monto en `otros_tributos`; en Dinner/Odoo es Impuesto Interno.
  otros_tributos: "Impuesto Interno",
};

const CLAIMED_KEY = "__fac_otros_claimed";

/** Odoo label → amount_key FacturIA para reclamar el slot provisional con monto. */
export function amountKeyForOdooLabel(lab) {
  const s = String(lab || "").trim();
  if (!s) return null;
  if (/impuesto\s*interno|impuestos\s*internos|internal\s*tax/i.test(s)) {
    return "otros_tributos";
  }
  if (/iibb|ingresos\s*brutos/i.test(s)) return "percepcion_iibb";
  if (/perc(epci[oó]n)?[\s._-]*iva|perc\s*iva/i.test(s)) return "percepcion_iva";
  return null;
}

function slotNFromMontoKey(mk) {
  const key = String(mk || "").trim();
  if (key === "otros_impuestos_monto") return 1;
  const m = /^otros_impuestos_(\d+)_monto$/.exec(key);
  return m ? parseInt(m[1], 10) : null;
}

function pieMirrorKey(n) {
  return `__otros_pie_mirror_${n}`;
}

function slotLabel(row, n) {
  return String(row?.[otrosImpuestoKey(n)] ?? "").trim();
}

function slotMonto(row, n) {
  return toNumberLoose(row?.[otrosImpuestoMontoKey(n)]);
}

function isPieMirrorSlot(row, n, groupRows) {
  return !!(groupRows?.[0] === row && row?.[pieMirrorKey(n)]);
}

function getClaimedMap(first) {
  const raw = first?.[CLAIMED_KEY];
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  return raw;
}

function setClaimedLabel(first, amountKey, lab) {
  if (!first || !amountKey || !lab) return;
  const map = { ...getClaimedMap(first) };
  map[amountKey] = lab;
  first[CLAIMED_KEY] = map;
}

function claimedLabelForSlot(first, n) {
  const percs = first?.__fac_percepciones;
  if (!Array.isArray(percs)) return "";
  const mk = otrosImpuestoMontoKey(n);
  const claimed = getClaimedMap(first);
  for (const p of percs) {
    if (p?.ui_monto_key === mk) {
      return String(claimed[p.amount_key] || "").trim();
    }
  }
  return "";
}

function provisionalLabelForSlot(first, n) {
  const percs = first?.__fac_percepciones;
  if (!Array.isArray(percs)) return "";
  const montoKey = otrosImpuestoMontoKey(n);
  for (const p of percs) {
    if (p?.ui_monto_key === montoKey) {
      return FAC_AMOUNT_LABELS[p.amount_key] || "Otros impuestos";
    }
  }
  return "";
}

function amountKeyForFooterSlot(first, n) {
  const percs = first?.__fac_percepciones;
  if (!Array.isArray(percs)) return null;
  const mk = otrosImpuestoMontoKey(n);
  for (const p of percs) {
    if (p?.ui_monto_key === mk) return p.amount_key || null;
  }
  return null;
}

/** Label Odoo del slot N para el pie: 1ª fila (slot FacturIA) o fila con monto en ese slot. */
function lineLabelForFooterSlot(groupRows, n) {
  const first = groupRows?.[0];
  if (first && !isPieMirrorSlot(first, n, groupRows)) {
    const lab = slotLabel(first, n);
    if (lab) return lab;
  }
  for (const row of groupRows || []) {
    if (row === first) continue;
    if (isPieMirrorSlot(row, n, groupRows)) continue;
    const lab = slotLabel(row, n);
    if (!lab) continue;
    // Solo si esa fila tiene el monto del slot (asignación real, no otro impuesto en col 1).
    if (slotMonto(row, n) > 0) return lab;
  }
  return "";
}

function labelForFooterSlot(groupRows, n) {
  const first = groupRows?.[0];
  // Si el usuario ya asignó impuesto Odoo en el slot → mostrar ese nombre.
  // Si no, label provisional FacturIA (IIBB / Perc. IVA / Impuesto Interno).
  const lineLab = lineLabelForFooterSlot(groupRows, n);
  if (lineLab) return lineLab;
  return provisionalLabelForSlot(first, n) || "";
}

function findSlotWithLabel(row, lab, groupRows = null) {
  if (!lab) return null;
  for (let k = 1; k <= 20; k++) {
    if (slotLabel(row, k) !== lab) continue;
    if (groupRows && isPieMirrorSlot(row, k, groupRows)) continue;
    return k;
  }
  return null;
}

function findProvisionalSlotForAmountKey(groupRows, amountKey) {
  const first = groupRows?.[0];
  if (!first || !amountKey) return null;
  if (getClaimedMap(first)[amountKey]) {
    // Ya reclamado: devolver slot del monto FacturIA.
    const percs = first.__fac_percepciones;
    if (!Array.isArray(percs)) return null;
    for (const p of percs) {
      if (p?.amount_key === amountKey) return slotNFromMontoKey(p.ui_monto_key);
    }
    return null;
  }
  const percs = first.__fac_percepciones;
  if (!Array.isArray(percs)) return null;
  for (const p of percs) {
    if (p?.amount_key !== amountKey) continue;
    const n = slotNFromMontoKey(p.ui_monto_key);
    if (!n || !Number.isFinite(n)) continue;
    // No reclamar si la 1ª fila ya tiene un label real (multi-impuesto en esa línea).
    if (slotLabel(first, n) && !isPieMirrorSlot(first, n, groupRows)) continue;
    if (slotMonto(first, n) <= 0 && toNumberLoose(p.monto) <= 0) continue;
    return n;
  }
  return null;
}

/** Quita labels espejo del pie en la 1ª fila (no son impuestos de esa línea). */
export function stripPieMirrorLabelsFromFirstRow(groupRows) {
  const first = groupRows?.[0];
  if (!first) return false;
  let changed = false;
  for (let n = 1; n <= 20; n++) {
    if (!first[pieMirrorKey(n)]) continue;
    if (slotLabel(first, n)) {
      first[otrosImpuestoKey(n)] = "";
      changed = true;
    }
    delete first[pieMirrorKey(n)];
  }
  return changed;
}

/** Suma montos del pie: por label (sin espejos), o por índice N. */
function sumAmountForFooterSlot(groupRows, n, label) {
  let amount = 0;
  if (label) {
    for (const row of groupRows || []) {
      for (let k = 1; k <= 20; k++) {
        if (slotLabel(row, k) !== label) continue;
        if (isPieMirrorSlot(row, k, groupRows)) continue;
        amount += slotMonto(row, k);
      }
    }
    if (amount > 0) return amount;
  }
  for (const row of groupRows || []) {
    amount += slotMonto(row, n);
  }
  return amount;
}

function clearAmountsForFooterSlot(groupRows, n, label) {
  const mk = otrosImpuestoMontoKey(n);
  for (const row of groupRows || []) {
    row[mk] = "";
  }
  if (!label) return;
  for (const row of groupRows || []) {
    for (let k = 1; k <= 20; k++) {
      if (k === n) continue;
      if (slotLabel(row, k) === label && !isPieMirrorSlot(row, k, groupRows)) {
        row[otrosImpuestoMontoKey(k)] = "";
      }
    }
  }
}

function formatPortion(amount) {
  if (!Number.isFinite(amount) || Math.abs(amount) < 0.0001) return "";
  return String(Math.round(amount * 100) / 100);
}

/**
 * Reparte el monto del pie (slot N) entre filas de contenido que tienen el label
 * asignado (ignora espejos del pie), proporcional a qty×precio.
 * Si nadie lo tiene → 1ª fila con contenido.
 */
export function distributeOtrosFooterAmount(groupRows, slotN, normalized) {
  if (!groupRows?.length) return;
  const n = parseInt(slotN, 10);
  if (!Number.isFinite(n) || n < 1) return;

  const label = labelForFooterSlot(groupRows, n);
  clearAmountsForFooterSlot(groupRows, n, label);

  const raw = String(normalized ?? "").trim();
  if (!raw) return;

  const total = toNumberLoose(raw);
  const content = groupRows.filter(lineHasContent);
  const fallbackRow = content[0] || groupRows[0];

  if (total <= 0) {
    if (fallbackRow) fallbackRow[otrosImpuestoMontoKey(n)] = raw;
    return;
  }

  const assigned = [];
  const amountKey = amountKeyForFooterSlot(groupRows[0], n);
  if (label || amountKey) {
    for (const row of content) {
      for (let k = 1; k <= 20; k++) {
        const lab = slotLabel(row, k);
        if (!lab) continue;
        if (isPieMirrorSlot(row, k, groupRows)) continue;
        const key = amountKeyForOdooLabel(lab);
        if (amountKey && key === amountKey) {
          assigned.push({ row, slotN: k });
          break;
        }
        if (!amountKey && lab === label) {
          assigned.push({ row, slotN: k });
          break;
        }
      }
    }
  }

  const targets = assigned.length
    ? assigned
    : [{ row: fallbackRow, slotN: n }];

  if (!targets[0]?.row) return;

  if (targets.length === 1) {
    targets[0].row[otrosImpuestoMontoKey(targets[0].slotN)] = raw.includes(",")
      ? raw
      : formatPortion(total) || raw;
    return;
  }

  const bases = targets.map((t) => Math.max(0, lineBase(t.row)));
  const sumBase = bases.reduce((a, b) => a + b, 0);

  if (sumBase <= 0) {
    const each = Math.round((total / targets.length) * 100) / 100;
    let allocated = 0;
    for (let i = 0; i < targets.length; i++) {
      const portion =
        i === targets.length - 1
          ? Math.round((total - allocated) * 100) / 100
          : each;
      if (i < targets.length - 1) allocated += portion;
      targets[i].row[otrosImpuestoMontoKey(targets[i].slotN)] = formatPortion(portion);
    }
    return;
  }

  let allocated = 0;
  for (let i = 0; i < targets.length; i++) {
    let portion;
    if (i === targets.length - 1) {
      portion = Math.round((total - allocated) * 100) / 100;
    } else {
      portion = Math.round(((total * bases[i]) / sumBase) * 100) / 100;
      allocated += portion;
    }
    targets[i].row[otrosImpuestoMontoKey(targets[i].slotN)] = formatPortion(portion);
  }
}

/** Copia montos de `__fac_percepciones` a slots vacíos de la 1ª fila. */
export function hydrateOtrosSlotsFromFacPercepciones(groupRows) {
  if (!groupRows?.length) return;
  const first = groupRows[0];
  const percs = first?.__fac_percepciones;
  if (!Array.isArray(percs)) return;
  for (const p of percs) {
    const mk = p?.ui_monto_key;
    const monto = p?.monto;
    if (!mk || monto == null || String(monto).trim() === "") continue;
    if (String(first[mk] ?? "").trim()) continue;
    first[mk] = String(monto).trim();
  }
}

/** Máximo índice de slot con label o monto en el grupo. */
export function maxOtrosSlotN(groupRows) {
  let maxN = 0;
  for (const row of groupRows || []) {
    if (slotLabel(row, 1) || slotMonto(row, 1) > 0) maxN = Math.max(maxN, 1);
    for (let n = 2; n <= 20; n++) {
      if (slotLabel(row, n) || slotMonto(row, n) > 0) maxN = Math.max(maxN, n);
    }
  }
  return maxN;
}

/**
 * Desglose de otros impuestos para el pie.
 * Con label Odoo en el slot → ese nombre; si no → provisional FacturIA + montos.
 * Slots con label y monto 0 también van al pie (flujo «+»: elegir impuesto y cargar monto abajo).
 */
export function computeOtrosBreakdown(groupRows) {
  if (!groupRows?.length) return [];
  hydrateOtrosSlotsFromFacPercepciones(groupRows);
  stripPieMirrorLabelsFromFirstRow(groupRows);
  const maxN = maxOtrosSlotN(groupRows);
  if (maxN < 1) return [];

  const rows = [];
  for (let n = 1; n <= maxN; n++) {
    let label = labelForFooterSlot(groupRows, n);
    const amount = sumAmountForFooterSlot(groupRows, n, label);
    if (!label && amount > 0) label = "Otros impuestos";
    // Sin label ni monto → no hay fila. Con label (aunque monto 0) sí, para poder editar en el pie.
    if (!label) continue;
    rows.push({
      slotN: n,
      slotKey: String(n),
      label: label || "Otros impuestos",
      amount,
      editable: true,
    });
  }
  return rows;
}

/**
 * Impuestos FacturIA del pie que aún no tienen label Odoo en las líneas.
 * Cubierto si el slot FacturIA tiene cualquier label en una línea, o si algún
 * label mapea al amount_key (IIBB / Perc. IVA / Interno).
 */
export function missingFacOtrosAssignments(groupRows) {
  if (!groupRows?.length) return [];
  hydrateOtrosSlotsFromFacPercepciones(groupRows);
  stripPieMirrorLabelsFromFirstRow(groupRows);
  const first = groupRows[0];
  const percs = first?.__fac_percepciones;
  if (!Array.isArray(percs) || !percs.length) return [];

  const covered = new Set();
  const coveredSlots = new Set();
  for (const row of groupRows) {
    for (let n = 1; n <= 20; n++) {
      if (isPieMirrorSlot(row, n, groupRows)) continue;
      const lab = slotLabel(row, n);
      if (!lab) continue;
      coveredSlots.add(n);
      const key = amountKeyForOdooLabel(lab);
      if (key) covered.add(key);
    }
  }

  const missing = [];
  for (const p of percs) {
    if (toNumberLoose(p?.monto) <= 0) continue;
    const key = p?.amount_key;
    if (!key || covered.has(key)) continue;
    const slotN = slotNFromMontoKey(p?.ui_monto_key);
    if (slotN && coveredSlots.has(slotN)) continue;
    missing.push(FAC_AMOUNT_LABELS[key] || String(key));
  }
  return missing;
}

/**
 * Solo para multi-impuesto real en la 1ª línea (el usuario usó + en esa fila).
 * No espeja impuestos de otras líneas ni renombra el pie FacturIA.
 */
export function ensureOtrosLabelOnFirstRow(groupRows, label, opts = {}) {
  const lab = String(label ?? "").trim();
  if (!lab || !groupRows?.length) return null;
  const first = groupRows[0];
  const selectedIsFirst = opts.selectedRow === first;

  stripPieMirrorLabelsFromFirstRow(groupRows);
  if (!selectedIsFirst) return null;

  for (let n = 1; n <= 20; n++) {
    if (slotLabel(first, n) === lab) return n;
  }
  for (let n = 1; n <= 20; n++) {
    if (!slotLabel(first, n) && slotMonto(first, n) <= 0) {
      first[otrosImpuestoKey(n)] = lab;
      if (first[otrosImpuestoMontoKey(n)] == null) first[otrosImpuestoMontoKey(n)] = "";
      delete first[pieMirrorKey(n)];
      return n;
    }
  }
  return null;
}

/**
 * @deprecated El pie ya no reclama labels Odoo; se mantiene por compat de imports.
 */
export function claimProvisionalOtrosFromLineLabels(_groupRows) {
  return false;
}

/** Máximo slot con label/monto real en una fila (no cuenta espejos). */
export function maxOtrosSlotNOnRow(row) {
  if (!row) return 0;
  let maxN = 0;
  for (let n = 1; n <= 20; n++) {
    if (row[pieMirrorKey(n)]) continue;
    if (slotLabel(row, n) || slotMonto(row, n) > 0) maxN = Math.max(maxN, n);
  }
  return maxN;
}

/** Escribe el monto del pie repartido entre filas con ese impuesto asignado. */
export function setOtrosFooterAmount(groupRows, slotN, normalized) {
  distributeOtrosFooterAmount(groupRows, slotN, normalized);
}

export { FAC_AMOUNT_LABELS };
