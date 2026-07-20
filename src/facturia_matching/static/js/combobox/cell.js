import { escapeAttr, findOptionLabel, isPadronOptionKey } from "../utils/index.js";

export function renderComboboxCellHtml({ rIdx, key, optKey, cellVal, tdStyle, loading, state, suggested }) {
  const opts = state.options?.[optKey] || [];
  const display =
    loading && !opts.length
      ? "Cargando…"
      : cellVal
        ? findOptionLabel(opts, cellVal) || cellVal
        : "";
  const dis = loading ? " disabled" : "";
  const cls = (loading ? " combobox-loading" : "") + (suggested ? " combobox-suggested" : "");
  const placeholder = loading ? "" : "Buscar…";
  const title = suggested
    ? ' title="Producto sugerido automáticamente (fuzzy con OCs del proveedor). Revisá antes de importar."'
    : "";
  return (
    `<td${tdStyle}>` +
    `<div class="combobox${cls}" data-r="${rIdx}" data-k="${key}" data-opt-key="${optKey}"${title}>` +
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
