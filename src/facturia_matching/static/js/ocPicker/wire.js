import {
  openOcPicker,
  renderOcPickerBar,
  setOverwriteOcPriceForComprobante,
} from "./render.js";
import { searchOc, selectOc } from "../api/index.js";

export function wireOcPicker(state, refs, handlers, setStatusFn) {
  const onOcAction = (e) => {
    const searchBtn = e.target.closest("[data-search-oc]");
    if (searchBtn) {
      const compIdx = Number(searchBtn.getAttribute("data-search-oc"));
      if (!Number.isFinite(compIdx)) return;
      searchOc(state, refs, setStatusFn, handlers, compIdx).then(() => {
        handlers?.onRerender?.();
        openOcPicker(state, refs, handlers, setStatusFn, String(compIdx));
      });
      return;
    }

    const openBtn = e.target.closest("[data-open-oc]");
    if (openBtn) {
      const compKey = openBtn.getAttribute("data-open-oc");
      const candidates = state.purchaseMatching?.oc_candidates_by_comprobante?.[compKey] || [];
      // Si el modal quedaría vacío, re-buscar en Odoo antes de abrir.
      if (!candidates.length) {
        const compIdx = Number(compKey);
        if (!Number.isFinite(compIdx)) return;
        searchOc(state, refs, setStatusFn, handlers, compIdx).then(() => {
          handlers?.onRerender?.();
          openOcPicker(state, refs, handlers, setStatusFn, String(compIdx));
        });
        return;
      }
      openOcPicker(state, refs, handlers, setStatusFn, compKey);
    }
  };

  refs.tableWrap?.addEventListener("click", onOcAction);
  // Compat: barra global vacía (por si queda en HTML)
  refs.ocPickerBar?.addEventListener("click", onOcAction);

  refs.tableWrap?.addEventListener("change", (e) => {
    const cb = e.target.closest("input[data-overwrite-oc-price]");
    if (!cb || cb.type !== "checkbox") return;
    const compKey = cb.getAttribute("data-overwrite-oc-price");
    if (compKey == null) return;
    setOverwriteOcPriceForComprobante(state.rows, compKey, cb.checked);
    handlers?.onAutoSave?.();
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

    const deselectBtn = e.target.closest(".ocDeselectBtn");
    if (deselectBtn && !deselectBtn.classList.contains("isActive")) {
      const compIdx = Number(deselectBtn.getAttribute("data-comp"));
      dialog.close?.();
      dialog.removeAttribute("open");
      selectOc(state, refs, setStatusFn, handlers, compIdx, 0).then(() => {
        handlers?.onRerender?.();
        renderOcPickerBar(state, refs, handlers, setStatusFn);
      });
      return;
    }

    const selectBtn = e.target.closest(".ocSelectBtn");
    if (selectBtn && !selectBtn.disabled) {
      const compIdx = Number(selectBtn.getAttribute("data-comp"));
      const orderId = Number(selectBtn.getAttribute("data-order"));
      dialog.close?.();
      dialog.removeAttribute("open");
      selectOc(state, refs, setStatusFn, handlers, compIdx, orderId).then(() => {
        handlers?.onRerender?.();
        renderOcPickerBar(state, refs, handlers, setStatusFn);
      });
    }
  });
}
