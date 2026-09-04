/**
 * Pestaña FacturIA (solo UI dev/staging): muestra json_data crudo.
 */
import { buildApiQuery } from "../utils/index.js";

export function isDevUi(state) {
  return state?.uiEnv === "dev";
}

export function wireFacturiaTab(state, refs) {
  const tabs = refs.processTabs;
  if (!tabs || !isDevUi(state)) {
    if (tabs) tabs.hidden = true;
    return;
  }
  tabs.hidden = false;
  tabs.querySelectorAll("[data-process-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const name = btn.getAttribute("data-process-tab");
      setActiveProcessTab(refs, name);
      if (name === "facturia") {
        loadFacturiaRaw(state, refs).catch((e) => {
          if (refs.facturiaRaw) {
            refs.facturiaRaw.textContent = e?.message || String(e);
          }
        });
      }
    });
  });
}

export function setActiveProcessTab(refs, name) {
  const tabs = refs.processTabs;
  if (!tabs) return;
  tabs.querySelectorAll("[data-process-tab]").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-process-tab") === name);
  });
  document.querySelectorAll("[data-process-panel]").forEach((panel) => {
    const match = panel.getAttribute("data-process-panel") === name;
    panel.hidden = !match;
  });
}

export async function loadFacturiaRaw(state, refs) {
  if (!refs.facturiaRaw) return;
  const pn = String(state.processNumber || "").trim();
  if (!pn) {
    refs.facturiaRaw.textContent = "Cargá un proceso para ver el JSON.";
    return;
  }
  if (state._facturiaRawFor === pn && state._facturiaRawText) {
    refs.facturiaRaw.textContent = state._facturiaRawText;
    return;
  }
  refs.facturiaRaw.textContent = "Cargando json_data…";
  const q = buildApiQuery({ empresa: state.empresa || "" });
  const res = await fetch(`/api/proceso/${encodeURIComponent(pn)}/facturia-raw${q}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data?.detail || `HTTP ${res.status}`);
  }
  const text = JSON.stringify(data.json_data ?? data, null, 2);
  state._facturiaRawFor = pn;
  state._facturiaRawText = text;
  refs.facturiaRaw.textContent = text;
}

/** Invalidar cache al cambiar de proceso. */
export function clearFacturiaRawCache(state) {
  state._facturiaRawFor = "";
  state._facturiaRawText = "";
}
