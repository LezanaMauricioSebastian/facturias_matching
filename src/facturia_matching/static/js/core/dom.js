import { isEmbedMode } from "../utils/index.js";

export const el = (id) => document.getElementById(id);

export function getDomRefs() {
  return {
    statusEl: el("status"),
    tableWrap: el("tableWrap"),
    summaryEl: el("summary"),
    ocPickerBar: el("ocPickerBar"),
    ocPickerDialog: el("ocPickerDialog"),
    btnBuscar: el("btnBuscar"),
    btnOdooImport: el("btnOdooImport"),
    btnDescargar: el("btnDescargar"),
    btnRevertir: el("btnRevertir"),
    totalGeneralEl: el("totalGeneral"),
    companyNumberEl: el("companyNumber"),
    processNumberEl: el("processNumber"),
  };
}

const EMBED_AUTOSAVE_NOTE = "Los cambios se guardan automáticamente";

export function setStatus(statusEl, msg, kind) {
  let text = msg || "";
  if (
    isEmbedMode() &&
    kind === "ok" &&
    text &&
    !text.includes(EMBED_AUTOSAVE_NOTE) &&
    !text.startsWith("CSV descargado") &&
    !text.startsWith("Importación") &&
    !text.includes("importad")
  ) {
    text += ` · ${EMBED_AUTOSAVE_NOTE}`;
  }
  statusEl.textContent = text;
  statusEl.className = "status" + (kind ? (" " + kind) : "");
}
