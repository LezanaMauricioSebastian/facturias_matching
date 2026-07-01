import { selectOc } from "../api/index.js";
import { openOcPicker, renderOcPickerBar } from "./render.js";

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
