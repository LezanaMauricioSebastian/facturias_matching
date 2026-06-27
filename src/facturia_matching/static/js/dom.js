export const el = (id) => document.getElementById(id);

export function getDomRefs() {
  return {
    statusEl: el("status"),
    tableWrap: el("tableWrap"),
    summaryEl: el("summary"),
    ocPickerBar: el("ocPickerBar"),
    ocPickerDialog: el("ocPickerDialog"),
    btnBuscar: el("btnBuscar"),
    btnOdooImportTest: el("btnOdooImportTest"),
    btnDescargar: el("btnDescargar"),
    btnRevertir: el("btnRevertir"),
    totalGeneralEl: el("totalGeneral"),
    companyNumberEl: el("companyNumber"),
    processNumberEl: el("processNumber"),
  };
}

export function setStatus(statusEl, msg, kind) {
  statusEl.textContent = msg || "";
  statusEl.className = "status" + (kind ? (" " + kind) : "");
}

