import { computeRowTotal, applyProveedorToCuit } from "./rows.js";
import {
  formatMoney,
  formatNumericForDisplay,
  isPadronOptionKey,
  isComboboxOptionKey,
  isFacturaCTypeId,
  normalizeIvaPctValue,
  normalizeNumericValue,
  normalizeDateValue,
  optionLabel,
  optionValue,
  findOptionLabel,
} from "./utils.js";
import { comprobanteDigitUiHint } from "./validation.js";
import { comprobanteHasMultipleLines, isFirstRowOfComprobante } from "./singleLine.js";
import {
  attachComboboxes,
  isComboboxLoading,
  renderComboboxCellHtml,
} from "./combobox.js";

const DOC_NUM_KEY = "l10n_latam_document_number";

function handleSelectionChange(state, r, k, ctx) {
  const { tableWrap, totalGeneralEl, handlers } = ctx;
  if (k === "partner_id") {
    applyProveedorToCuit(state, r);
    handlers.onRerender?.();
    return;
  }
  if (k === "l10n_latam_document_type_id") {
    const docTypeRaw = String(state.rows[r]?.[k] ?? "").trim();
    const ivaKey = "iva_pct";
    const docOpts = state.options?.document_types || [];
    const isFacturaC =
      isFacturaCTypeId(docTypeRaw, state) ||
      (() => {
        const lab = findOptionLabel(docOpts, docTypeRaw).toUpperCase();
        return lab === "FACTURAS C" || lab === "FACTURA C" || lab === "C";
      })();
    if (isFacturaC) {
      state.rows[r][ivaKey] = "IVA No Corresponde";
      state.rows[r].__iva_monto_manual = false;
      const ivaSel = tableWrap.querySelector(`select[data-r="${r}"][data-k="${ivaKey}"]`);
      if (ivaSel) ivaSel.value = "IVA No Corresponde";
      updateRowTotals(state, totalGeneralEl, r);
      if (!ivaSel && handlers.onRerender) handlers.onRerender();
      return;
    }
  }
  if (k === "iva_pct") {
    state.rows[r].__iva_monto_manual = false;
    updateRowTotals(state, totalGeneralEl, r);
  }
}

function isTotalAffectingKey(k) {
  return (
    k === "invoice_line_ids/quantity" ||
    k === "invoice_line_ids/price_unit" ||
    k === "iva_monto" ||
    k === "otros_impuestos_monto" ||
    /^otros_impuestos_\d+_monto$/.test(k)
  );
}

function buildDomRefs(state, tableWrap) {
  const n = state.rows.length;
  const totalCells = new Array(n);
  const ivaInputs = new Array(n);
  for (let i = 0; i < n; i++) {
    totalCells[i] = tableWrap.querySelector(`[data-total-r="${i}"]`);
    ivaInputs[i] = tableWrap.querySelector(`input[data-r="${i}"][data-k="iva_monto"]`);
  }
  state.domRefs = { totalCells, ivaInputs };
}

function sumRowTotals(rowTotals) {
  let total = 0;
  for (let i = 0; i < rowTotals.length; i++) total += rowTotals[i] || 0;
  return total;
}

function applyRowTotalToDom(state, rIdx) {
  const r = state.rows[rIdx];
  const rowTotal = state.rowTotals[rIdx];
  const { totalCells, ivaInputs } = state.domRefs || {};
  const cell = totalCells?.[rIdx];
  if (cell) cell.textContent = formatMoney(rowTotal);
  if (!r?.__iva_monto_manual) {
    const ivaInp = ivaInputs?.[rIdx];
    if (ivaInp) ivaInp.value = formatNumericForDisplay(r.iva_monto, "iva_monto");
  }
}

export function updateRowTotals(state, totalGeneralEl, rIdx) {
  if (rIdx < 0 || rIdx >= state.rows.length) return;
  state.rowTotals[rIdx] = computeRowTotal(state.rows[rIdx]);
  applyRowTotalToDom(state, rIdx);
  if (totalGeneralEl) {
    totalGeneralEl.textContent = formatMoney(sumRowTotals(state.rowTotals));
  }
}

function refreshComprobanteHints(tableWrap, state) {
  tableWrap.querySelectorAll("[data-doc-hint-row]").forEach((el) => {
    const r = parseInt(el.getAttribute("data-doc-hint-row"), 10);
    const hint = comprobanteDigitUiHint(state.rows[r]?.[DOC_NUM_KEY]);
    if (!hint) {
      el.textContent = "";
      el.hidden = true;
      el.className = "fieldHint";
      return;
    }
    el.textContent = hint.text;
    el.hidden = false;
    el.className = hint.kind === "bad" ? "fieldHint bad" : "fieldHint warn";
  });
}

export function updateTotals(state, tableWrap, totalGeneralEl) {
  const n = state.rows.length;
  state.rowTotals = new Array(n);
  let total = 0;
  const { totalCells, ivaInputs } = state.domRefs || {};
  for (let i = 0; i < n; i++) {
    const r = state.rows[i];
    const rowTotal = computeRowTotal(r);
    state.rowTotals[i] = rowTotal;
    total += rowTotal;
    const cell = totalCells?.[i] ?? tableWrap.querySelector(`[data-total-r="${i}"]`);
    if (cell) cell.textContent = formatMoney(rowTotal);
    if (!r.__iva_monto_manual) {
      const ivaInp = ivaInputs?.[i] ?? tableWrap.querySelector(`input[data-r="${i}"][data-k="iva_monto"]`);
      if (ivaInp) ivaInp.value = formatNumericForDisplay(r.iva_monto, "iva_monto");
    }
  }
  if (totalGeneralEl) totalGeneralEl.textContent = formatMoney(total);
}

export function renderTable(state, refs, handlers) {
  const { tableWrap, totalGeneralEl } = refs;
  if (!state.columns.length) {
    tableWrap.innerHTML = "";
    state.rowTotals = [];
    state.domRefs = { totalCells: [], ivaInputs: [] };
    return;
  }
  const cols = state.columns;
  const colMinWidth = {
    l10n_latam_document_number: 260,
    "Número de Documento": 260,
    CUIT: 220,
    Cuit: 220,
    "Tipo de Documento": 260,
    l10n_latam_document_type_id: 260,
    "Fecha factura": 260,
    "Fecha de vencimiento": 260,
    Rubros: 280,
    x_studio_category: 280,
    invoice_date: 260,
    invoice_date_due: 260,
    "invoice_line_ids/name": 420,
    "invoice_line_ids/product_id": 320,
    journal_id: 220,
    Proveedor: 220,
    "invoice_line_ids/account_id": 260,
    "invoice_line_ids/quantity": 140,
    "invoice_line_ids/price_unit": 200,
    iva_pct: 140,
    iva_monto: 160,
    otros_impuestos: 240,
    otros_impuestos_monto: 200,
    "invoice_line_ids/tax_ids": 220,
    __solo_encabezado: 130,
    __um_proveedor: 110,
    __um_empresa: 110,
    __oc_match_note: 220,
  };
  for (const c of cols) {
    if (c.key === "otros_impuestos" || /^otros_impuestos_\d+$/.test(c.key)) colMinWidth[c.key] = 240;
    if (c.key === "otros_impuestos_monto" || /^otros_impuestos_\d+_monto$/.test(c.key)) colMinWidth[c.key] = 200;
  }

  const html = [];
  html.push("<table><thead><tr>");
  for (const c of cols) {
    const mw = colMinWidth[c.key] || colMinWidth[c.label];
    const style = mw ? ` style="min-width:${mw}px"` : "";
    html.push(`<th${style}>${c.label}</th>`);
  }
  html.push(`<th style="min-width:120px">Acciones</th>`);
  html.push("</tr></thead><tbody>");

  for (let rIdx = 0; rIdx < state.rows.length; rIdx++) {
    const r = state.rows[rIdx];
    html.push("<tr>");
    for (const c of cols) {
      const key = c.key;
      const rawVal = r[key];
      const val = (rawVal ?? "").toString();
      const mw = colMinWidth[key] || colMinWidth[c.label];
      const tdStyle = mw ? ` style="min-width:${mw}px"` : "";
      if (c.type === "checkbox") {
        const showCb =
          isFirstRowOfComprobante(state.rows, rIdx) && comprobanteHasMultipleLines(state.rows, rIdx);
        if (showCb) {
          html.push(
            `<td class="soloEncabezadoCell"${tdStyle}><input type="checkbox" data-collapse-r="${rIdx}" title="Colapsar a una sola línea (elimina líneas extra del comprobante)" aria-label="Solo encabezado" /></td>`
          );
        } else {
          html.push(`<td${tdStyle}></td>`);
        }
      } else if (c.readonly) {
        html.push(`<td class="readonly"${tdStyle}>${val}</td>`);
      } else if (c.type === "selection") {
        const optKey = c.options_key;
        const opts = state.options && state.options[optKey] ? state.options[optKey] : [];
        const cellVal = key === "iva_pct" ? normalizeIvaPctValue(rawVal) : val;
        if (key === "iva_pct" && cellVal !== val) r[key] = cellVal;
        const loading = isComboboxLoading(state, optKey);
        if (isComboboxOptionKey(optKey)) {
          html.push(
            renderComboboxCellHtml({ rIdx, key, optKey, cellVal, tdStyle, loading, state })
          );
        } else {
          const selectLoading =
            (isPadronOptionKey(optKey) && state.padronLoading && (!opts || opts.length === 0)) ||
            (optKey === "productos" && state.productosLoading && (!opts || opts.length === 0));
          const dis = selectLoading ? " disabled" : "";
          const cls = selectLoading ? ' class="selectLoading"' : "";
          html.push(`<td${tdStyle}><select${cls}${dis} data-r="${rIdx}" data-k="${key}">`);
          if (selectLoading) {
            html.push(`<option value="" selected disabled>Cargando…</option>`);
          } else {
            html.push(`<option value=""></option>`);
            const values = new Set();
            for (const o of opts) {
              const ov = optionValue(o);
              if (!ov || values.has(ov)) continue;
              values.add(ov);
              const sel = ov === cellVal ? " selected" : "";
              const lab = optionLabel(o).replaceAll('"', "&quot;");
              html.push(`<option${sel} value="${ov.replaceAll('"', "&quot;")}">${lab}</option>`);
            }
            if (cellVal && !values.has(cellVal)) {
              const orphanLab = findOptionLabel(opts, cellVal).replaceAll('"', "&quot;");
              html.push(
                `<option selected value="${cellVal.replaceAll('"', "&quot;")}">${orphanLab}</option>`
              );
            }
          }
          html.push("</select></td>");
        }
      } else if (c.type === "numeric") {
        const shown = formatNumericForDisplay(rawVal, key);
        html.push(
          `<td${tdStyle}><input inputmode="decimal" data-r="${rIdx}" data-k="${key}" value="${shown.replaceAll('"', "&quot;")}" /></td>`
        );
      } else if (c.type === "computed") {
        const n = computeRowTotal(r);
        html.push(`<td class="readonly"${tdStyle} data-total-r="${rIdx}">${formatMoney(n)}</td>`);
      } else if (c.type === "text" && c.editable && key === DOC_NUM_KEY) {
        html.push(
          `<td class="cellWithHint"${tdStyle}><div class="cellStack"><input data-r="${rIdx}" data-k="${key}" value="${val.replaceAll('"', "&quot;")}" /><div class="fieldHint" data-doc-hint-row="${rIdx}" aria-live="polite" hidden></div></div></td>`
        );
      } else if (c.type === "text" && c.editable) {
        html.push(`<td${tdStyle}><input data-r="${rIdx}" data-k="${key}" value="${val.replaceAll('"', "&quot;")}" /></td>`);
      } else {
        html.push(`<td class="readonly"${tdStyle}>${val}</td>`);
      }
    }
    html.push(
      `<td><button type="button" class="rowDeleteBtn" data-del-r="${rIdx}">Borrar</button></td>`
    );
    html.push("</tr>");
  }
  html.push("</tbody></table>");
  tableWrap.innerHTML = html.join("");

  tableWrap.querySelectorAll("input[data-collapse-r]").forEach((cb) => {
    cb.addEventListener("change", (e) => {
      const t = e.target;
      if (!(t instanceof HTMLInputElement) || t.type !== "checkbox") return;
      if (!t.checked) return;
      t.checked = false;
      const r = parseInt(t.getAttribute("data-collapse-r"), 10);
      if (!Number.isFinite(r)) return;
      handlers.onCollapseComprobante?.(r);
    });
  });

  tableWrap.querySelectorAll("input[data-r][data-k]").forEach((inp) => {
    inp.addEventListener("input", (e) => {
      const r = parseInt(e.target.getAttribute("data-r"), 10);
      const k = e.target.getAttribute("data-k");
      state.rows[r][k] = e.target.value;
      if (k === "iva_monto") state.rows[r].__iva_monto_manual = true;
      if (isTotalAffectingKey(k)) {
        updateRowTotals(state, totalGeneralEl, r);
      }
      if (k === DOC_NUM_KEY) refreshComprobanteHints(tableWrap, state);
    });
    inp.addEventListener("blur", (e) => {
      const r = parseInt(e.target.getAttribute("data-r"), 10);
      const k = e.target.getAttribute("data-k");
      const col = cols.find((c) => c.key === k);
      if (k === "invoice_date" || k === "invoice_date_due") {
        const normalized = normalizeDateValue(e.target.value);
        state.rows[r][k] = normalized;
        e.target.value = normalized;
        return;
      }
      if (!col || col.type !== "numeric") return;
      const normalized = normalizeNumericValue(e.target.value, k);
      state.rows[r][k] = normalized;
      e.target.value = normalized;
      if (isTotalAffectingKey(k)) {
        updateRowTotals(state, totalGeneralEl, r);
      }
    });
  });

  tableWrap.querySelectorAll("select[data-r][data-k]").forEach((sel) => {
    sel.addEventListener("change", (e) => {
      if (e.target.disabled) return;
      const r = parseInt(e.target.getAttribute("data-r"), 10);
      const k = e.target.getAttribute("data-k");
      state.rows[r][k] = e.target.value;
      handleSelectionChange(state, r, k, { tableWrap, totalGeneralEl, handlers });
    });
  });

  const selectionCtx = { tableWrap, totalGeneralEl, handlers };
  attachComboboxes(tableWrap, state, (r, k) => {
    handleSelectionChange(state, r, k, selectionCtx);
  });

  tableWrap.querySelectorAll("button[data-del-r]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const r = parseInt(e.currentTarget.getAttribute("data-del-r"), 10);
      if (!Number.isFinite(r) || r < 0 || r >= state.rows.length) return;
      const ok = window.confirm(`¿Borrar la fila ${r + 1}?`);
      if (!ok) return;
      handlers.onDeleteRow?.(r);
    });
  });

  buildDomRefs(state, tableWrap);
  refreshComprobanteHints(tableWrap, state);
  updateTotals(state, tableWrap, totalGeneralEl);
}

