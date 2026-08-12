import {
  listComprobanteGroups,
  classifyComprobanteTaxMode,
  computeComprobanteTotals,
  comprobanteGroupByIdx,
  computeIvaBreakdown,
  computeOtrosBreakdown,
  parseFacIvaMontos,
  serializeFacIvaMontos,
  shouldHideIvaFooter,
  shouldShowOtrosFooter,
  setOtrosFooterAmount,
  ensureOtrosLabelOnFirstRow,
  maxOtrosSlotNOnRow,
  stripPieMirrorLabelsFromFirstRow,
  missingFacOtrosAssignments,
} from "../comprobanteTax/index.js";
import {
  formatMoney,
  formatNumericForDisplay,
  normalizeNumericValue,
  escapeHtml,
} from "../utils/index.js";
import { updateProcessTotals, updateRowTotals } from "../table/index.js";
import { ensureOtroImpuestoColumns } from "../rows/index.js";

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

function renderOtrosFooterRows(totals, compIdx, groupRows) {
  if (!shouldShowOtrosFooter(groupRows, totals)) return "";
  const breakdown = computeOtrosBreakdown(groupRows);
  const missing = missingFacOtrosAssignments(groupRows);
  let html = "";
  if (!breakdown.length) {
    html = `<tr data-comp-footer-otros-row="${escapeHtml(compIdx)}">
            <td>Otros impuestos</td>
            <td>
              <input type="text" inputmode="decimal" class="comprobanteFooterInput"
                data-comp-footer-otros="${escapeHtml(compIdx)}"
                data-otros-slot="1"
                value="" />
            </td>
          </tr>`;
  } else {
    html = breakdown
      .map((row) => {
        const shown = row.amount > 0 ? formatNumericForDisplay(row.amount, "otros_impuestos_monto") : "";
        return `<tr data-comp-footer-otros-row="${escapeHtml(compIdx)}" data-otros-slot="${escapeHtml(row.slotKey)}">
            <td>${escapeHtml(row.label)}</td>
            <td>
              <input type="text" inputmode="decimal" class="comprobanteFooterInput"
                data-comp-footer-otros="${escapeHtml(compIdx)}"
                data-otros-slot="${escapeHtml(row.slotKey)}"
                value="${escapeHtml(shown)}" />
            </td>
          </tr>`;
      })
      .join("");
  }
  if (missing.length) {
    html += `<tr class="comprobanteOtrosWarn" data-comp-footer-otros-warn="${escapeHtml(compIdx)}">
      <td colspan="2">No asignaste en las líneas todos los impuestos de la factura: ${escapeHtml(missing.join(", "))}</td>
    </tr>`;
  }
  return html;
}

function footerStructureSignature(groupRows, totals, breakdown) {
  const otros = computeOtrosBreakdown(groupRows);
  const missing = missingFacOtrosAssignments(groupRows);
  return JSON.stringify({
    hideIva: shouldHideIvaFooter(groupRows),
    showOtros: shouldShowOtrosFooter(groupRows, totals),
    ivaKeys: (breakdown || []).map((b) => `${b.rateKey}:${b.editable}`).join(","),
    otrosKeys: otros.map((b) => `${b.slotKey}:${b.label}`).join(","),
    missingOtros: missing.join("|"),
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
    renderIvaFooterRows(totals, compKey, groupRows) + renderOtrosFooterRows(totals, compKey, groupRows);
  if (middleHtml) grandTotal.insertAdjacentHTML("beforebegin", middleHtml);
}

function isFooterTaxInput(el) {
  return (
    el instanceof HTMLInputElement &&
    (el.hasAttribute("data-comp-footer-iva") || el.hasAttribute("data-comp-footer-otros"))
  );
}

export function renderFooterHtml(totals, compIdx, groupRows) {
  // Montos siempre en el pie (también con Solo encabezado: colapsa líneas, no el pie).
  return `<div class="comprobanteFooter">
      <table class="comprobanteTotalsTable">
        <tbody>
          <tr>
            <td>Base imponible</td>
            <td class="comprobanteFooterReadonly" data-comp-footer-base="${escapeHtml(compIdx)}">${footerMoneyCell(totals.baseOdoo)}</td>
          </tr>
          ${renderIvaFooterRows(totals, compIdx, groupRows)}
          ${renderOtrosFooterRows(totals, compIdx, groupRows)}
          <tr class="totalsGrand">
            <td>Total</td>
            <td class="comprobanteFooterReadonly" data-comp-footer-total="${escapeHtml(compIdx)}">${footerMoneyCell(totals.totalOdoo)}</td>
          </tr>
        </tbody>
      </table>
    </div>`;
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

function setComprobanteFooterOtrosSlot(state, compIdx, slotN, rawValue) {
  const groupRows = groupRowsOfComp(state, compIdx);
  if (!groupRows.length) return;
  const normalized = normalizeNumericValue(rawValue, "otros_impuestos_monto");
  const n = parseInt(slotN, 10) || 1;
  if (state && n >= 2) ensureOtroImpuestoColumns(state, n);
  setOtrosFooterAmount(groupRows, n, normalized);
}

/**
 * Al elegir un impuesto en la columna, asegura una fila de pie con ese nombre.
 * @returns {boolean} true si hay que re-renderizar pie (nuevo slot / label).
 */
export function syncOtrosFooterFromRowSelection(state, rowIdx) {
  const row = state.rows?.[rowIdx];
  if (!row) return false;
  const g = comprobanteGroupByIdx(state.rows, row.__comprobante_idx);
  if (!g) return false;
  const groupRows = g.rowIndices.map((i) => state.rows[i]);
  const beforeMissing = missingFacOtrosAssignments(groupRows).join("|");
  stripPieMirrorLabelsFromFirstRow(groupRows);
  // Multi-impuesto solo en la línea editada (col 2+ vía +).
  if (groupRows[0] === row) {
    const lab1 = String(row.otros_impuestos ?? "").trim();
    if (lab1) ensureOtrosLabelOnFirstRow(groupRows, lab1, { selectedRow: row });
    for (let n = 2; n <= 20; n++) {
      const lab = String(row[`otros_impuestos_${n}`] ?? "").trim();
      if (lab) ensureOtrosLabelOnFirstRow(groupRows, lab, { selectedRow: row });
    }
  }
  const maxOnRow = maxOtrosSlotNOnRow(row);
  if (maxOnRow >= 2) ensureOtroImpuestoColumns(state, maxOnRow);
  const afterMissing = missingFacOtrosAssignments(groupRows).join("|");
  return beforeMissing !== afterMissing;
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
      const slot = t.getAttribute("data-otros-slot") || "1";
      setComprobanteFooterOtrosSlot(ctx.state, comp, slot, t.value);
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
        const slot = t.getAttribute("data-otros-slot") || "1";
        const normalized = normalizeNumericValue(t.value, "otros_impuestos_monto");
        setComprobanteFooterOtrosSlot(ctx.state, comp, slot, normalized);
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
    const compKey = String(g.compIdx);
    const mode = state.comprobanteTaxModes?.[compKey] || classifyComprobanteTaxMode(groupRows);
    state.comprobanteTaxModes[compKey] = mode;
    const totals = computeComprobanteTotals(groupRows, mode);
    const breakdown = totals.ivaBreakdown || computeIvaBreakdown(groupRows, totals);
    const otrosBreakdown = computeOtrosBreakdown(groupRows);
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

    card.querySelectorAll(`[data-comp-footer-otros="${CSS.escape(compKey)}"]`).forEach((otrosInp) => {
      if (document.activeElement === otrosInp) return;
      const slot = otrosInp.getAttribute("data-otros-slot") || "1";
      const row = otrosBreakdown.find((b) => String(b.slotKey) === String(slot));
      const amt = row?.amount || 0;
      otrosInp.value = amt > 0 ? formatNumericForDisplay(amt, "otros_impuestos_monto") : "";
    });

    const totalCell = card.querySelector(`[data-comp-footer-total="${CSS.escape(compKey)}"]`);
    if (totalCell) totalCell.textContent = footerMoneyCell(totals.totalOdoo);

    card.querySelector(".comprobanteModeHint")?.remove();
    card.querySelector(".comprobanteWarnings")?.remove();
  }
  updateProcessTotals(state, refs);
}
