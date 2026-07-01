import { renderComprobanteTable, updateTotals } from "../table/index.js";
import {
  listComprobanteGroups,
  classifyComprobanteTaxMode,
  computeComprobanteTotals,
} from "../comprobanteTax/index.js";
import { formatMoney, findOptionLabel, escapeHtml } from "../utils/index.js";
import { captureTableUiState, restoreTableUiState } from "./uiState.js";
import { renderFooterHtml, attachComprobanteFooterHandlers } from "./footer.js";

function comprobanteTitle(state, groupRows, compIdx) {
  const first = groupRows[0] || {};
  const doc = String(first["l10n_latam_document_number"] ?? "").trim();
  const partner =
    findOptionLabel(state.options?.proveedores || [], first.partner_id) ||
    String(first["Nombre de Proveedor"] ?? "").trim();
  const label = doc || `Comprobante ${Number(compIdx) + 1}`;
  return partner ? `${label} · ${partner}` : label;
}

export function renderComprobantes(state, refs, handlers) {
  const wrap = refs.tableWrap;
  if (!wrap) return;
  if (!state.columns.length) {
    wrap.innerHTML = "";
    state.rowTotals = [];
    state.domRefs = { totalCells: [], ivaInputs: [] };
    if (refs.totalGeneralEl) refs.totalGeneralEl.textContent = formatMoney(0);
    return;
  }

  const groups = listComprobanteGroups(state.rows);
  state.comprobanteTaxModes = {};
  const cards = [];

  for (const g of groups) {
    const groupRows = g.rowIndices.map((i) => state.rows[i]);
    const mode = classifyComprobanteTaxMode(groupRows);
    state.comprobanteTaxModes[String(g.compIdx)] = mode;
    const totals = computeComprobanteTotals(groupRows, mode);
    cards.push(
      `<section class="comprobanteCard" data-comp="${g.compIdx}">
        <header class="comprobanteCardHeader">
          <h3 class="comprobanteCardTitle">${escapeHtml(comprobanteTitle(state, groupRows, g.compIdx))}</h3>
        </header>
        <div class="comprobanteTableMount" data-comp-table="${escapeHtml(g.compIdx)}"></div>
        ${renderFooterHtml(totals, g.compIdx, groupRows)}
      </section>`
    );
  }

  const uiState = captureTableUiState(refs);

  wrap.innerHTML = `<div class="comprobantesStack">${cards.join("")}</div>`;

  wrap.querySelectorAll(".comprobanteTableMount").forEach((mount) => {
    const compKey = mount.getAttribute("data-comp-table");
    const g = groups.find((x) => String(x.compIdx) === String(compKey));
    if (!g) return;
    const mode = state.comprobanteTaxModes[String(g.compIdx)];
    renderComprobanteTable(state, g.rowIndices, mount, refs, handlers, { taxMode: mode });
  });

  attachComprobanteFooterHandlers(wrap, state, refs, handlers);
  wrap.querySelectorAll(".comprobanteModeHint, .comprobanteWarnings").forEach((el) => el.remove());
  restoreTableUiState(refs, uiState);
  updateTotals(state, refs);
}
