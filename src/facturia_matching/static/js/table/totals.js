import { computeRowTotal } from "../rows/index.js";
import {
  classifyComprobanteTaxMode,
  computeComprobanteTotals,
  listComprobanteGroups,
  resolveTaxModeForRow,
  showIvaMontoColumn,
  lineBase,
} from "../comprobanteTax/index.js";
import { formatMoney, formatNumericForDisplay, toNumberLoose } from "../utils/index.js";
import { isSoloEncabezado } from "../singleLine/index.js";

function rowSubtotal(row) {
  const fac = toNumberLoose(row?.__fac_subtotal);
  if (fac > 0) return fac;
  return lineBase(row);
}

function applyRowTotalToDom(state, rIdx) {
  const r = state.rows[rIdx];
  const rowTotal = state.rowTotals[rIdx];
  const { totalCells, ivaInputs, subtotalCells } = state.domRefs || {};
  const cell = totalCells?.[rIdx];
  if (cell) cell.textContent = formatMoney(rowTotal);
  const subCell = subtotalCells?.[rIdx];
  if (subCell) subCell.textContent = formatMoney(rowSubtotal(r));
  const mode = resolveTaxModeForRow(state, rIdx);
  const solo = isSoloEncabezado(r);
  if (!r?.__iva_monto_manual && showIvaMontoColumn(mode, solo)) {
    const ivaInp = ivaInputs?.[rIdx];
    if (ivaInp) ivaInp.value = formatNumericForDisplay(r.iva_monto, "iva_monto");
  }
}

export function mergeDomRefs(state, containerEl) {
  const totalCells = state.domRefs?.totalCells ? [...state.domRefs.totalCells] : [];
  const ivaInputs = state.domRefs?.ivaInputs ? [...state.domRefs.ivaInputs] : [];
  const subtotalCells = state.domRefs?.subtotalCells ? [...state.domRefs.subtotalCells] : [];
  containerEl.querySelectorAll("[data-total-r]").forEach((cell) => {
    const r = parseInt(cell.getAttribute("data-total-r"), 10);
    if (Number.isFinite(r)) totalCells[r] = cell;
  });
  containerEl.querySelectorAll("[data-subtotal-r]").forEach((cell) => {
    const r = parseInt(cell.getAttribute("data-subtotal-r"), 10);
    if (Number.isFinite(r)) subtotalCells[r] = cell;
  });
  containerEl.querySelectorAll('input[data-k="iva_monto"]').forEach((inp) => {
    const r = parseInt(inp.getAttribute("data-r"), 10);
    if (Number.isFinite(r)) ivaInputs[r] = inp;
  });
  state.domRefs = { totalCells, ivaInputs, subtotalCells };
}

export function updateRowTotals(state, refs, rIdx) {
  if (rIdx < 0 || rIdx >= state.rows.length) return;
  const mode = resolveTaxModeForRow(state, rIdx);
  state.rowTotals[rIdx] = computeRowTotal(state.rows[rIdx], mode);
  applyRowTotalToDom(state, rIdx);
  updateProcessTotals(state, refs);
}

export function updateProcessTotals(state, refs) {
  const groups = listComprobanteGroups(state.rows || []);
  let processTotal = 0;
  for (const g of groups) {
    const groupRows = g.rowIndices.map((i) => state.rows[i]);
    const mode =
      state.comprobanteTaxModes?.[String(g.compIdx)] || classifyComprobanteTaxMode(groupRows);
    processTotal += computeComprobanteTotals(groupRows, mode).totalOdoo;
  }
  if (refs?.totalGeneralEl) {
    refs.totalGeneralEl.textContent = formatMoney(processTotal);
  }
}

export function updateTotals(state, refs) {
  const tableWrap = refs?.tableWrap;
  const n = state.rows.length;
  state.rowTotals = new Array(n);
  const { totalCells, ivaInputs } = state.domRefs || {};
  for (let i = 0; i < n; i++) {
    const r = state.rows[i];
    const mode = resolveTaxModeForRow(state, i);
    const rowTotal = computeRowTotal(r, mode);
    state.rowTotals[i] = rowTotal;
    const cell = totalCells?.[i] ?? tableWrap?.querySelector(`[data-total-r="${i}"]`);
    if (cell) cell.textContent = formatMoney(rowTotal);
    if (!r.__iva_monto_manual && showIvaMontoColumn(mode, isSoloEncabezado(r))) {
      const ivaInp = ivaInputs?.[i] ?? tableWrap?.querySelector(`input[data-r="${i}"][data-k="iva_monto"]`);
      if (ivaInp) ivaInp.value = formatNumericForDisplay(r.iva_monto, "iva_monto");
    }
  }
  updateProcessTotals(state, refs);
}
