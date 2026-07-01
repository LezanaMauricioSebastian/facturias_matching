import { escapeAttr, findOptionLabel, isPadronOptionKey } from "../utils/index.js";

export function renderComboboxCellHtml({ rIdx, key, optKey, cellVal, tdStyle, loading, state }) {
  const opts = state.options?.[optKey] || [];
  const display =
    loading && !opts.length
      ? "Cargando…"
      : cellVal
        ? findOptionLabel(opts, cellVal) || cellVal
        : "";
  const dis = loading ? " disabled" : "";
  const cls = loading ? " combobox-loading" : "";
  const placeholder = loading ? "" : "Buscar…";
  return (
    `<td${tdStyle}>` +
    `<div class="combobox${cls}" data-r="${rIdx}" data-k="${key}" data-opt-key="${optKey}">` +
    `<input type="text" class="combobox-input" autocomplete="off" spellcheck="false"` +
    ` placeholder="${escapeAttr(placeholder)}" value="${escapeAttr(display)}"${dis} />` +
    `<div class="combobox-list" role="listbox" hidden></div>` +
    `</div></td>`
  );
}

export function isComboboxLoading(state, optKey) {
  const opts = state.options?.[optKey];
  return (
    (isPadronOptionKey(optKey) && state.padronLoading && (!opts || opts.length === 0)) ||
    (optKey === "productos" && state.productosLoading && (!opts || opts.length === 0))
  );
}
