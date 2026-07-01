import { computeRowTotal } from "../rows/index.js";
import {
  classifyComprobanteTaxMode,
  computeComprobanteTotals,
  listComprobanteGroups,
  resolveTaxModeForRow,
  showIvaMontoColumn,
} from "../comprobanteTax/index.js";
import { formatMoney, formatNumericForDisplay } from "../utils/index.js";

function applyRowTotalToDom(state, rIdx) {
  const r = state.rows[rIdx];
  const rowTotal = state.rowTotals[rIdx];
  const { totalCells, ivaInputs } = state.domRefs || {};
  const cell = totalCells?.[rIdx];
  if (cell) cell.textContent = formatMoney(rowTotal);
  const mode = resolveTaxModeForRow(state, rIdx);
  if (!r?.__iva_monto_manual && showIvaMontoColumn(mode)) {
    const ivaInp = ivaInputs?.[rIdx];
    if (ivaInp) ivaInp.value = formatNumericForDisplay(r.iva_monto, "iva_monto");
  }
}

export function mergeDomRefs(state, containerEl) {
  const totalCells = state.domRefs?.totalCells ? [...state.domRefs.totalCells] : [];
  const ivaInputs = state.domRefs?.ivaInputs ? [...state.domRefs.ivaInputs] : [];
  containerEl.querySelectorAll("[data-total-r]").forEach((cell) => {
    const r = parseInt(cell.getAttribute("data-total-r"), 10);
    if (Number.isFinite(r)) totalCells[r] = cell;
  });
  containerEl.querySelectorAll('input[data-k="iva_monto"]').forEach((inp) => {
    const r = parseInt(inp.getAttribute("data-r"), 10);
    if (Number.isFinite(r)) ivaInputs[r] = inp;
  });
  state.domRefs = { totalCells, ivaInputs };
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
    if (!r.__iva_monto_manual && showIvaMontoColumn(mode)) {
      const ivaInp = ivaInputs?.[i] ?? tableWrap?.querySelector(`input[data-r="${i}"][data-k="iva_monto"]`);
      if (ivaInp) ivaInp.value = formatNumericForDisplay(r.iva_monto, "iva_monto");
    }
  }
  updateProcessTotals(state, refs);
}
