import { applyProveedorToCuit, propagateAccountDown } from "../rows/index.js";
import {
  allContentLinesExplicitZeroIva,
  classifyComprobanteTaxMode,
  clearFacIvaFooter,
} from "../comprobanteTax/index.js";
import {
  isFacturaCTypeId,
  findOptionLabel,
} from "../utils/index.js";
import { groupBounds } from "../singleLine/index.js";
import { updateRowTotals } from "./totals.js";
import { DOC_NUM_KEY } from "./constants.js";
import { comprobanteDigitUiHint } from "../validation/index.js";

function clearStaleFacIvaIfExplicitZero(state, rowIdx) {
  const [s, e] = groupBounds(state.rows, rowIdx);
  const groupRows = state.rows.slice(s, e);
  if (allContentLinesExplicitZeroIva(groupRows)) {
    clearFacIvaFooter(groupRows);
  }
}

export function isTotalAffectingKey(k) {
  return (
    k === "invoice_line_ids/quantity" ||
    k === "invoice_line_ids/price_unit" ||
    k === "iva_monto" ||
    k === "otros_impuestos_monto" ||
    /^otros_impuestos_\d+_monto$/.test(k)
  );
}

/** Re-renderiza si el modo cruza el límite line (cambia columna IVA vs pie editable). */
export function maybeRerenderOnTaxModeChange(state, rowIdx, handlers) {
  const [s, e] = groupBounds(state.rows, rowIdx);
  const compKey = String(state.rows[s]?.__comprobante_idx ?? s);
  const groupRows = state.rows.slice(s, e);
  const oldMode = state.comprobanteTaxModes?.[compKey];
  const newMode = classifyComprobanteTaxMode(groupRows);
  state.comprobanteTaxModes[compKey] = newMode;
  if (oldMode !== newMode && (oldMode === "line" || newMode === "line")) {
    handlers?.onRerender?.();
    return true;
  }
  return false;
}

export function refreshComprobanteHints(tableWrap, state) {
  tableWrap.querySelectorAll("[data-doc-hint-row]").forEach((el) => {
    const r = parseInt(el.getAttribute("data-doc-hint-row"), 10);
    const hint = comprobanteDigitUiHint(state.rows[r]?.[DOC_NUM_KEY]);
    if (!hint) {
      el.textContent = "";
      el.hidden = true;
      el.className = "fieldHint";
      return;
    }
    el.textContent = hint.text;
    el.hidden = false;
    el.className = hint.kind === "bad" ? "fieldHint bad" : "fieldHint warn";
  });
}

export function handleSelectionChange(state, r, k, ctx) {
  const { refs, handlers } = ctx;
  const tableWrap = refs?.tableWrap;
  if (k === "invoice_line_ids/account_id") {
    propagateAccountDown(state.rows);
    handlers.onRerender?.();
    return;
  }
  if (k === "partner_id") {
    applyProveedorToCuit(state, r);
    // Unifica partner en todas las filas del comprobante (como el backend).
    const [s, e] = groupBounds(state.rows, r);
    const partner = String(state.rows[r]?.partner_id ?? "").trim();
    for (let i = s; i < e; i++) {
      if (state.rows[i]) state.rows[i].partner_id = partner;
    }
    // Siempre rematchear: aparece/desaparece «Buscar OCs» según el nuevo proveedor.
    if (handlers.onRematchPurchase) {
      state.skipAutoSave = true;
      handlers.onRematchPurchase(r);
      return;
    }
    handlers.onRerender?.();
    return;
  }
  if (k === "l10n_latam_document_type_id") {
    const docTypeRaw = String(state.rows[r]?.[k] ?? "").trim();
    const ivaKey = "iva_pct";
    const docOpts = state.options?.document_types || [];
    const isFacturaC =
      isFacturaCTypeId(docTypeRaw, state) ||
      (() => {
        const lab = findOptionLabel(docOpts, docTypeRaw).toUpperCase();
        return lab === "FACTURAS C" || lab === "FACTURA C" || lab === "C";
      })();
    if (isFacturaC) {
      state.rows[r][ivaKey] = "IVA No Corresponde";
      state.rows[r].__iva_monto_manual = false;
      clearStaleFacIvaIfExplicitZero(state, r);
      const ivaSel = tableWrap?.querySelector(`select[data-r="${r}"][data-k="${ivaKey}"]`);
      if (ivaSel) ivaSel.value = "IVA No Corresponde";
      handlers.onRerender?.();
      return;
    }
  }
  if (k === "iva_pct") {
    state.rows[r].__iva_monto_manual = false;
    clearStaleFacIvaIfExplicitZero(state, r);
    if (!maybeRerenderOnTaxModeChange(state, r, handlers)) {
      handlers.onUpdateComprobanteFooters?.();
    }
    return;
  }
  if (k === "otros_impuestos" || /^otros_impuestos_\d+$/.test(k)) {
    updateRowTotals(state, refs, r);
    handlers.onUpdateComprobanteFooters?.();
    return;
  }
}
