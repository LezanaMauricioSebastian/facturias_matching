import {
  escapeHtml,
  findOptionLabel,
  isPadronOptionKey,
  normalizeDateValue,
  optionLabel,
  optionValue,
} from "../utils/index.js";
import { normalizeComprobanteNumber } from "../validation/index.js";
import { attachComboboxes, isComboboxLoading, renderComboboxCellHtml } from "../combobox/index.js";
import { handleSelectionChange, refreshComprobanteHints } from "../table/handlers.js";
import { DOC_NUM_KEY } from "../table/constants.js";
import { renderVerFacturaButtonHtml } from "./archivoViewer.js";

/** Letra del comprobante desde label Odoo (`FACTURAS A` → `A`). */
export function documentLetterFromLabel(label) {
  const s = String(label || "").trim().toUpperCase();
  if (!s) return "—";
  const m = s.match(/\b([A-Z])\s*$/) || s.match(/\b([A-Z])\b/);
  if (m) return m[1];
  const last = s.replace(/[^A-Z]/g, "").slice(-1);
  return last || "—";
}

/** Código AFIP aproximado por letra (A→01, B→06, C→11). */
export function documentAfipCodeFromLetter(letter) {
  const L = String(letter || "").toUpperCase();
  if (L === "A") return "01";
  if (L === "B") return "06";
  if (L === "C") return "11";
  if (L === "E") return "19";
  if (L === "M") return "51";
  return "—";
}

/** Parte PV / nro de `00001-00006363`. */
export function splitDocumentNumber(doc) {
  const s = String(doc || "").trim();
  const m = s.match(/^(\d+)\s*[-–]\s*(\d+)$/);
  if (m) return { pv: m[1], nro: m[2], raw: s };
  return { pv: "", nro: s, raw: s };
}

function escapeAttr(s) {
  return String(s ?? "").replaceAll('"', "&quot;");
}

function fieldLabel(state, key, fallback) {
  const col = (state.columns || []).find((c) => c.key === key);
  return col?.label || fallback;
}

function partnerDisplayName(state, row) {
  return (
    findOptionLabel(state.options?.proveedores || [], row.partner_id) ||
    String(row["Nombre de Proveedor"] ?? "").trim() ||
    ""
  );
}

function renderTextField(rIdx, key, value, { hint = false, cls = "" } = {}) {
  const v = escapeAttr(value);
  const extra = cls ? ` ${cls}` : "";
  if (hint && key === DOC_NUM_KEY) {
    return (
      `<div class="cellStack facturaFieldControl">` +
      `<input class="facturaPlainInput${extra}" data-r="${rIdx}" data-k="${key}" value="${v}" />` +
      `<div class="fieldHint" data-doc-hint-row="${rIdx}" aria-live="polite" hidden></div>` +
      `</div>`
    );
  }
  return `<input class="facturaPlainInput facturaFieldControl${extra}" data-r="${rIdx}" data-k="${key}" value="${v}" />`;
}

function renderDocTypeSelect(state, rIdx, row) {
  const key = "l10n_latam_document_type_id";
  const optKey = "document_types";
  const opts = state.options?.[optKey] || [];
  const cellVal = String(row[key] ?? "").trim();
  const loading =
    isPadronOptionKey(optKey) && state.padronLoading && (!opts || opts.length === 0);
  const dis = loading ? " disabled" : "";
  const cls = loading
    ? ' class="selectLoading facturaPlainInput facturaFieldControl"'
    : ' class="facturaPlainInput facturaFieldControl"';
  const parts = [`<select${cls}${dis} data-r="${rIdx}" data-k="${key}">`];
  if (loading) {
    parts.push(`<option value="" selected disabled>Cargando…</option>`);
  } else {
    parts.push(`<option value=""></option>`);
    const values = new Set();
    for (const o of opts) {
      const ov = optionValue(o);
      if (!ov || values.has(ov)) continue;
      values.add(ov);
      const sel = ov === cellVal ? " selected" : "";
      const lab = optionLabel(o).replaceAll('"', "&quot;");
      parts.push(`<option${sel} value="${ov.replaceAll('"', "&quot;")}">${lab}</option>`);
    }
  }
  parts.push("</select>");
  return parts.join("");
}

function renderPartnerCombobox(state, rIdx, row) {
  return renderCatalogCombobox(state, rIdx, row, "partner_id", "proveedores");
}

function renderCatalogCombobox(state, rIdx, row, key, optKey) {
  const cellVal = String(row[key] ?? "").trim();
  const loading = isComboboxLoading(state, optKey);
  const td = renderComboboxCellHtml({
    rIdx,
    key,
    optKey,
    cellVal,
    tdStyle: "",
    loading,
    state,
    suggested: false,
  });
  return td.replace(/^<td[^>]*>/, "").replace(/<\/td>$/, "");
}

function hasColumn(state, key) {
  return (state.columns || []).some((c) => c.key === key);
}

/**
 * Layout tipo factura AFIP AR (emisor | letra | FACTURA + nro).
 * `rIdx` = primera fila del comprobante.
 */
export function renderFacturaChromeHtml(state, groupRows, rIdx, ocControlsHtml) {
  const row = groupRows[0] || {};
  const docOpts = state.options?.document_types || [];
  const docTypeId = String(row.l10n_latam_document_type_id ?? "").trim();
  const docLabel =
    String(row.__doc_type_label || "").trim() || findOptionLabel(docOpts, docTypeId) || "";
  const letter = documentLetterFromLabel(docLabel);
  const afipCode = documentAfipCodeFromLetter(letter);
  const docNum = String(row[DOC_NUM_KEY] ?? "").trim();
  const { pv, nro } = splitDocumentNumber(docNum);
  const invDate = String(row.invoice_date ?? "").trim();
  const dueDate = String(row.invoice_date_due ?? "").trim();
  const cuit = String(row.CUIT ?? "").trim();
  const partnerName = partnerDisplayName(state, row);
  const showRubro = hasColumn(state, "x_studio_category");
  const showDiario = hasColumn(state, "journal_id");
  const showCuenta = hasColumn(state, "invoice_line_ids/account_id");
  const compIdx = row.__comprobante_idx ?? 0;
  const verFacturaBtn = renderVerFacturaButtonHtml(groupRows, compIdx);

  const accountingBand =
    showRubro || showDiario || showCuenta
      ? `<div class="facturaAccountingBand">
          ${
            showRubro
              ? `<div class="facturaAccountingCell">
            <span class="facturaLbl">${escapeHtml(fieldLabel(state, "x_studio_category", "Rubros"))}</span>
            ${renderCatalogCombobox(state, rIdx, row, "x_studio_category", "rubros")}
          </div>`
              : ""
          }
          ${
            showDiario
              ? `<div class="facturaAccountingCell">
            <span class="facturaLbl">${escapeHtml(fieldLabel(state, "journal_id", "Diario"))}</span>
            ${renderCatalogCombobox(state, rIdx, row, "journal_id", "journals")}
          </div>`
              : ""
          }
          ${
            showCuenta
              ? `<div class="facturaAccountingCell">
            <span class="facturaLbl">${escapeHtml(fieldLabel(state, "invoice_line_ids/account_id", "Cuenta"))}</span>
            ${renderCatalogCombobox(state, rIdx, row, "invoice_line_ids/account_id", "cuentas")}
          </div>`
              : ""
          }
        </div>`
      : "";

  return `
    <div class="comprobanteFactura" data-factura-chrome>
      <div class="facturaToolbar">
        ${verFacturaBtn}
        ${ocControlsHtml || ""}
      </div>
      <div class="facturaPaper">
        <header class="facturaAfipHeader">
          <div class="facturaEmisor">
            <div class="facturaEmisorName" data-factura-partner-name>${escapeHtml(partnerName || "Proveedor")}</div>
            <div class="facturaEmisorLine">
              <span class="facturaLbl">Razón social / Proveedor</span>
              ${renderPartnerCombobox(state, rIdx, row)}
            </div>
            <div class="facturaEmisorGrid">
              <div class="facturaEmisorCell">
                <span class="facturaLbl">CUIT</span>
                ${renderTextField(rIdx, "CUIT", cuit)}
              </div>
              <div class="facturaEmisorCell">
                <span class="facturaLbl">Tipo</span>
                ${renderDocTypeSelect(state, rIdx, row)}
              </div>
            </div>
            <div class="facturaEmisorMeta">IVA Responsable Inscripto</div>
          </div>
          <div class="facturaLetterCol">
            <div class="facturaLetterBox" aria-hidden="true">
              <span class="facturaLetter">${escapeHtml(letter)}</span>
              <span class="facturaLetterCode">COD. ${escapeHtml(afipCode)}</span>
            </div>
            <div class="facturaOriginal">ORIGINAL</div>
          </div>
          <div class="facturaRightMeta">
            <div class="facturaDocKind">FACTURA</div>
            <div class="facturaCompBlock">
              <div class="facturaCompLine">
                <span class="facturaLbl">Punto de Venta</span>
                <span class="facturaPvNro" data-factura-pv>${escapeHtml(pv || "—")}</span>
                <span class="facturaLbl facturaLblInline">Comp. Nro</span>
                <span class="facturaPvNro" data-factura-nro>${escapeHtml(nro || "—")}</span>
              </div>
              <div class="facturaCompEdit">
                <span class="facturaLbl">${escapeHtml(fieldLabel(state, DOC_NUM_KEY, "Número"))}</span>
                ${renderTextField(rIdx, DOC_NUM_KEY, docNum, { hint: true })}
              </div>
              <div class="facturaCompEdit">
                <span class="facturaLbl">Fecha de Emisión</span>
                ${renderTextField(rIdx, "invoice_date", invDate)}
              </div>
            </div>
          </div>
        </header>

        <div class="facturaPeriodBand">
          <div class="facturaPeriodItem">
            <span class="facturaLbl">Período facturado</span>
            <span class="facturaPeriodVal" data-factura-period>${escapeHtml(invDate || "—")}</span>
          </div>
          <div class="facturaPeriodItem">
            <span class="facturaLbl">Fecha de Vto. para el pago</span>
            ${renderTextField(rIdx, "invoice_date_due", dueDate, { cls: "facturaPeriodInput" })}
          </div>
        </div>

        <div class="facturaReceptor">
          <div class="facturaReceptorTitle">Datos del comprobante</div>
          <div class="facturaReceptorGrid">
            <div class="facturaReceptorCell facturaReceptorWide">
              <span class="facturaLbl">Proveedor</span>
              <strong class="facturaReceptorName" data-factura-partner-name>${escapeHtml(partnerName || "—")}</strong>
            </div>
            <div class="facturaReceptorCell">
              <span class="facturaLbl">CUIT</span>
              <strong data-factura-cuit>${escapeHtml(cuit || "—")}</strong>
            </div>
            <div class="facturaReceptorCell">
              <span class="facturaLbl">Condición frente al IVA</span>
              <strong>Responsable Inscripto</strong>
            </div>
          </div>
        </div>

        ${accountingBand}

        <div class="facturaLinesLabel">Detalle</div>
      </div>
    </div>`;
}

function syncChromeDerived(root, state, rIdx) {
  const row = state.rows[rIdx] || {};
  const docOpts = state.options?.document_types || [];
  const docTypeId = String(row.l10n_latam_document_type_id ?? "").trim();
  const docLabel =
    String(row.__doc_type_label || "").trim() || findOptionLabel(docOpts, docTypeId) || "";
  const letter = documentLetterFromLabel(docLabel);
  const letterEl = root.querySelector(".facturaLetter");
  if (letterEl) letterEl.textContent = letter;
  const codeEl = root.querySelector(".facturaLetterCode");
  if (codeEl) codeEl.textContent = `COD. ${documentAfipCodeFromLetter(letter)}`;

  const docNum = String(row[DOC_NUM_KEY] ?? "").trim();
  const { pv, nro } = splitDocumentNumber(docNum);
  const pvEl = root.querySelector("[data-factura-pv]");
  const nroEl = root.querySelector("[data-factura-nro]");
  if (pvEl) pvEl.textContent = pv || "—";
  if (nroEl) nroEl.textContent = nro || "—";

  const invDate = String(row.invoice_date ?? "").trim();
  const periodEl = root.querySelector("[data-factura-period]");
  if (periodEl) periodEl.textContent = invDate || "—";

  const cuit = String(row.CUIT ?? "").trim();
  const cuitEl = root.querySelector("[data-factura-cuit]");
  if (cuitEl) cuitEl.textContent = cuit || "—";

  const name = partnerDisplayName(state, row) || "—";
  root.querySelectorAll("[data-factura-partner-name]").forEach((el) => {
    el.textContent = name;
  });
}

/** Wire inputs/selects/comboboxes del chrome (misma semántica que la tabla). */
export function wireFacturaChromeFields(root, state, refs, handlers, rIdx) {
  if (!root) return;
  const chrome = root.querySelector("[data-factura-chrome]") || root;
  const selectionCtx = { refs, handlers };

  chrome.querySelectorAll("input[data-r][data-k]").forEach((inp) => {
    inp.addEventListener("input", (e) => {
      const r = parseInt(e.target.getAttribute("data-r"), 10);
      const k = e.target.getAttribute("data-k");
      if (!Number.isFinite(r) || !k) return;
      state.rows[r][k] = e.target.value;
      if (k === DOC_NUM_KEY || k === "invoice_date" || k === "CUIT") {
        syncChromeDerived(chrome, state, r);
      }
      if (k === DOC_NUM_KEY) refreshComprobanteHints(chrome, state);
      handlers.onAutoSave?.();
    });
    inp.addEventListener("blur", (e) => {
      const r = parseInt(e.target.getAttribute("data-r"), 10);
      const k = e.target.getAttribute("data-k");
      if (!Number.isFinite(r) || !k) return;
      if (k === "invoice_date" || k === "invoice_date_due") {
        const normalized = normalizeDateValue(e.target.value);
        state.rows[r][k] = normalized;
        e.target.value = normalized;
        syncChromeDerived(chrome, state, r);
        handlers.onAutoSave?.();
        return;
      }
      if (k === DOC_NUM_KEY) {
        const normalized = normalizeComprobanteNumber(e.target.value);
        state.rows[r][k] = normalized;
        e.target.value = normalized;
        syncChromeDerived(chrome, state, r);
        refreshComprobanteHints(chrome, state);
        handlers.onAutoSave?.();
      }
    });
  });

  chrome.querySelectorAll("select[data-r][data-k]").forEach((sel) => {
    sel.addEventListener("change", (e) => {
      if (e.target.disabled) return;
      const r = parseInt(e.target.getAttribute("data-r"), 10);
      const k = e.target.getAttribute("data-k");
      if (!Number.isFinite(r) || !k) return;
      state.rows[r][k] = e.target.value;
      handleSelectionChange(state, r, k, selectionCtx);
      syncChromeDerived(chrome, state, r);
      handlers.onAutoSave?.();
    });
  });

  attachComboboxes(chrome, state, (r, k) => {
    handleSelectionChange(state, r, k, selectionCtx);
    syncChromeDerived(chrome, state, r);
    if (k !== "invoice_line_ids/product_id") {
      handlers.onAutoSave?.();
    }
  });

  refreshComprobanteHints(chrome, state);
  syncChromeDerived(chrome, state, rIdx);
}
