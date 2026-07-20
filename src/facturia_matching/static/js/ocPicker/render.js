import { escapeHtml } from "../utils/index.js";

function formatDate(raw) {
  const s = String(raw || "").trim();
  if (!s) return "";
  const d = s.slice(0, 10);
  return d.includes("-") ? d.split("-").reverse().join("/") : d;
}

function formatQty(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v ?? "");
  return String(n);
}

function formatMoney(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v ?? "");
  return n.toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function comprobanteLabel(rows, compIdx) {
  for (const row of rows) {
    if (Number(row.__comprobante_idx) !== Number(compIdx)) continue;
    const doc = String(row["l10n_latam_document_number"] || "").trim();
    if (doc) return doc;
    const prov = String(row["Nombre de Proveedor"] || "").trim();
    if (prov) return prov;
  }
  return `Comprobante ${compIdx}`;
}

function selectedOcName(pm, compKey) {
  const selected = pm?.selected_oc_by_comprobante || {};
  const orderId = selected[compKey];
  if (!orderId) return "";
  const candidates = pm?.oc_candidates_by_comprobante?.[compKey] || [];
  const hit = candidates.find((c) => Number(c.order_id) === Number(orderId));
  return hit?.order_name || "";
}

function groupOverwriteOcPrice(rows, compKey) {
  for (const row of rows || []) {
    if (Number(row.__comprobante_idx) !== Number(compKey)) continue;
    const raw = row.__overwrite_oc_price;
    if (raw === true || raw === 1) return true;
    const s = String(raw ?? "")
      .trim()
      .toLowerCase();
    if (s === "1" || s === "true" || s === "yes" || s === "si" || s === "sí" || s === "on") {
      return true;
    }
  }
  return false;
}

function receiptBadgeClass(status) {
  if (status === "full") return "ocReceiptBadge isFull";
  if (status === "partial") return "ocReceiptBadge isPartial";
  if (status === "pending") return "ocReceiptBadge isPending";
  return "ocReceiptBadge";
}

function renderCandidateLines(lines) {
  if (!lines?.length) {
    return '<p class="ocPickerEmpty">Sin líneas en esta OC.</p>';
  }
  const rows = lines
    .map((ln) => {
      const match = ln.invoice_match;
      const matchHtml = match
        ? `<span class="ocLineMatch">→ ${escapeHtml(match.invoice_desc)} (${Math.round(match.score)}%)</span>`
        : '<span class="ocLineMatch muted">Sin match factura</span>';
      const um = ln.product_uom_name ? escapeHtml(ln.product_uom_name) : "";
      return `<tr>
        <td>${escapeHtml(ln.line_name || "")}</td>
        <td class="num">${formatQty(ln.product_qty)}</td>
        <td class="num">${formatQty(ln.qty_received)}</td>
        <td class="num">${formatQty(ln.qty_invoiced)}</td>
        <td class="num">${formatMoney(ln.price_unit)}</td>
        <td>${um}</td>
        <td>${matchHtml}</td>
      </tr>`;
    })
    .join("");
  return `<table class="ocLinesTable">
    <thead><tr>
      <th>Línea OC</th><th>Cant. pedida</th><th>Cant. recibida</th><th>Facturado</th>
      <th>Precio unit.</th><th>UM</th><th>Match factura</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function buildCandidateCard(candidate, compKey, selectedOrderId, expanded) {
  const isSelected = Number(candidate.order_id) === Number(selectedOrderId);
  const datePart = formatDate(candidate.date_order);
  const meta = [
    candidate.partner_ref ? `Ref: ${escapeHtml(candidate.partner_ref)}` : "",
    datePart ? `Fecha: ${datePart}` : "",
    `Score: ${candidate.basket_score ?? 0}%`,
    `${candidate.lines_matched ?? 0}/${candidate.lines_total ?? 0} líneas`,
  ]
    .filter(Boolean)
    .join(" · ");

  const receiptLabel = candidate.receipt_status_label
    ? `<span class="${receiptBadgeClass(candidate.receipt_status)}">${escapeHtml(candidate.receipt_status_label)}</span>`
    : "";
  const deliverTo = candidate.deliver_to
    ? `<span class="ocDeliverTo">Entregar a: ${escapeHtml(candidate.deliver_to)}</span>`
    : "";
  const tags =
    receiptLabel || deliverTo ? `<span class="ocCandidateTags">${receiptLabel}${deliverTo}</span>` : "";

  return `<article class="ocCandidate${isSelected ? " isSelected" : ""}" data-order-id="${candidate.order_id}">
    <button type="button" class="ocCandidateToggle" data-comp="${escapeHtml(compKey)}" data-order="${candidate.order_id}" aria-expanded="${expanded ? "true" : "false"}">
      <span class="ocCandidateTitle">${escapeHtml(candidate.order_name || "OC")}</span>
      ${tags}
      <span class="ocCandidateMeta">${meta}</span>
    </button>
    <div class="ocCandidateBody" ${expanded ? "" : "hidden"}>
      ${renderCandidateLines(candidate.lines)}
      <button type="button" class="ocSelectBtn secondary" data-comp="${escapeHtml(compKey)}" data-order="${candidate.order_id}"${isSelected ? " disabled" : ""}>
        ${isSelected ? "OC en uso" : "Usar esta OC"}
      </button>
    </div>
  </article>`;
}

function rowsHaveOcLink(rows, compKey) {
  for (const row of rows || []) {
    if (Number(row.__comprobante_idx) !== Number(compKey)) continue;
    if (String(row.__oc_line_id || "").trim()) return true;
    if (String(row.__selected_oc_order_id || "").trim()) return true;
  }
  return false;
}

function comprobanteHasPartner(rows, compKey) {
  for (const row of rows || []) {
    if (Number(row.__comprobante_idx) !== Number(compKey)) continue;
    if (/^\d+$/.test(String(row.partner_id ?? "").trim())) return true;
  }
  return false;
}

/**
 * Controles OC + checkbox, arriba de cada factura.
 * Mismo botón secondary que la barra vieja («Buscar OCs similares» / «OC: … ▾»).
 */
export function renderOcHeaderControls(state, compKey) {
  const pm = state.purchaseMatching || {};
  const key = String(compKey);
  const hasOcsFlag = (pm.oc_provider_has_ocs_by_comprobante || {})[key];
  // Solo ocultar cuando sabemos con certeza que el proveedor NO tiene OCs.
  const knownNoOcs = hasOcsFlag === false;
  const searched = !!pm.oc_searched_by_comprobante?.[key];
  const selectedOrderId = pm.selected_oc_by_comprobante?.[key] ?? null;
  const hasSelectedOc = !!selectedOrderId || rowsHaveOcLink(state.rows || [], key);
  const overwrite = groupOverwriteOcPrice(state.rows || [], key);
  const hasPartner = comprobanteHasPartner(state.rows || [], key);

  // Pastilla OC: siempre que haya proveedor y no sepamos que NO tiene OCs.
  const showOcPill = hasSelectedOc || searched || (hasPartner && !knownNoOcs);

  let ocButtons = "";
  if (showOcPill) {
    if (!searched) {
      ocButtons = `<button type="button" class="ocSearchBtn secondary" data-search-oc="${escapeHtml(key)}">
        Buscar OCs similares
      </button>`;
    } else if (!hasSelectedOc) {
      // Tras «Sin OC»: queda como selector OC para reabrir el modal, sin número de factura.
      ocButtons = `<button type="button" class="ocPickerBtn secondary" data-open-oc="${escapeHtml(key)}">
        OC: Sin OC ▾
      </button>
      <button type="button" class="ocResearchBtn" data-search-oc="${escapeHtml(key)}" title="Buscar de nuevo">↻</button>`;
    } else {
      const ocName =
        selectedOcName(pm, key) ||
        String(
          (state.rows || []).find(
            (r) => Number(r.__comprobante_idx) === Number(key) && r.__selected_oc_name
          )?.__selected_oc_name || ""
        ) ||
        "OC vinculada";
      ocButtons = `<button type="button" class="ocPickerBtn secondary" data-open-oc="${escapeHtml(key)}">
        OC: ${escapeHtml(ocName)} ▾
      </button>
      <button type="button" class="ocResearchBtn" data-search-oc="${escapeHtml(key)}" title="Buscar de nuevo">↻</button>`;
    }
  }

  const disabledAttr = hasSelectedOc ? "" : " disabled";
  const titleAttr = hasSelectedOc
    ? ' title="Al importar, actualiza el precio unitario en la orden de compra de Odoo"'
    : ' title="Seleccioná una OC para habilitar esta opción"';
  const checkHtml = `<label class="ocOverwritePrice${!hasSelectedOc ? " isDisabled" : ""}"${titleAttr}>
      <input type="checkbox" data-overwrite-oc-price="${escapeHtml(key)}"${overwrite ? " checked" : ""}${disabledAttr} />
      <span>Sobreescribir precio de la OC</span>
    </label>`;

  if (!showOcPill) {
    return `<div class="comprobanteOcControls">${checkHtml}</div>`;
  }

  return `<div class="comprobanteOcControls">
    <div class="ocPickerRow comprobanteOcRow">
      ${ocButtons}
      ${checkHtml}
    </div>
  </div>`;
}

/** Barra global legacy: se deja vacía; los controles viven en cada factura. */
export function renderOcPickerBar(state, refs, _handlers, _setStatusFn) {
  const bar = refs.ocPickerBar;
  if (!bar) return;
  bar.hidden = true;
  bar.innerHTML = "";
}

export function openOcPicker(state, refs, handlers, setStatusFn, compKey) {
  const dialog = refs.ocPickerDialog;
  if (!dialog) return;

  const pm = state.purchaseMatching || {};
  const candidates = pm.oc_candidates_by_comprobante?.[compKey] || [];
  let selectedOrderId = pm.selected_oc_by_comprobante?.[compKey] ?? null;
  if (!selectedOrderId) {
    for (const row of state.rows || []) {
      if (Number(row.__comprobante_idx) !== Number(compKey)) continue;
      const raw = String(row.__selected_oc_order_id || row.__oc_order_id || "").trim();
      if (/^\d+$/.test(raw)) {
        selectedOrderId = Number(raw);
        break;
      }
    }
  }
  const label = comprobanteLabel(state.rows || [], compKey);

  const list = candidates.length
    ? candidates.map((c, i) => buildCandidateCard(c, compKey, selectedOrderId, i === 0)).join("")
    : '<p class="ocPickerEmpty">No hay OCs del proveedor en Odoo (o no se pudo consultar). Probá «Buscar OCs similares» de nuevo.</p>';

  const deselect = `<div class="ocDeselectRow">
    <button type="button" class="ocDeselectBtn${!selectedOrderId ? " isActive" : ""}" data-comp="${escapeHtml(compKey)}" data-order="0">
      ${!selectedOrderId ? "✓ Sin OC (seleccionado)" : "Deseleccionar OC / Sin OC"}
    </button>
  </div>`;

  const title = dialog.querySelector(".ocPickerDialogTitle");
  if (title) title.textContent = `Seleccionar OC — ${label}`;

  const body = dialog.querySelector(".ocPickerDialogBody");
  if (body) {
    body.innerHTML = `${deselect}<div class="ocCandidateList" data-comp="${escapeHtml(compKey)}">${list}</div>`;
  }

  dialog.dataset.compKey = compKey;
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
}

export function renderOcPickerAfterTable(state, refs, handlers, setStatusFn) {
  renderOcPickerBar(state, refs, handlers, setStatusFn);
}

export function setOverwriteOcPriceForComprobante(rows, compKey, enabled) {
  const value = enabled ? "1" : "";
  for (const row of rows || []) {
    if (Number(row.__comprobante_idx) !== Number(compKey)) continue;
    row.__overwrite_oc_price = value;
  }
}
