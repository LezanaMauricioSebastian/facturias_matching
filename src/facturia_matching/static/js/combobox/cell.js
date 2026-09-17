import { escapeAttr, findOptionLabel, isPadronOptionKey, optionValue } from "../utils/index.js";

export function renderComboboxCellHtml({ rIdx, key, optKey, cellVal, tdStyle, loading, state, suggested, row }) {
  const opts = state.options?.[optKey] || [];
  // Solo mostrar label si el id existe en el catálogo activo (no huérfanos de otro Odoo).
  const known =
    !cellVal ||
    optKey === "productos" ||
    optKey === "conceptos" ||
    opts.some((o) => optionValue(o) === String(cellVal));
  const safeVal = known ? cellVal : "";
  let display =
    loading && !opts.length
      ? "Cargando…"
      : safeVal
        ? findOptionLabel(opts, safeVal) ||
          (optKey === "productos" || optKey === "conceptos" ? safeVal : "")
        : "";
  // Modo Excel: Proveedor/Producto son matches de texto del Sheet, no ids Odoo.
  let excelTitle = "";
  if (state?.excelUser && row && !(loading && !opts.length)) {
    if (key === "partner_id") {
      const excelName = String(row["Nombre de Proveedor"] || row.__excel_proveedor || "").trim();
      if (excelName) {
        display = excelName;
        const sc = row.__excel_proveedor_score ?? row._match_score_proveedor;
        excelTitle =
          sc != null && Number(sc) > 0
            ? `Match Excel ${Math.round(Number(sc))}%`
            : "Match padrón Excel";
      }
    } else if (key === "invoice_line_ids/product_id") {
      const excelName = String(row["Nombre de producto"] || row.__excel_producto || "").trim();
      if (excelName) {
        display = excelName;
        const sc = row.__excel_producto_score;
        excelTitle =
          sc != null && Number(sc) > 0
            ? `Match Excel ${Math.round(Number(sc))}%`
            : "Match padrón Excel";
      }
    }
  }
  const dis = loading ? " disabled" : "";
  const cls = (loading ? " combobox-loading" : "") + (suggested ? " combobox-suggested" : "");
  const placeholder = loading ? "" : "Buscar…";
  const title = excelTitle
    ? ` title="${escapeAttr(excelTitle)}"`
    : suggested
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
    (optKey === "productos" && state.productosLoading && (!opts || opts.length === 0)) ||
    (optKey === "conceptos" && state.padronLoading && (!opts || opts.length === 0))
  );
}
