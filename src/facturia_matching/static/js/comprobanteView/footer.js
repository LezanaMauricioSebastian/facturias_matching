import {
  listComprobanteGroups,
  classifyComprobanteTaxMode,
  computeComprobanteTotals,
  comprobanteGroupByIdx,
  computeIvaBreakdown,
  parseFacIvaMontos,
  serializeFacIvaMontos,
  shouldHideIvaFooter,
  shouldShowOtrosFooter,
  hasOtrosImpuestosSelection,
} from "../comprobanteTax/index.js";
import {
  formatMoney,
  formatNumericForDisplay,
  normalizeNumericValue,
  escapeHtml,
} from "../utils/index.js";
import { updateProcessTotals, updateRowTotals } from "../table/index.js";
import { isSoloEncabezado } from "../singleLine/index.js";

function footerMoneyCell(n) {
  return n == null || Number.isNaN(n) ? "—" : formatMoney(n);
}

function renderIvaFooterRows(totals, compIdx, groupRows) {
  if (shouldHideIvaFooter(groupRows)) return "";
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

function formatOtrosFooterValue(groupRows, totals) {
  const otrosVal = totals.otros || 0;
  if (otrosVal > 0) return formatNumericForDisplay(otrosVal, "otros_impuestos_monto");
  if (hasOtrosImpuestosSelection(groupRows)) return "0";
  return "";
}

function footerStructureSignature(groupRows, totals, breakdown) {
  return JSON.stringify({
    hideIva: shouldHideIvaFooter(groupRows),
    showOtros: shouldShowOtrosFooter(groupRows, totals),
    ivaKeys: (breakdown || []).map((b) => `${b.rateKey}:${b.editable}`).join(","),
  });
}

function syncFooterTaxRows(card, compKey, totals, groupRows) {
  const tbody = card.querySelector(".comprobanteTotalsTable tbody");
  const grandTotal = tbody?.querySelector("tr.totalsGrand");
  if (!tbody || !grandTotal) return;

  const baseRow = tbody.querySelector("tr:first-child");
  let node = baseRow?.nextElementSibling;
  while (node && node !== grandTotal) {
    const next = node.nextElementSibling;
    node.remove();
    node = next;
  }

  const middleHtml =
    renderIvaFooterRows(totals, compKey, groupRows) + renderOtrosFooterRow(totals, compKey, groupRows);
  if (middleHtml) grandTotal.insertAdjacentHTML("beforebegin", middleHtml);
}

function isFooterTaxInput(el) {
  return (
    el instanceof HTMLInputElement &&
    (el.hasAttribute("data-comp-footer-iva") || el.hasAttribute("data-comp-footer-otros"))
  );
}

function renderOtrosFooterRow(totals, compIdx, groupRows) {
  if (!shouldShowOtrosFooter(groupRows, totals)) return "";
  const otrosShown = formatOtrosFooterValue(groupRows, totals);
  return `<tr data-comp-footer-otros-row="${escapeHtml(compIdx)}">
            <td>Otros impuestos</td>
            <td>
              <input type="text" inputmode="decimal" class="comprobanteFooterInput"
                data-comp-footer-otros="${escapeHtml(compIdx)}" value="${escapeHtml(otrosShown)}" />
            </td>
          </tr>`;
}

export function renderFooterHtml(totals, compIdx, groupRows) {
  if (isSoloEncabezado(groupRows?.[0])) return "";
  return `<div class="comprobanteFooter">
      <table class="comprobanteTotalsTable">
        <tbody>
          <tr>
            <td>Base imponible</td>
            <td class="comprobanteFooterReadonly" data-comp-footer-base="${escapeHtml(compIdx)}">${footerMoneyCell(totals.baseOdoo)}</td>
          </tr>
          ${renderIvaFooterRows(totals, compIdx, groupRows)}
          ${renderOtrosFooterRow(totals, compIdx, groupRows)}
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
    const rateKeys = Object.keys(montos).filter((k) => k !== "_total");
    if (normalized) {
      if (rateKeys.length === 1) {
        montos[rateKeys[0]] = normalized;
      } else if (!rateKeys.length) {
        montos["21"] = normalized;
      }
    }
  } else if (normalized) {
    montos[rateKey] = normalized;
  } else {
    delete montos[rateKey];
  }
  serializeFacIvaMontos(groupRows, montos);
  const first = groupRows[0];
  if (first) first.__fac_iva_monto_manual = true;
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
  if (!wrap) return;
  wrap._footerHandlerCtx = { state, refs, handlers };
  if (wrap._footerEventsBound) return;
  wrap._footerEventsBound = true;

  wrap.addEventListener("input", (e) => {
    const ctx = wrap._footerHandlerCtx;
    if (!ctx || !isFooterTaxInput(e.target)) return;
    const t = e.target;
    if (t.hasAttribute("data-comp-footer-iva")) {
      const comp = t.getAttribute("data-comp-footer-iva");
      const rateKey = t.getAttribute("data-iva-rate-key") || "_total";
      setFooterIvaAmount(ctx.state, comp, rateKey, t.value);
      updateComprobanteFooters(ctx.state, ctx.refs);
      ctx.handlers.onAutoSave?.();
      return;
    }
    if (t.hasAttribute("data-comp-footer-otros")) {
      const comp = t.getAttribute("data-comp-footer-otros");
      setComprobanteFooterOtros(ctx.state, comp, t.value);
      updateComprobanteFooters(ctx.state, ctx.refs);
      ctx.handlers.onAutoSave?.();
    }
  });

  wrap.addEventListener(
    "blur",
    (e) => {
      const ctx = wrap._footerHandlerCtx;
      if (!ctx || !isFooterTaxInput(e.target)) return;
      const t = e.target;
      if (t.hasAttribute("data-comp-footer-iva")) {
        const comp = t.getAttribute("data-comp-footer-iva");
        const rateKey = t.getAttribute("data-iva-rate-key") || "_total";
        const normalized = normalizeNumericValue(t.value, "iva_monto");
        setFooterIvaAmount(ctx.state, comp, rateKey, normalized);
        t.value = normalized ? formatNumericForDisplay(normalized, "iva_monto") : "";
        updateComprobanteFooters(ctx.state, ctx.refs);
        refreshComprobanteRowTotals(ctx.state, ctx.refs, comp);
        ctx.handlers.onAutoSave?.();
        return;
      }
      if (t.hasAttribute("data-comp-footer-otros")) {
        const comp = t.getAttribute("data-comp-footer-otros");
        setComprobanteFooterOtros(ctx.state, comp, t.value);
        const normalized = normalizeNumericValue(t.value, "otros_impuestos_monto");
        t.value = normalized ? formatNumericForDisplay(normalized, "otros_impuestos_monto") : "";
        updateComprobanteFooters(ctx.state, ctx.refs);
        refreshComprobanteRowTotals(ctx.state, ctx.refs, comp);
        ctx.handlers.onAutoSave?.();
      }
    },
    true
  );
}

/** Actualiza pies de comprobante sin re-renderizar tablas (edición en curso). */
export function updateComprobanteFooters(state, refs) {
  const wrap = refs?.tableWrap;
  if (!wrap || !state.rows?.length) return;
  if (!state.comprobanteFooterStructure) state.comprobanteFooterStructure = {};

  for (const g of listComprobanteGroups(state.rows)) {
    const card = wrap.querySelector(`.comprobanteCard[data-comp="${CSS.escape(String(g.compIdx))}"]`);
    if (!card) continue;
    const groupRows = g.rowIndices.map((i) => state.rows[i]);
    if (isSoloEncabezado(groupRows[0])) continue;
    const compKey = String(g.compIdx);
    const mode = state.comprobanteTaxModes?.[compKey] || classifyComprobanteTaxMode(groupRows);
    state.comprobanteTaxModes[compKey] = mode;
    const totals = computeComprobanteTotals(groupRows, mode);
    const breakdown = totals.ivaBreakdown || computeIvaBreakdown(groupRows, totals);
    const structureSig = footerStructureSignature(groupRows, totals, breakdown);
    const prevStructure = state.comprobanteFooterStructure[compKey];

    if (prevStructure !== undefined && prevStructure !== structureSig) {
      syncFooterTaxRows(card, compKey, totals, groupRows);
    }
    state.comprobanteFooterStructure[compKey] = structureSig;

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
      otrosInp.value = formatOtrosFooterValue(groupRows, totals);
    }

    const totalCell = card.querySelector(`[data-comp-footer-total="${CSS.escape(compKey)}"]`);
    if (totalCell) totalCell.textContent = footerMoneyCell(totals.totalOdoo);

    card.querySelector(".comprobanteModeHint")?.remove();
    card.querySelector(".comprobanteWarnings")?.remove();
  }
  updateProcessTotals(state, refs);
}
