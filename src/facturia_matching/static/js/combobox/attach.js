import { applyProveedorToCuit } from "../rows/index.js";
import { findOptionLabel } from "../utils/index.js";
import {
  closeOpenCombobox,
  dismissCombobox,
  getOpenCombobox,
  openComboboxList,
  positionComboboxList,
  setOpenCombobox,
} from "./dropdown.js";

export function attachComboboxes(tableWrap, state, onSelectionChange) {
  tableWrap.querySelectorAll(".combobox").forEach((root) => {
    const r = parseInt(root.getAttribute("data-r"), 10);
    const k = root.getAttribute("data-k");
    const optKey = root.getAttribute("data-opt-key");
    const input = root.querySelector(".combobox-input");
    const listEl = root.querySelector(".combobox-list");
    if (!input || !listEl || !Number.isFinite(r) || !k || !optKey) return;

    const getOpts = () => state.options?.[optKey] || [];
    const getValue = () => String(state.rows[r]?.[k] ?? "").trim();

    const syncDisplayFromValue = () => {
      const v = getValue();
      input.value = v ? findOptionLabel(getOpts(), v) || v : "";
    };

    const openList = (query) => {
      const sameRoot = getOpenCombobox()?.root === root;
      dismissCombobox(!sameRoot);
      const opts = getOpts();
      const cellVal = getValue();
      setOpenCombobox(openComboboxList(root, input, listEl, opts, cellVal, query));
      const entry = getOpenCombobox();
      if (entry) entry.r = r;
      if (entry) entry.k = k;
    };

    input.addEventListener("focus", () => {
      if (input.disabled) return;
      openList("");
    });

    input.addEventListener("input", () => {
      if (input.disabled) return;
      openList(input.value);
    });

    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        closeOpenCombobox();
        input.blur();
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        const first = listEl.querySelector(".combobox-item");
        if (first && !listEl.hidden) first.click();
      }
    });

    input.addEventListener("blur", () => {
      window.setTimeout(() => {
        if (getOpenCombobox()?.root === root) closeOpenCombobox();
        if (!input.value.trim() && getValue()) {
          state.rows[r][k] = "";
          onSelectionChange?.(r, k);
        } else {
          syncDisplayFromValue();
        }
      }, 150);
    });

    listEl.addEventListener("mousedown", (e) => {
      e.preventDefault();
    });

    listEl.addEventListener("click", (e) => {
      const btn = e.target.closest(".combobox-item");
      if (!btn) return;
      const v = btn.getAttribute("data-value") ?? "";
      state.rows[r][k] = v;
      input.value = findOptionLabel(getOpts(), v) || v;
      listEl.hidden = true;
      root.classList.remove("combobox-open");
      setOpenCombobox(null);
      onSelectionChange?.(r, k);
    });
  });

  if (!attachComboboxes._docListener) {
    attachComboboxes._docListener = true;
    document.addEventListener("click", (e) => {
      const open = getOpenCombobox();
      if (!open) return;
      if (open.root.contains(e.target)) return;
      closeOpenCombobox();
    });
    window.addEventListener(
      "scroll",
      () => {
        const open = getOpenCombobox();
        if (!open) return;
        positionComboboxList(open.listEl, open.input);
      },
      true
    );
    window.addEventListener("resize", () => {
      const open = getOpenCombobox();
      if (!open) return;
      positionComboboxList(open.listEl, open.input);
    });
  }
}

export function applyProveedorSelection(state, rIdx) {
  applyProveedorToCuit(state, rIdx);
}
