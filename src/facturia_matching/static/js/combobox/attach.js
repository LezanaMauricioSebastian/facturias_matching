import { applyProveedorToCuit } from "../rows/index.js";
import { findOptionLabel, filterOptions, optionValue } from "../utils/index.js";
import { mergePartnerOptions, searchPartnersRemote } from "../api/partners.js";
import { createOdooCatalogItem } from "../api/catalogCreate.js";
import {
  closeOpenCombobox,
  dismissCombobox,
  getOpenCombobox,
  openComboboxList,
  positionComboboxList,
  setOpenCombobox,
} from "./dropdown.js";

const REMOTE_PARTNER_DEBOUNCE_MS = 280;

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
    let remoteTimer = null;
    let remoteSeq = 0;
    let creatingCatalog = false;
    let partnerQuerySettled = "";

    const syncDisplayFromValue = () => {
      const v = getValue();
      if (!v && state.excelUser) {
        if (k === "partner_id") {
          input.value = String(state.rows[r]?.["Nombre de Proveedor"] || state.rows[r]?.__excel_proveedor || "").trim();
          return;
        }
        if (k === "invoice_line_ids/product_id") {
          input.value = String(state.rows[r]?.["Nombre de producto"] || state.rows[r]?.__excel_producto || "").trim();
          return;
        }
      }
      input.value = v ? findOptionLabel(getOpts(), v) || v : "";
    };

    const createNameFor = (query) => {
      if (state.excelUser || state.odooProfile !== "aliare") return "";
      if (optKey !== "proveedores" && optKey !== "productos") return "";
      const q = String(query || "").trim();
      if (q.length < 2) return "";
      if (optKey === "proveedores" && partnerQuerySettled !== q) return "";
      const qKey = q.toLowerCase();
      const exact = getOpts().some((o) => {
        const name =
          o && typeof o === "object" ? String(o.name || o.label || "").trim() : String(o ?? "").trim();
        return name.toLowerCase() === qKey;
      });
      return exact ? "" : q;
    };

    const openList = (query, optsOverride = null) => {
      const sameRoot = getOpenCombobox()?.root === root;
      dismissCombobox(!sameRoot);
      const opts = optsOverride || getOpts();
      const cellVal = getValue();
      setOpenCombobox(
        openComboboxList(root, input, listEl, opts, cellVal, query, createNameFor(query))
      );
      const entry = getOpenCombobox();
      if (entry) entry.r = r;
      if (entry) entry.k = k;
    };

    const scheduleRemotePartnerSearch = (query) => {
      if (optKey !== "proveedores" || state.excelUser) return;
      const q = String(query || "").trim();
      if (q.length < 2) return;
      if (remoteTimer) window.clearTimeout(remoteTimer);
      const seq = ++remoteSeq;
      remoteTimer = window.setTimeout(async () => {
        try {
          const remote = await searchPartnersRemote(state, q);
          if (seq !== remoteSeq) return;
          if (getOpenCombobox()?.root !== root) return;
          if (String(input.value || "").trim() !== q) return;
          partnerQuerySettled = q;
          mergePartnerOptions(state, remote);
          const local = filterOptions(getOpts(), q, 50);
          const byId = new Map();
          for (const o of [...remote, ...local]) {
            const id = optionValue(o);
            if (!id || byId.has(id)) continue;
            byId.set(id, o);
          }
          openList(q, [...byId.values()].slice(0, 50));
        } catch {
          if (seq !== remoteSeq) return;
          partnerQuerySettled = q;
          if (getOpenCombobox()?.root !== root) return;
          if (String(input.value || "").trim() !== q) return;
          openList(q);
        }
      }, REMOTE_PARTNER_DEBOUNCE_MS);
    };

    input.addEventListener("focus", () => {
      if (input.disabled) return;
      openList("");
    });

    input.addEventListener("input", () => {
      if (input.disabled) return;
      if (optKey === "proveedores") partnerQuerySettled = "";
      openList(input.value);
      scheduleRemotePartnerSearch(input.value);
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

    const clearProductMatchMeta = () => {
      if (state.rows[r].__product_suggested) {
        state.rows[r].__product_suggested = "";
        root.classList.remove("combobox-suggested");
      }
      // UM se recalcula en rematch-uom al cambiar producto; al borrar, limpiar acá.
      if (state.rows[r].__um_empresa_id) {
        state.rows[r].__um_empresa_id = "";
        state.rows[r].__um_empresa = "";
        state.rows[r].__um_factor = "";
        state.rows[r].__um_note = "";
      }
    };

    input.addEventListener("blur", () => {
      window.setTimeout(() => {
        if (getOpenCombobox()?.root === root) closeOpenCombobox();
        if (!input.value.trim() && getValue()) {
          state.rows[r][k] = "";
          if (k === "invoice_line_ids/product_id") clearProductMatchMeta();
          onSelectionChange?.(r, k);
        } else {
          syncDisplayFromValue();
        }
      }, 150);
    });

    listEl.addEventListener("mousedown", (e) => {
      e.preventDefault();
    });

    const selectCatalogValue = (v) => {
      const changedProduct =
        k === "invoice_line_ids/product_id" && v !== String(state.rows[r][k] ?? "");
      state.rows[r][k] = v;
      if (state.excelUser && k === "partner_id") {
        state.rows[r]["Nombre de Proveedor"] = v;
      }
      if (state.excelUser && k === "invoice_line_ids/product_id") {
        state.rows[r]["Nombre de producto"] = v;
        state.rows[r].__excel_producto = v;
      }
      if (changedProduct) {
        if (state.rows[r].__product_suggested) {
          state.rows[r].__product_suggested = "";
          root.classList.remove("combobox-suggested");
        }
        state.rows[r].__um_empresa_id = "";
        state.rows[r].__um_empresa = "";
        state.rows[r].__um_factor = "";
        state.rows[r].__um_note = "";
      }
      input.value = findOptionLabel(getOpts(), v) || v;
      listEl.hidden = true;
      root.classList.remove("combobox-open");
      setOpenCombobox(null);
      onSelectionChange?.(r, k);
    };

    listEl.addEventListener("click", (e) => {
      const btn = e.target.closest(".combobox-item");
      if (!btn || creatingCatalog) return;
      if (btn.getAttribute("data-create") === "1") {
        const name = btn.getAttribute("data-name") || "";
        if (!name) return;
        creatingCatalog = true;
        btn.disabled = true;
        btn.textContent = "Creando…";
        const kind = optKey === "productos" ? "product" : "partner";
        const vat = kind === "partner" ? String(state.rows[r]?.CUIT || "").trim() : "";
        createOdooCatalogItem(state, kind, { name, vat })
          .then((created) => {
            selectCatalogValue(String(created.id));
          })
          .catch((err) => {
            const note = document.createElement("div");
            note.className = "combobox-empty";
            note.textContent = err?.message || String(err);
            listEl.prepend(note);
            btn.disabled = false;
            btn.textContent = `Crear «${name}»`;
          })
          .finally(() => {
            creatingCatalog = false;
          });
        return;
      }
      selectCatalogValue(btn.getAttribute("data-value") ?? "");
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
