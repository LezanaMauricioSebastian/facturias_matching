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
      const notes = Array.isArray(ln.note_labels)
        ? ln.note_labels.map((n) => String(n || "").trim()).filter(Boolean)
        : [];
      const noteHtml = notes.length
        ? `<div class="ocLineNotes">${notes.map((n) => `<span class="ocLineNote">${escapeHtml(n)}</span>`).join(" ")}</div>`
        : "";
      return `<tr>
        <td><div class="ocLineName">${escapeHtml(ln.line_name || "")}</div>${noteHtml}</td>
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

function candidateDateKey(candidate) {
  const raw = String(candidate.date_order || "").trim();
  if (!raw) return "";
  // Odoo suele mandar "YYYY-MM-DD HH:MM:SS" o solo fecha.
  const m = raw.match(/^(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : "";
}

function candidateSearchText(candidate) {
  const parts = [
    candidate.order_name,
    candidate.partner_ref,
    candidate.deliver_to,
    candidate.receipt_status_label,
    formatDate(candidate.date_order),
    String(candidate.order_id ?? ""),
  ];
  for (const ln of candidate.lines || []) {
    parts.push(ln.line_name);
    if (Array.isArray(ln.note_labels)) parts.push(...ln.note_labels);
  }
  return parts
    .map((p) => String(p || "").trim().toLowerCase())
    .filter(Boolean)
    .join(" ");
}

/** Mes mínimo por defecto en el modal (ene-2026). */
export const OC_PICKER_DEFAULT_FROM_MONTH = "2026-01";

function monthToFromDate(monthValue) {
  const s = String(monthValue || "").trim();
  if (!/^\d{4}-\d{2}$/.test(s)) return "";
  return `${s}-01`;
}

function buildCandidateCard(candidate, compKey, selectedOrderId, expanded) {
  const isSelected = Number(candidate.order_id) === Number(selectedOrderId);
  const datePart = formatDate(candidate.date_order);
  const refHit =
    Number(candidate.ref_score || 0) >= 85
      ? `Ref match: ${Number(candidate.ref_score).toFixed(0)}%`
      : "";
  const meta = [
    candidate.partner_ref ? `Ref: ${escapeHtml(candidate.partner_ref)}` : "",
    datePart ? `Fecha: ${datePart}` : "",
    `Score: ${candidate.basket_score ?? 0}%`,
    `${candidate.lines_matched ?? 0}/${candidate.lines_total ?? 0} líneas`,
    refHit,
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
  const search = escapeHtml(candidateSearchText(candidate));
  const dateKey = escapeHtml(candidateDateKey(candidate));

  return `<article class="ocCandidate${isSelected ? " isSelected" : ""}" data-order-id="${candidate.order_id}" data-oc-search="${search}" data-oc-date="${dateKey}">
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

/** Filtra las tarjetas del modal por texto + fecha «desde» (client-side). */
export function filterOcCandidates(dialog) {
  if (!dialog) return;
  const list = dialog.querySelector(".ocCandidateList");
  if (!list) return;

  const searchInput = dialog.querySelector(".ocPickerSearchInput");
  const dateInput = dialog.querySelector(".ocPickerDateFrom");
  const q = String(searchInput?.value || "")
    .trim()
    .toLowerCase();
  const fromDate = monthToFromDate(dateInput?.value);

  const cards = list.querySelectorAll(".ocCandidate");
  let visible = 0;
  for (const card of cards) {
    const hay = card.getAttribute("data-oc-search") || "";
    const matchText = !q || hay.includes(q);
    const ocDate = card.getAttribute("data-oc-date") || "";
    // Sin fecha en la OC: no la ocultamos por el filtro de mes.
    const matchDate = !fromDate || !ocDate || ocDate >= fromDate;
    // La OC en uso siempre queda visible, aunque quede fuera del rango.
    const keepSelected = card.classList.contains("isSelected");
    const show = keepSelected || (matchText && matchDate);
    card.hidden = !show;
    if (show) visible += 1;
  }

  let empty = list.querySelector(".ocPickerFilterEmpty");
  if (!empty) {
    empty = document.createElement("p");
    empty.className = "ocPickerEmpty ocPickerFilterEmpty";
    list.appendChild(empty);
  }
  const hasFilter = !!q || !!fromDate;
  if (!hasFilter || visible > 0) {
    empty.hidden = true;
  } else {
    empty.hidden = false;
    empty.textContent = fromDate
      ? "Ninguna OC coincide con la búsqueda / fecha."
      : "Ninguna OC coincide con la búsqueda.";
  }
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
  if (state?.excelUser) return "";
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
    // Prioridad: OC guardada/seleccionada (sobrevive reload vía __selected_oc_*),
    // luego «Sin OC» si ya se buscó, si no el CTA de buscar.
    if (hasSelectedOc) {
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
    } else if (!searched) {
      ocButtons = `<button type="button" class="ocSearchBtn secondary" data-search-oc="${escapeHtml(key)}">
        Buscar OCs similares
      </button>`;
    } else {
      // Tras «Sin OC»: queda como selector OC para reabrir el modal, sin número de factura.
      ocButtons = `<button type="button" class="ocPickerBtn secondary" data-open-oc="${escapeHtml(key)}">
        OC: Sin OC ▾
      </button>
      <button type="button" class="ocResearchBtn" data-search-oc="${escapeHtml(key)}" title="Buscar de nuevo">↻</button>`;
    }
  }

  // Sin OCs del proveedor: no mostrar ni pastilla ni checkbox.
  if (!showOcPill) {
    return "";
  }

  const disabledAttr = hasSelectedOc ? "" : " disabled";
  const titleAttr = hasSelectedOc
    ? ' title="Al importar, actualiza el precio unitario en la orden de compra de Odoo"'
    : ' title="Seleccioná una OC para habilitar esta opción"';
  const checkHtml = `<label class="ocOverwritePrice${!hasSelectedOc ? " isDisabled" : ""}"${titleAttr}>
      <input type="checkbox" data-overwrite-oc-price="${escapeHtml(key)}"${overwrite ? " checked" : ""}${disabledAttr} />
      <span>Sobreescribir precio de la OC</span>
    </label>`;

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

  const fromDefault = monthToFromDate(OC_PICKER_DEFAULT_FROM_MONTH);
  const firstVisibleIdx = candidates.findIndex((c) => {
    const d = candidateDateKey(c);
    return !fromDefault || !d || d >= fromDefault;
  });
  const list = candidates.length
    ? candidates
        .map((c, i) => {
          const isSelected = Number(c.order_id) === Number(selectedOrderId);
          const expanded = isSelected || (!selectedOrderId && i === firstVisibleIdx);
          return buildCandidateCard(c, compKey, selectedOrderId, expanded);
        })
        .join("")
    : '<p class="ocPickerEmpty">No hay OCs del proveedor en Odoo (o no se pudo consultar). Probá «Buscar OCs similares» de nuevo.</p>';

  const search = candidates.length
    ? `<div class="ocPickerSearchRow">
        <div class="ocPickerSearchFields">
          <div class="ocPickerSearchField ocPickerSearchFieldGrow">
            <label class="ocPickerSearchLabel" for="ocPickerSearchInput">Buscar OC</label>
            <input type="search" id="ocPickerSearchInput" class="ocPickerSearchInput" placeholder="Nombre, ref. proveedor, producto…" autocomplete="off" />
          </div>
          <div class="ocPickerSearchField">
            <label class="ocPickerSearchLabel" for="ocPickerDateFrom">Desde</label>
            <input type="month" id="ocPickerDateFrom" class="ocPickerDateFrom" value="${OC_PICKER_DEFAULT_FROM_MONTH}" title="Mostrar OCs desde este mes (inclusive). Vacíalo para ver todas." />
          </div>
        </div>
      </div>`
    : "";

  const deselect = `<div class="ocDeselectRow">
    <button type="button" class="ocDeselectBtn${!selectedOrderId ? " isActive" : ""}" data-comp="${escapeHtml(compKey)}" data-order="0">
      ${!selectedOrderId ? "✓ Sin OC (seleccionado)" : "Deseleccionar OC / Sin OC"}
    </button>
  </div>`;

  const title = dialog.querySelector(".ocPickerDialogTitle");
  if (title) title.textContent = `Seleccionar OC — ${label}`;

  const body = dialog.querySelector(".ocPickerDialogBody");
  if (body) {
    body.innerHTML = `${search}${deselect}<div class="ocCandidateList" data-comp="${escapeHtml(compKey)}">${list}</div>`;
  }

  dialog.dataset.compKey = compKey;
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }

  // Aplica el filtro por defecto (desde 01/2026) al abrir.
  filterOcCandidates(dialog);

  const searchInput = dialog.querySelector(".ocPickerSearchInput");
  if (searchInput) {
    // Foco al abrir: si ya saben el nombre/ref, escriben y filtran al toque.
    requestAnimationFrame(() => searchInput.focus());
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
