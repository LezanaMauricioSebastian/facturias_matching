import { computeRowTotal, ADD_OTRO_IMPUESTO_KEY } from "../rows/index.js";
import { showIvaMontoColumn, classifyComprobanteTaxMode, syncFacIvaMontosFromLines, lineBase } from "../comprobanteTax/index.js";
import {
  formatMoney,
  formatNumericForDisplay,
  isPadronOptionKey,
  isComboboxOptionKey,
  normalizeIvaPctValue,
  normalizeNumericValue,
  normalizeDateValue,
  optionLabel,
  optionValue,
  findOptionLabel,
  toNumberLoose,
} from "../utils/index.js";
import { normalizeComprobanteNumber } from "../validation/index.js";
import {
  comprobanteHasMultipleLines,
  isFirstRowOfComprobante,
  groupBounds,
  isSoloEncabezado,
  syncSoloEncabezadoMontos,
} from "../singleLine/index.js";
import {
  attachComboboxes,
  isComboboxLoading,
  renderComboboxCellHtml,
} from "../combobox/index.js";
import { buildColMinWidth, DOC_NUM_KEY } from "./constants.js";
import { columnsForTaxMode, otroImpuestoNFromNameKey, otrosImpuestoKey } from "./columns.js";
import { mergeDomRefs, updateRowTotals } from "./totals.js";
import {
  handleSelectionChange,
  isTotalAffectingKey,
  maybeRerenderOnTaxModeChange,
  refreshComprobanteHints,
} from "./handlers.js";

function syncLineIvaMetadata(state, rowIdx) {
  const [s, e] = groupBounds(state.rows, rowIdx);
  const groupRows = state.rows.slice(s, e);
  const mode = classifyComprobanteTaxMode(groupRows);
  state.comprobanteTaxModes[String(state.rows[s]?.__comprobante_idx ?? s)] = mode;
  if (mode === "line") syncFacIvaMontosFromLines(groupRows, mode);
}

/** Monto sin impuestos: __fac_subtotal si hay; si no, cantidad × precio. */
function computeSubtotalCell(row) {
  const fac = toNumberLoose(row?.__fac_subtotal);
  if (fac > 0) return fac;
  return lineBase(row);
}

export function renderComprobanteTable(state, rowIndices, containerEl, refs, handlers, options = {}) {
  const taxMode = options.taxMode || "header";
  if (!state.columns.length || !containerEl) {
    return;
  }
  const firstRow = rowIndices.length ? state.rows[rowIndices[0]] : null;
  const soloEncabezado = isSoloEncabezado(firstRow);
  const cols = columnsForTaxMode(state.columns, taxMode, { soloEncabezado });
  const colMinWidth = buildColMinWidth(cols);
  const actionDisabled = !(state.rows && state.rows.length);

  const html = [];
  html.push("<table><thead><tr>");
  for (const c of cols) {
    const mw = colMinWidth[c.key] || colMinWidth[c.label];
    const style = mw ? ` style="min-width:${mw}px"` : "";
    if (c.type === "header_action" && c.key === ADD_OTRO_IMPUESTO_KEY) {
      const dis = actionDisabled ? " disabled" : "";
      html.push(
        `<th class="headerActionCell headerAddTaxCell"${style}>` +
          `<button type="button" class="headerActionBtn secondary" data-add-otro-impuesto${dis} title="Agregar impuesto" aria-label="Agregar impuesto">+</button>` +
          `</th>`
      );
      continue;
    }
    const taxN = otroImpuestoNFromNameKey(c.key);
    if (taxN >= 2 && c.type === "selection" && c.key === otrosImpuestoKey(taxN)) {
      const dis = actionDisabled ? " disabled" : "";
      html.push(
        `<th class="headerActionCell headerTaxCell"${style}>` +
          `<div class="headerTaxHead">` +
          `<span class="headerTaxLabel">${c.label}</span>` +
          `<button type="button" class="headerActionBtn secondary headerRemoveTaxBtn" data-remove-otro-impuesto="${taxN}"${dis} title="Quitar impuesto" aria-label="Quitar impuesto">×</button>` +
          `</div></th>`
      );
      continue;
    }
    html.push(`<th${style}>${c.label}</th>`);
  }
  html.push(`<th style="min-width:120px">Acciones</th>`);
  html.push("</tr></thead><tbody>");

  for (const rIdx of rowIndices) {
    const r = state.rows[rIdx];
    if (isSoloEncabezado(r)) syncSoloEncabezadoMontos(r, state);
    if (showIvaMontoColumn(taxMode, soloEncabezado) && !r.__iva_monto_manual) {
      computeRowTotal(r, taxMode);
    }
    html.push("<tr>");
    for (const c of cols) {
      const key = c.key;
      const rawVal = r[key];
      const val = (rawVal ?? "").toString();
      const mw = colMinWidth[key] || colMinWidth[c.label];
      const tdStyle = mw ? ` style="min-width:${mw}px"` : "";
      if (c.type === "header_action") {
        html.push(`<td class="headerActionBodyCell"${tdStyle}></td>`);
      } else if (c.type === "checkbox") {
        if (isFirstRowOfComprobante(state.rows, rIdx)) {
          const checked = isSoloEncabezado(r) ? " checked" : "";
          const multi = comprobanteHasMultipleLines(state.rows, rIdx);
          const title = multi
            ? "Solo encabezado: una línea (elimina líneas extra) y oculta el pie"
            : "Solo encabezado: muestra Subtotal y oculta el pie del comprobante";
          html.push(
            `<td class="soloEncabezadoCell"${tdStyle}><input type="checkbox" data-solo-encabezado-r="${rIdx}"${checked} title="${title}" aria-label="Solo encabezado" /></td>`
          );
        } else {
          html.push(`<td${tdStyle}></td>`);
        }
      } else if (c.type === "computed") {
        const n = key === "__subtotal" ? computeSubtotalCell(r) : computeRowTotal(r, taxMode);
        const dataAttr =
          key === "__subtotal" ? ` data-subtotal-r="${rIdx}"` : ` data-total-r="${rIdx}"`;
        html.push(`<td class="readonly"${tdStyle}${dataAttr}>${formatMoney(n)}</td>`);
      } else if (c.readonly) {
        html.push(`<td class="readonly"${tdStyle}>${val}</td>`);
      } else if (c.type === "selection") {
        const optKey = c.options_key;
        const opts = state.options && state.options[optKey] ? state.options[optKey] : [];
        const cellVal = key === "iva_pct" ? normalizeIvaPctValue(rawVal) : val;
        if (key === "iva_pct" && cellVal !== val) r[key] = cellVal;
        const loading = isComboboxLoading(state, optKey);
        if (isComboboxOptionKey(optKey)) {
          const suggested = optKey === "productos" && !!r.__product_suggested;
          html.push(
            renderComboboxCellHtml({ rIdx, key, optKey, cellVal, tdStyle, loading, state, suggested })
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
  containerEl.innerHTML = html.join("");

  containerEl.querySelectorAll("input[data-solo-encabezado-r]").forEach((cb) => {
    cb.addEventListener("change", (e) => {
      const t = e.target;
      if (!(t instanceof HTMLInputElement) || t.type !== "checkbox") return;
      const r = parseInt(t.getAttribute("data-solo-encabezado-r"), 10);
      if (!Number.isFinite(r)) return;
      handlers.onToggleSoloEncabezado?.(r, t.checked);
    });
  });

  containerEl.querySelectorAll("input[data-r][data-k]").forEach((inp) => {
    inp.addEventListener("input", (e) => {
      const r = parseInt(e.target.getAttribute("data-r"), 10);
      const k = e.target.getAttribute("data-k");
      state.rows[r][k] = e.target.value;
      if (k === "iva_monto") {
        state.rows[r].__iva_monto_manual = true;
        if (isSoloEncabezado(state.rows[r])) {
          state.rows[r].__fac_iva_monto = state.rows[r][k];
          state.rows[r].__fac_iva_monto_manual = true;
        }
      }
      if (isTotalAffectingKey(k)) {
        syncLineIvaMetadata(state, r);
        updateRowTotals(state, refs, r);
        if (!maybeRerenderOnTaxModeChange(state, r, handlers)) {
          handlers.onUpdateComprobanteFooters?.();
        }
      }
      if (k === DOC_NUM_KEY) refreshComprobanteHints(containerEl, state);
      handlers.onAutoSave?.();
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
      if (k === DOC_NUM_KEY) {
        const normalized = normalizeComprobanteNumber(e.target.value);
        state.rows[r][k] = normalized;
        e.target.value = normalized;
        refreshComprobanteHints(containerEl, state);
        handlers.onAutoSave?.();
        return;
      }
      if (!col || col.type !== "numeric") return;
      const normalized = normalizeNumericValue(e.target.value, k);
      state.rows[r][k] = normalized;
      e.target.value = normalized;
      if (k === "iva_monto") {
        state.rows[r].__iva_monto_manual = true;
        if (isSoloEncabezado(state.rows[r])) {
          state.rows[r].__fac_iva_monto = state.rows[r][k];
          state.rows[r].__fac_iva_monto_manual = true;
        }
      }
      if (isTotalAffectingKey(k)) {
        syncLineIvaMetadata(state, r);
        updateRowTotals(state, refs, r);
        if (!maybeRerenderOnTaxModeChange(state, r, handlers)) {
          handlers.onUpdateComprobanteFooters?.();
        }
      }
      handlers.onAutoSave?.();
    });
  });

  containerEl.querySelectorAll("select[data-r][data-k]").forEach((sel) => {
    sel.addEventListener("change", (e) => {
      if (e.target.disabled) return;
      const r = parseInt(e.target.getAttribute("data-r"), 10);
      const k = e.target.getAttribute("data-k");
      state.rows[r][k] = e.target.value;
      handleSelectionChange(state, r, k, { refs, handlers });
      handlers.onAutoSave?.();
    });
  });

  const selectionCtx = { refs, handlers };
  attachComboboxes(containerEl, state, (r, k) => {
    handleSelectionChange(state, r, k, selectionCtx);
    handlers.onAutoSave?.();
  });

  containerEl.querySelectorAll("button[data-remove-otro-impuesto]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      if (e.currentTarget.disabled) return;
      const n = parseInt(e.currentTarget.getAttribute("data-remove-otro-impuesto"), 10);
      if (!Number.isFinite(n) || n < 2) return;
      handlers.onRemoveOtroImpuesto?.(n);
    });
  });

  containerEl.querySelectorAll("button[data-del-r]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const r = parseInt(e.currentTarget.getAttribute("data-del-r"), 10);
      if (!Number.isFinite(r) || r < 0 || r >= state.rows.length) return;
      const ok = window.confirm(`¿Borrar la fila ${r + 1}?`);
      if (!ok) return;
      handlers.onDeleteRow?.(r);
    });
  });

  mergeDomRefs(state, containerEl);
  refreshComprobanteHints(containerEl, state);
}
