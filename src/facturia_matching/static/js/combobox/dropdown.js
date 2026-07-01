import {
  escapeAttr,
  filterOptions,
  findOptionLabel,
  isPadronOptionKey,
  optionLabel,
  optionValue,
} from "../utils/index.js";

let openCombobox = null;

const COMBOBOX_LIST_GAP = 4;
const COMBOBOX_LIST_MAX_HEIGHT = 220;

/** Coloca el listado fijo: abajo por defecto; arriba si no entra en viewport. */
export function positionComboboxList(listEl, input) {
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

export function dismissCombobox(revertInput = true) {
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

export function closeOpenCombobox() {
  dismissCombobox(true);
}

export function setOpenCombobox(entry) {
  openCombobox = entry;
}

export function getOpenCombobox() {
  return openCombobox;
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

export function openComboboxList(root, input, listEl, opts, cellVal, query) {
  const items = filterOptions(opts, query);
  renderListItems(listEl, items, cellVal);
  listEl.hidden = false;
  root.classList.add("combobox-open");
  positionComboboxList(listEl, input);
  return { root, input, listEl, opts, value: cellVal };
}
