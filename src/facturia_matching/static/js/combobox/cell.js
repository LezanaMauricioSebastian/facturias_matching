import { escapeAttr, findOptionLabel, isPadronOptionKey, optionValue } from "../utils/index.js";

export function renderComboboxCellHtml({ rIdx, key, optKey, cellVal, tdStyle, loading, state, suggested }) {
  const opts = state.options?.[optKey] || [];
  // Solo mostrar label si el id existe en el catálogo activo (no huérfanos de otro Odoo).
  const known =
    !cellVal ||
    optKey === "productos" ||
    opts.some((o) => optionValue(o) === String(cellVal));
  const safeVal = known ? cellVal : "";
  const display =
    loading && !opts.length
      ? "Cargando…"
      : safeVal
        ? findOptionLabel(opts, safeVal) || (optKey === "productos" ? safeVal : "")
        : "";
  const dis = loading ? " disabled" : "";
  const cls = (loading ? " combobox-loading" : "") + (suggested ? " combobox-suggested" : "");
  const placeholder = loading ? "" : "Buscar…";
  const title = suggested
    ? ' title="Producto sugerido (historial del proveedor o fuzzy con OCs). Revisá antes de importar."'
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
