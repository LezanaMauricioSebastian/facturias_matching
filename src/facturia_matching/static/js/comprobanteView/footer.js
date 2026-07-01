import {
  listComprobanteGroups,
  classifyComprobanteTaxMode,
  computeComprobanteTotals,
  comprobanteGroupByIdx,
  computeIvaBreakdown,
  parseFacIvaMontos,
  serializeFacIvaMontos,
} from "../comprobanteTax/index.js";
import {
  formatMoney,
  formatNumericForDisplay,
  normalizeNumericValue,
  escapeHtml,
} from "../utils/index.js";
import { updateProcessTotals, updateRowTotals } from "../table/index.js";

function footerMoneyCell(n) {
  return n == null || Number.isNaN(n) ? "—" : formatMoney(n);
}

function renderIvaFooterRows(totals, compIdx, groupRows) {
  const breakdown = totals.ivaBreakdown || computeIvaBreakdown(groupRows, totals);
  if (!breakdown.length) {
    return `<tr>
            <td>IVA</td>
            <td><span class="comprobanteFooterReadonly">—</span></td>
          </tr>`;
  }
  return breakdown
    .map((row) => {
      const shown = row.amount > 0 ? formatNumericForDisplay(row.amount, "iva_monto") : "";
      const cell = row.editable
        ? `<input type="text" inputmode="decimal" class="comprobanteFooterInput"
                data-comp-footer-iva="${escapeHtml(compIdx)}"
                data-iva-rate-key="${escapeHtml(row.rateKey)}"
                value="${escapeHtml(shown)}" />`
        : `<span class="comprobanteFooterReadonly" data-comp-footer-iva-readonly="${escapeHtml(compIdx)}" data-iva-rate-key="${escapeHtml(row.rateKey)}">${footerMoneyCell(row.amount)}</span>`;
      return `<tr>
            <td>${escapeHtml(row.label)}</td>
            <td>${cell}</td>
          </tr>`;
    })
    .join("");
}

export function renderFooterHtml(totals, compIdx, groupRows) {
  const otrosVal = totals.otros || 0;
  const otrosShown = otrosVal > 0 ? formatNumericForDisplay(otrosVal, "otros_impuestos_monto") : "";
  return `<div class="comprobanteFooter">
      <table class="comprobanteTotalsTable">
        <tbody>
          <tr>
            <td>Base imponible</td>
            <td class="comprobanteFooterReadonly" data-comp-footer-base="${escapeHtml(compIdx)}">${footerMoneyCell(totals.baseOdoo)}</td>
          </tr>
          ${renderIvaFooterRows(totals, compIdx, groupRows)}
          <tr>
            <td>Otros impuestos</td>
            <td>
              <input type="text" inputmode="decimal" class="comprobanteFooterInput"
                data-comp-footer-otros="${escapeHtml(compIdx)}" value="${escapeHtml(otrosShown)}" />
            </td>
          </tr>
          <tr class="totalsGrand">
            <td>Total</td>
            <td class="comprobanteFooterReadonly" data-comp-footer-total="${escapeHtml(compIdx)}">${footerMoneyCell(totals.totalOdoo)}</td>
          </tr>
        </tbody>
      </table>
    </div>`;
}

function firstRowOfComp(state, compIdx) {
  const g = comprobanteGroupByIdx(state.rows, compIdx);
  if (!g?.rowIndices?.length) return null;
  return state.rows[g.rowIndices[0]];
}

function groupRowsOfComp(state, compIdx) {
  const g = comprobanteGroupByIdx(state.rows, compIdx);
  if (!g) return [];
  return g.rowIndices.map((i) => state.rows[i]);
}

function setFooterIvaAmount(state, compIdx, rateKey, rawValue) {
  const groupRows = groupRowsOfComp(state, compIdx);
  if (!groupRows.length) return;
  const normalized = normalizeNumericValue(rawValue, "iva_monto");
  const montos = parseFacIvaMontos(groupRows);
  if (rateKey === "_total") {
    const first = firstRowOfComp(state, compIdx);
    if (first) first.__fac_iva_monto = normalized;
    delete montos._total;
  } else if (normalized) {
    montos[rateKey] = normalized;
  } else {
    delete montos[rateKey];
  }
  serializeFacIvaMontos(groupRows, montos);
}

function setComprobanteFooterOtros(state, compIdx, rawValue) {
  const g = comprobanteGroupByIdx(state.rows, compIdx);
  if (!g) return;
  const normalized = normalizeNumericValue(rawValue, "otros_impuestos_monto");
  for (const idx of g.rowIndices) {
    state.rows[idx].otros_impuestos_monto = "";
    for (let n = 2; n <= 20; n++) {
      state.rows[idx][`otros_impuestos_${n}_monto`] = "";
    }
  }
  const first = state.rows[g.rowIndices[0]];
  if (first) first.otros_impuestos_monto = normalized;
}

function refreshComprobanteRowTotals(state, refs, compIdx) {
  const g = comprobanteGroupByIdx(state.rows, compIdx);
  if (!g) return;
  for (const idx of g.rowIndices) updateRowTotals(state, refs, idx);
}

export function attachComprobanteFooterHandlers(wrap, state, refs, handlers) {
  wrap.querySelectorAll("[data-comp-footer-iva]").forEach((inp) => {
    const onIvaChange = (e) => {
      const comp = e.target.getAttribute("data-comp-footer-iva");
      const rateKey = e.target.getAttribute("data-iva-rate-key") || "_total";
      setFooterIvaAmount(state, comp, rateKey, e.target.value);
      updateComprobanteFooters(state, refs);
      handlers.onAutoSave?.();
    };
    inp.addEventListener("input", onIvaChange);
    inp.addEventListener("blur", (e) => {
      const comp = e.target.getAttribute("data-comp-footer-iva");
      const rateKey = e.target.getAttribute("data-iva-rate-key") || "_total";
      const normalized = normalizeNumericValue(e.target.value, "iva_monto");
      setFooterIvaAmount(state, comp, rateKey, normalized);
      e.target.value = normalized ? formatNumericForDisplay(normalized, "iva_monto") : "";
      updateComprobanteFooters(state, refs);
      refreshComprobanteRowTotals(state, refs, comp);
      handlers.onAutoSave?.();
    });
  });

  wrap.querySelectorAll("[data-comp-footer-otros]").forEach((inp) => {
    inp.addEventListener("input", (e) => {
      const comp = e.target.getAttribute("data-comp-footer-otros");
      setComprobanteFooterOtros(state, comp, e.target.value);
      updateComprobanteFooters(state, refs);
      handlers.onAutoSave?.();
    });
    inp.addEventListener("blur", (e) => {
      const comp = e.target.getAttribute("data-comp-footer-otros");
      setComprobanteFooterOtros(state, comp, e.target.value);
      const normalized = normalizeNumericValue(e.target.value, "otros_impuestos_monto");
      e.target.value = normalized ? formatNumericForDisplay(normalized, "otros_impuestos_monto") : "";
      updateComprobanteFooters(state, refs);
      refreshComprobanteRowTotals(state, refs, comp);
      handlers.onAutoSave?.();
    });
  });
}

/** Actualiza pies de comprobante sin re-renderizar tablas (edición en curso). */
export function updateComprobanteFooters(state, refs) {
  const wrap = refs?.tableWrap;
  if (!wrap || !state.rows?.length) return;
  for (const g of listComprobanteGroups(state.rows)) {
    const card = wrap.querySelector(`.comprobanteCard[data-comp="${CSS.escape(String(g.compIdx))}"]`);
    if (!card) continue;
    const groupRows = g.rowIndices.map((i) => state.rows[i]);
    const compKey = String(g.compIdx);
    const mode = state.comprobanteTaxModes?.[compKey] || classifyComprobanteTaxMode(groupRows);
    state.comprobanteTaxModes[compKey] = mode;
    const totals = computeComprobanteTotals(groupRows, mode);
    const breakdown = totals.ivaBreakdown || computeIvaBreakdown(groupRows, totals);

    const baseCell = card.querySelector(`[data-comp-footer-base="${CSS.escape(compKey)}"]`);
    if (baseCell) baseCell.textContent = footerMoneyCell(totals.baseOdoo);

    card.querySelectorAll("[data-comp-footer-iva]").forEach((ivaInp) => {
      if (document.activeElement === ivaInp) return;
      const rateKey = ivaInp.getAttribute("data-iva-rate-key") || "_total";
      const row = breakdown.find((b) => b.rateKey === rateKey);
      const ivaVal = row?.amount || 0;
      ivaInp.value = ivaVal > 0 ? formatNumericForDisplay(ivaVal, "iva_monto") : "";
    });

    card.querySelectorAll("[data-comp-footer-iva-readonly]").forEach((ivaCell) => {
      const rateKey = ivaCell.getAttribute("data-iva-rate-key") || "_total";
      const row = breakdown.find((b) => b.rateKey === rateKey);
      ivaCell.textContent = footerMoneyCell(row?.amount || 0);
    });

    const otrosInp = card.querySelector(`[data-comp-footer-otros="${CSS.escape(compKey)}"]`);
    if (otrosInp && document.activeElement !== otrosInp) {
      otrosInp.value =
        totals.otros > 0 ? formatNumericForDisplay(totals.otros, "otros_impuestos_monto") : "";
    }

    const totalCell = card.querySelector(`[data-comp-footer-total="${CSS.escape(compKey)}"]`);
    if (totalCell) totalCell.textContent = footerMoneyCell(totals.totalOdoo);

    card.querySelector(".comprobanteModeHint")?.remove();
    card.querySelector(".comprobanteWarnings")?.remove();
  }
  updateProcessTotals(state, refs);
}
