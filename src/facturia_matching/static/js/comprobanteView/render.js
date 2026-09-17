import { renderComprobanteTable, updateTotals } from "../table/index.js";
import {
  listComprobanteGroups,
  classifyComprobanteTaxMode,
  computeComprobanteTotals,
} from "../comprobanteTax/index.js";
import { formatMoney, findOptionLabel, escapeHtml } from "../utils/index.js";
import { captureTableUiState, restoreTableUiState } from "./uiState.js";
import { renderFooterHtml, attachComprobanteFooterHandlers, updateComprobanteFooters } from "./footer.js";
import { renderOcHeaderControls } from "../ocPicker/render.js";
import { renderFacturaChromeHtml, wireFacturaChromeFields } from "./facturaChrome.js";
import { persistViewMode, persistUnifiedOneLine } from "../core/state.js";
import {
  attachArchivoViewerHandlers,
  renderVerFacturaButtonHtml,
} from "./archivoViewer.js";
import { classifyProcesoLineMode } from "../singleLine/index.js";

function comprobanteTitle(state, groupRows, compIdx) {
  const first = groupRows[0] || {};
  const doc = String(first["l10n_latam_document_number"] ?? "").trim();
  const partner =
    findOptionLabel(state.options?.proveedores || [], first.partner_id) ||
    String(first["Nombre de Proveedor"] ?? "").trim();
  const label = doc || `Comprobante ${Number(compIdx) + 1}`;
  return partner ? `${label} · ${partner}` : label;
}

/** Checkbox visible solo en Lista, con ≥2 facturas y todas de 1 línea. */
export function canUseUnifiedOneLine(state, groups = null) {
  if (state.viewMode === "carrusel") return false;
  const gs = groups || listComprobanteGroups(state.rows);
  if (gs.length < 2) return false;
  return classifyProcesoLineMode(state.rows) === "encabezado";
}

function syncViewModeToggle(state, refs) {
  const mode = state.viewMode === "carrusel" ? "carrusel" : "lista";
  if (refs.btnViewLista) refs.btnViewLista.classList.toggle("active", mode === "lista");
  if (refs.btnViewCarrusel) refs.btnViewCarrusel.classList.toggle("active", mode === "carrusel");
}

function syncUnifiedOneLineToggle(state, refs, groups) {
  const wrap = refs.unifiedOneLineToggle;
  const chk = refs.chkUnifiedOneLine;
  const available = canUseUnifiedOneLine(state, groups);
  if (wrap) wrap.hidden = !available;
  if (!available) {
    if (chk) chk.checked = false;
    return false;
  }
  if (chk) chk.checked = !!state.unifiedOneLine;
  return !!state.unifiedOneLine;
}

function syncCarouselNav(state, refs, groupCount) {
  const nav = refs.carouselNav;
  if (!nav) return;
  const carrusel = state.viewMode === "carrusel" && groupCount > 0;
  nav.hidden = !carrusel;
  if (!carrusel) return;
  const idx = Math.max(0, Math.min(state.carouselIndex, groupCount - 1));
  state.carouselIndex = idx;
  if (refs.carouselNavLabel) {
    refs.carouselNavLabel.textContent = `${idx + 1} / ${groupCount}`;
  }
  const multi = groupCount > 1;
  if (refs.btnCarouselPrev) refs.btnCarouselPrev.disabled = !multi || idx <= 0;
  if (refs.btnCarouselNext) refs.btnCarouselNext.disabled = !multi || idx >= groupCount - 1;
}

function renderListaCards(state, groups) {
  const cards = [];
  for (const g of groups) {
    const groupRows = g.rowIndices.map((i) => state.rows[i]);
    const mode = classifyComprobanteTaxMode(groupRows);
    state.comprobanteTaxModes[String(g.compIdx)] = mode;
    const totals = computeComprobanteTotals(groupRows, mode);
    const ocControls = renderOcHeaderControls(state, g.compIdx);
    const verFactura = renderVerFacturaButtonHtml(groupRows, g.compIdx);
    cards.push(
      `<section class="comprobanteCard" data-comp="${g.compIdx}">
        <header class="comprobanteCardHeader">
          <div class="comprobanteCardHeaderMain">
            <h3 class="comprobanteCardTitle">${escapeHtml(comprobanteTitle(state, groupRows, g.compIdx))}</h3>
            <div class="comprobanteCardHeaderActions">
              ${verFactura}
              ${ocControls}
            </div>
          </div>
        </header>
        <div class="comprobanteTableMount" data-comp-table="${escapeHtml(g.compIdx)}"></div>
        ${renderFooterHtml(totals, g.compIdx, groupRows)}
      </section>`
    );
  }
  return `<div class="comprobantesStack">${cards.join("")}</div>`;
}

/**
 * Todas las facturas 1 línea → una sola tabla (1 thead + 1 scroller).
 * OC / Ver factura van en la columna Acciones de cada fila.
 */
function renderUnifiedOneLineCard(state, groups) {
  for (const g of groups) {
    const groupRows = g.rowIndices.map((i) => state.rows[i]);
    state.comprobanteTaxModes[String(g.compIdx)] = classifyComprobanteTaxMode(groupRows);
  }
  const n = groups.length;
  return `<div class="comprobantesStack comprobantesStack--unified">
    <section class="comprobanteCard comprobanteCard--unified" data-comp="unified">
      <header class="comprobanteCardHeader comprobanteCardHeader--unified">
        <h3 class="comprobanteCardTitle">${n} comprobantes · vista unificada</h3>
      </header>
      <div class="comprobanteTableMount comprobanteTableMount--unified" data-comp-table="unified"></div>
    </section>
  </div>`;
}

function renderCarruselCard(state, g) {
  const groupRows = g.rowIndices.map((i) => state.rows[i]);
  const mode = classifyComprobanteTaxMode(groupRows);
  state.comprobanteTaxModes[String(g.compIdx)] = mode;
  const totals = computeComprobanteTotals(groupRows, mode);
  const ocControls = renderOcHeaderControls(state, g.compIdx);
  const rIdx = g.rowIndices[0];
  const chrome = renderFacturaChromeHtml(state, groupRows, rIdx, ocControls);
  return `<div class="comprobantesStack comprobantesStack--carrusel">
    <section class="comprobanteCard comprobanteCard--factura" data-comp="${g.compIdx}">
      ${chrome}
      <div class="comprobanteTableMount" data-comp-table="${escapeHtml(g.compIdx)}"></div>
      ${renderFooterHtml(totals, g.compIdx, groupRows)}
    </section>
  </div>`;
}

export function renderComprobantes(state, refs, handlers) {
  const wrap = refs.tableWrap;
  if (!wrap) return;
  if (!state.columns.length) {
    wrap.innerHTML = "";
    state.rowTotals = [];
    state.domRefs = { totalCells: [], ivaInputs: [], subtotalCells: [] };
    if (refs.totalGeneralEl) refs.totalGeneralEl.textContent = formatMoney(0);
    syncViewModeToggle(state, refs);
    syncUnifiedOneLineToggle(state, refs, []);
    syncCarouselNav(state, refs, 0);
    return;
  }

  const groups = listComprobanteGroups(state.rows);
  state.comprobanteTaxModes = {};
  state.comprobanteFooterStructure = {};

  const mode = state.viewMode === "carrusel" ? "carrusel" : "lista";
  if (state.carouselIndex >= groups.length) {
    state.carouselIndex = Math.max(0, groups.length - 1);
  }

  syncViewModeToggle(state, refs);
  const unifiedOn = syncUnifiedOneLineToggle(state, refs, groups);
  syncCarouselNav(state, refs, groups.length);

  let activeGroups = groups;
  let html;
  let unified = false;
  if (mode === "carrusel" && groups.length) {
    const g = groups[state.carouselIndex] || groups[0];
    activeGroups = [g];
    html = renderCarruselCard(state, g);
  } else if (unifiedOn) {
    unified = true;
    html = renderUnifiedOneLineCard(state, groups);
  } else {
    html = renderListaCards(state, groups);
  }

  const uiState = captureTableUiState(refs);
  wrap.innerHTML = html;

  if (unified) {
    const mount = wrap.querySelector(".comprobanteTableMount--unified");
    if (mount) {
      const allIndices = [];
      for (const g of groups) allIndices.push(...g.rowIndices);
      const taxMode = state.comprobanteTaxModes[String(groups[0]?.compIdx)] || "header";
      renderComprobanteTable(state, allIndices, mount, refs, handlers, {
        taxMode,
        forceOneLine: true,
        unifiedOneLine: true,
      });
    }
  } else {
    wrap.querySelectorAll(".comprobanteTableMount").forEach((mount) => {
      const compKey = mount.getAttribute("data-comp-table");
      const g = activeGroups.find((x) => String(x.compIdx) === String(compKey));
      if (!g) return;
      const taxMode = state.comprobanteTaxModes[String(g.compIdx)];
      renderComprobanteTable(state, g.rowIndices, mount, refs, handlers, {
        taxMode,
        hideChromeKeys: mode === "carrusel",
      });
    });
  }

  if (mode === "carrusel" && activeGroups.length) {
    const g = activeGroups[0];
    const card = wrap.querySelector(`.comprobanteCard[data-comp="${CSS.escape(String(g.compIdx))}"]`);
    wireFacturaChromeFields(card, state, refs, handlers, g.rowIndices[0]);
  }

  attachComprobanteFooterHandlers(wrap, state, refs, handlers);
  attachArchivoViewerHandlers(wrap, state);
  updateComprobanteFooters(state, refs);
  wrap.querySelectorAll(".comprobanteModeHint, .comprobanteWarnings").forEach((el) => el.remove());
  restoreTableUiState(refs, uiState);
  updateTotals(state, refs);
}

export function setViewMode(state, refs, handlers, mode) {
  const next = persistViewMode(mode === "carrusel" ? "carrusel" : "lista");
  if (state.viewMode === next) {
    syncViewModeToggle(state, refs);
    syncUnifiedOneLineToggle(state, refs);
    return;
  }
  state.viewMode = next;
  handlers.onRerender?.();
}

export function setUnifiedOneLine(state, refs, handlers, on) {
  const next = persistUnifiedOneLine(!!on);
  if (state.unifiedOneLine === next) {
    syncUnifiedOneLineToggle(state, refs);
    return;
  }
  state.unifiedOneLine = next;
  handlers.onRerender?.();
}

export function shiftCarousel(state, refs, handlers, delta) {
  if (state.viewMode !== "carrusel") return;
  const groups = listComprobanteGroups(state.rows);
  if (groups.length <= 1) return;
  const next = Math.max(0, Math.min(groups.length - 1, state.carouselIndex + delta));
  if (next === state.carouselIndex) return;
  state.carouselIndex = next;
  handlers.onRerender?.();
}
