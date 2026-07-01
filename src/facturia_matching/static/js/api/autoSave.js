import { apiContextBody, apiOdooQueryParams, buildApiQuery, isEmbedMode } from "../utils/index.js";

const AUTO_SAVE_DELAY_MS = 1500;

export function buildSummaryText(refs, state) {
  const proceso = String(state.processNumber || refs.processNumberEl?.value || "").trim();
  const parts = [`Filas: ${state.rows?.length || 0}`, `Proceso: ${proceso || "—"}`];
  if (state.source === "saved") parts.push("Guardado");
  else if (state.source === "generated") parts.push("Generado");
  if (state.saveStatus === "saving") parts.push("Guardando…");
  else if (state.saveStatus === "synced") parts.push("Sincronizado");
  else if (state.saveStatus === "error") parts.push("Error al guardar");
  return parts.join(" · ");
}

function badge(label, extraClass = "") {
  const cls = extraClass ? `metaBadge ${extraClass}` : "metaBadge";
  return `<span class="${cls}">${label}</span>`;
}

function buildSummaryHtml(state) {
  const badges = [];
  const n = state.rows?.length || 0;
  if (n) badges.push(badge(`${n} fila${n === 1 ? "" : "s"}`));
  if (state.source === "saved") badges.push(badge("Guardado"));
  else if (state.source === "generated") badges.push(badge("Generado"));
  if (state.saveStatus === "saving") badges.push(badge("Guardando…", "metaBadgePending"));
  else if (state.saveStatus === "synced") badges.push(badge("Sincronizado", "metaBadgeOk"));
  else if (state.saveStatus === "error") badges.push(badge("Error al guardar", "metaBadgeBad"));
  return badges.join("");
}

export function renderSummary(refs, state) {
  if (!refs?.summaryEl) return;
  if (isEmbedMode()) {
    refs.summaryEl.innerHTML = buildSummaryHtml(state);
    refs.summaryEl.className = "hint summaryHint summaryBadges";
    return;
  }
  refs.summaryEl.textContent = buildSummaryText(refs, state);
  refs.summaryEl.className = "hint summaryHint";
}

export function clearAutoSaveTimer(state) {
  if (state.autoSaveTimer) {
    clearTimeout(state.autoSaveTimer);
    state.autoSaveTimer = null;
  }
}

export function scheduleAutoSave(state, refs, setStatusFn) {
  if (state.skipAutoSave || !(state.rows && state.rows.length) || !state.processNumber) return;
  state.dirty = true;
  state.saveStatus = "pending";
  renderSummary(refs, state);
  clearAutoSaveTimer(state);
  state.autoSaveTimer = setTimeout(() => {
    state.autoSaveTimer = null;
    saveConversion(state, refs, setStatusFn);
  }, AUTO_SAVE_DELAY_MS);
}

export function flushAutoSave(state, refs, setStatusFn) {
  if (!state.dirty || state.skipAutoSave) return Promise.resolve();
  clearAutoSaveTimer(state);
  return saveConversion(state, refs, setStatusFn);
}

export async function saveConversion(state, refs, setStatusFn) {
  if (!(state.rows && state.rows.length) || !state.processNumber || state.saveInFlight) return;
  state.saveInFlight = true;
  state.saveStatus = "saving";
  renderSummary(refs, state);
  try {
    const body = { rows: state.rows, ...apiContextBody(state) };
    const res = await fetch(
      `/api/proceso/${encodeURIComponent(state.processNumber)}/conversion${buildApiQuery(apiOdooQueryParams(state))}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    );
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.detail || "No se pudo guardar");
    state.source = "saved";
    state.dirty = false;
    state.saveStatus = "synced";
    renderSummary(refs, state);
  } catch (e) {
    state.saveStatus = "error";
    renderSummary(refs, state);
    setStatusFn?.(e?.message || String(e), "bad");
  } finally {
    state.saveInFlight = false;
  }
}
