export const el = (id) => document.getElementById(id);

export function getDomRefs() {
  return {
    statusEl: el("status"),
    tableWrap: el("tableWrap"),
    summaryEl: el("summary"),
    btnBuscar: el("btnBuscar"),
    btnOdooImportTest: el("btnOdooImportTest"),
    btnDescargar: el("btnDescargar"),
    btnAddOtroImpuesto: el("btnAddOtroImpuesto"),
    totalGeneralEl: el("totalGeneral"),
    processNumberEl: el("processNumber"),
  };
}

export function setStatus(statusEl, msg, kind) {
  statusEl.textContent = msg || "";
  statusEl.className = "status" + (kind ? (" " + kind) : "");
}

