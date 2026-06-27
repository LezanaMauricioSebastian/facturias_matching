import { selectOc } from "./api.js";

function formatDate(raw) {
  const s = String(raw || "").trim();
  if (!s) return "";
  const d = s.slice(0, 10);
  return d.includes("-") ? d.split("-").reverse().join("/") : d;
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
      return `<tr>
        <td>${escapeHtml(ln.line_name || "")}</td>
        <td class="num">${formatQty(ln.product_qty)}</td>
        <td class="num">${formatQty(ln.qty_received)}</td>
        <td class="num">${formatQty(ln.qty_invoiced)}</td>
        <td>${matchHtml}</td>
      </tr>`;
    })
    .join("");
  return `<table class="ocLinesTable">
    <thead><tr>
      <th>Línea OC</th><th>Cant. pedida</th><th>Cant. recibida</th><th>Facturado</th><th>Match factura</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function formatQty(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v ?? "");
  return String(n);
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
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

  return `<article class="ocCandidate${isSelected ? " isSelected" : ""}" data-order-id="${candidate.order_id}">
    <button type="button" class="ocCandidateToggle" data-comp="${compKey}" data-order="${candidate.order_id}" aria-expanded="${expanded ? "true" : "false"}">
      <span class="ocCandidateTitle">${escapeHtml(candidate.order_name || "OC")}</span>
      <span class="ocCandidateMeta">${meta}</span>
    </button>
    <div class="ocCandidateBody" ${expanded ? "" : 'hidden'}>
      ${renderCandidateLines(candidate.lines)}
      <button type="button" class="ocSelectBtn secondary" data-comp="${compKey}" data-order="${candidate.order_id}"${isSelected ? " disabled" : ""}>
        ${isSelected ? "OC en uso" : "Usar esta OC"}
      </button>
    </div>
  </article>`;
}

export function renderOcPickerBar(state, refs, handlers, setStatusFn) {
  const bar = refs.ocPickerBar;
  if (!bar) return;

  const pm = state.purchaseMatching;
  if (!pm?.enabled || !pm?.show_purchase_columns) {
    bar.hidden = true;
    bar.innerHTML = "";
    return;
  }

  const candidatesMap = pm.oc_candidates_by_comprobante || {};
  const keys = Object.keys(candidatesMap)
    .filter((k) => (candidatesMap[k] || []).length > 0)
    .sort((a, b) => Number(a) - Number(b));
  if (!keys.length) {
    bar.hidden = true;
    bar.innerHTML = "";
    return;
  }

  const buttons = keys
    .map((compKey) => {
      const ocName = selectedOcName(pm, compKey) || "Sin OC";
      const label = comprobanteLabel(state.rows || [], compKey);
      return `<button type="button" class="ocPickerBtn secondary" data-open-oc="${compKey}">
        ${escapeHtml(label)}: OC ${escapeHtml(ocName)} ▾
      </button>`;
    })
    .join("");

  bar.hidden = false;
  bar.innerHTML = `<div class="ocPickerBarInner"><span class="ocPickerLabel">Órdenes de compra:</span>${buttons}</div>`;
}

export function openOcPicker(state, refs, handlers, setStatusFn, compKey) {
  const dialog = refs.ocPickerDialog;
  if (!dialog) return;

  const pm = state.purchaseMatching || {};
  const candidates = pm.oc_candidates_by_comprobante?.[compKey] || [];
  const selectedOrderId = pm.selected_oc_by_comprobante?.[compKey] ?? null;
  const label = comprobanteLabel(state.rows || [], compKey);

  const list = candidates.length
    ? candidates
        .map((c, i) => buildCandidateCard(c, compKey, selectedOrderId, i === 0))
        .join("")
    : '<p class="ocPickerEmpty">No hay OCs del proveedor en Odoo.</p>';

  const title = dialog.querySelector(".ocPickerDialogTitle");
  if (title) title.textContent = `Seleccionar OC — ${label}`;

  const body = dialog.querySelector(".ocPickerDialogBody");
  if (body) {
    body.innerHTML = `<div class="ocCandidateList" data-comp="${compKey}">${list}</div>`;
  }

  dialog.dataset.compKey = compKey;
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
}

export function wireOcPicker(state, refs, handlers, setStatusFn) {
  refs.ocPickerBar?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-open-oc]");
    if (!btn) return;
    openOcPicker(state, refs, handlers, setStatusFn, btn.getAttribute("data-open-oc"));
  });

  refs.ocPickerDialog?.addEventListener("click", (e) => {
    const dialog = refs.ocPickerDialog;
    if (!dialog) return;

    if (e.target === dialog) {
      dialog.close?.();
      return;
    }

    const closeBtn = e.target.closest("[data-close-oc]");
    if (closeBtn) {
      dialog.close?.();
      dialog.removeAttribute("open");
      return;
    }

    const toggle = e.target.closest(".ocCandidateToggle");
    if (toggle) {
      const card = toggle.closest(".ocCandidate");
      const body = card?.querySelector(".ocCandidateBody");
      if (body) {
        const open = body.hasAttribute("hidden");
        body.toggleAttribute("hidden", !open);
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
      }
      return;
    }

    const selectBtn = e.target.closest(".ocSelectBtn");
    if (selectBtn && !selectBtn.disabled) {
      const compKey = selectBtn.getAttribute("data-comp");
      const orderId = selectBtn.getAttribute("data-order");
      const compIdx = Number(compKey);
      dialog.close?.();
      dialog.removeAttribute("open");
      selectOc(state, refs, setStatusFn, handlers, compIdx, Number(orderId)).then(() => {
        renderOcPickerBar(state, refs, handlers, setStatusFn);
      });
    }
  });
}

export function renderOcPickerAfterTable(state, refs, handlers, setStatusFn) {
  renderOcPickerBar(state, refs, handlers, setStatusFn);
}
