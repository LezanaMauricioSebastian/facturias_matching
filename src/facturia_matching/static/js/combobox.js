import { applyProveedorToCuit } from "./rows.js";
import {
  escapeAttr,
  filterOptions,
  findOptionLabel,
  isPadronOptionKey,
  optionLabel,
  optionValue,
} from "./utils.js";

let openCombobox = null;

const COMBOBOX_LIST_GAP = 4;
const COMBOBOX_LIST_MAX_HEIGHT = 220;

/** Coloca el listado fijo: abajo por defecto; arriba si no entra en viewport. */
function positionComboboxList(listEl, input) {
  const rect = input.getBoundingClientRect();
  listEl.style.position = "fixed";
  listEl.style.left = `${rect.left}px`;
  listEl.style.width = `${rect.width}px`;
  listEl.style.right = "auto";
  listEl.style.maxHeight = `${COMBOBOX_LIST_MAX_HEIGHT}px`;
  listEl.style.top = `${rect.bottom + COMBOBOX_LIST_GAP}px`;

  const contentHeight = listEl.scrollHeight;
  const spaceBelow = window.innerHeight - rect.bottom - COMBOBOX_LIST_GAP;
  const spaceAbove = rect.top - COMBOBOX_LIST_GAP;
  const openUp = spaceBelow < contentHeight && spaceAbove > spaceBelow;

  if (openUp) {
    const maxHeight = Math.min(COMBOBOX_LIST_MAX_HEIGHT, spaceAbove);
    const height = Math.min(contentHeight, maxHeight);
    listEl.style.top = `${rect.top - COMBOBOX_LIST_GAP - height}px`;
    listEl.style.maxHeight = `${maxHeight}px`;
    listEl.classList.add("combobox-list-above");
  } else {
    listEl.style.maxHeight = `${Math.min(COMBOBOX_LIST_MAX_HEIGHT, spaceBelow)}px`;
    listEl.classList.remove("combobox-list-above");
  }
}

function dismissCombobox(revertInput = true) {
  if (!openCombobox) return;
  const { root, input, value, opts, listEl } = openCombobox;
  if (listEl) {
    listEl.hidden = true;
    listEl.style.position = "";
    listEl.style.left = "";
    listEl.style.top = "";
    listEl.style.width = "";
    listEl.style.right = "";
    listEl.style.maxHeight = "";
    listEl.classList.remove("combobox-list-above");
  }
  root.classList.remove("combobox-open");
  if (revertInput) {
    const cellVal = value ?? "";
    input.value = cellVal ? findOptionLabel(opts, cellVal) : "";
  }
  openCombobox = null;
}

function closeOpenCombobox() {
  dismissCombobox(true);
}

function renderListItems(listEl, items, selectedValue) {
  if (!items.length) {
    listEl.innerHTML = '<div class="combobox-empty">Sin resultados</div>';
    return;
  }
  const parts = [];
  for (const o of items) {
    const ov = optionValue(o);
    const lab = optionLabel(o);
    const sel = ov === selectedValue ? " combobox-item-selected" : "";
    parts.push(
      `<button type="button" class="combobox-item${sel}" data-value="${escapeAttr(ov)}">${escapeAttr(lab)}</button>`
    );
  }
  listEl.innerHTML = parts.join("");
}

export function renderComboboxCellHtml({ rIdx, key, optKey, cellVal, tdStyle, loading, state }) {
  const opts = state.options?.[optKey] || [];
  const display =
    loading && !opts.length
      ? "Cargando…"
      : cellVal
        ? findOptionLabel(opts, cellVal) || cellVal
        : "";
  const dis = loading ? " disabled" : "";
  const cls = loading ? " combobox-loading" : "";
  const placeholder = loading ? "" : "Buscar…";
  return (
    `<td${tdStyle}>` +
    `<div class="combobox${cls}" data-r="${rIdx}" data-k="${key}" data-opt-key="${optKey}">` +
    `<input type="text" class="combobox-input" autocomplete="off" spellcheck="false"` +
    ` placeholder="${escapeAttr(placeholder)}" value="${escapeAttr(display)}"${dis} />` +
    `<div class="combobox-list" role="listbox" hidden></div>` +
    `</div></td>`
  );
}

export function isComboboxLoading(state, optKey) {
  const opts = state.options?.[optKey];
  return (
    (isPadronOptionKey(optKey) && state.padronLoading && (!opts || opts.length === 0)) ||
    (optKey === "productos" && state.productosLoading && (!opts || opts.length === 0))
  );
}

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
      const sameRoot = openCombobox?.root === root;
      dismissCombobox(!sameRoot);
      const opts = getOpts();
      const cellVal = getValue();
      const items = filterOptions(opts, query);
      renderListItems(listEl, items, cellVal);
      listEl.hidden = false;
      root.classList.add("combobox-open");
      positionComboboxList(listEl, input);
      openCombobox = { root, input, listEl, opts, value: cellVal, r, k };
    };

    input.addEventListener("focus", () => {
      if (input.disabled) return;
      openList("");
      input.select();
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
        if (openCombobox?.root === root) closeOpenCombobox();
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
      openCombobox = null;
      onSelectionChange?.(r, k);
    });
  });

  if (!attachComboboxes._docListener) {
    attachComboboxes._docListener = true;
    document.addEventListener("click", (e) => {
      if (!openCombobox) return;
      if (openCombobox.root.contains(e.target)) return;
      closeOpenCombobox();
    });
    window.addEventListener(
      "scroll",
      () => {
        if (!openCombobox) return;
        positionComboboxList(openCombobox.listEl, openCombobox.input);
      },
      true
    );
    window.addEventListener("resize", () => {
      if (!openCombobox) return;
      positionComboboxList(openCombobox.listEl, openCombobox.input);
    });
  }
}

export function applyProveedorSelection(state, rIdx) {
  applyProveedorToCuit(state, rIdx);
}
