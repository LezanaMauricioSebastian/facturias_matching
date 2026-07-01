const DATE_FIELD_KEYS = ["invoice_date", "invoice_date_due"];

/** Parsea DD/MM/YYYY, DD-MM-YYYY o YYYY-MM-DD. null si inválida. */
export function parseDateLoose(raw) {
  const s = String(raw ?? "").trim();
  if (!s) return null;
  const m = /^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$/.exec(s);
  const mIso = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s);
  if (!m && !mIso) return null;
  const dd = parseInt(m ? m[1] : mIso[3], 10);
  const mm = parseInt(m ? m[2] : mIso[2], 10);
  const yyyy = parseInt(m ? m[3] : mIso[1], 10);
  if (mm < 1 || mm > 12 || dd < 1 || dd > 31) return null;
  const dt = new Date(yyyy, mm - 1, dd);
  if (dt.getFullYear() !== yyyy || dt.getMonth() !== mm - 1 || dt.getDate() !== dd) return null;
  return { dd, mm, yyyy };
}

/** Formato canónico de fechas en la UI: dd/mm/yyyy */
export function formatDateDDMMYYYY(parts) {
  const d2 = String(parts.dd).padStart(2, "0");
  const m2 = String(parts.mm).padStart(2, "0");
  return `${d2}/${m2}/${parts.yyyy}`;
}

export function normalizeDateValue(raw) {
  const parts = parseDateLoose(raw);
  if (!parts) return String(raw ?? "").trim();
  return formatDateDDMMYYYY(parts);
}

export function normalizeDateFieldsInRows(state, keys = DATE_FIELD_KEYS) {
  for (const row of state.rows || []) {
    for (const k of keys) {
      const v = String(row[k] ?? "").trim();
      if (!v) continue;
      const parts = parseDateLoose(v);
      if (parts) row[k] = formatDateDDMMYYYY(parts);
    }
  }
}
