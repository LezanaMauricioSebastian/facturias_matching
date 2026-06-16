import {
  formatDateDDMMYYYY,
  normalizeNumericValue,
  parseDateLoose,
  tryParseNumericString,
} from "./utils.js";

const INV_KEY = "l10n_latam_document_number";

/** UI en tiempo real: null = válido o vacío; warn = 13 dígitos sin guión; bad = no cumple formato. */
export function comprobanteDigitUiHint(raw) {
  const v = String(raw ?? "").trim();
  if (!v) return null;
  if (/^\d{13}$/.test(v)) {
    return {
      kind: "warn",
      text: `Sin guión: al exportar quedará ${v.slice(0, 5)}-${v.slice(5)}.`,
    };
  }
  if (/^\d{5}-\d{8}$/.test(v)) return null;
  return {
    kind: "bad",
    text: "Formato inválido. Usá 12345-12345678 (5 y 8 dígitos) o 13 dígitos seguidos.",
  };
}

export function validateRows(state) {
  const ivaKey = "iva_pct";
  for (let idx = 0; idx < state.rows.length; idx++) {
    const row = state.rows[idx];
    const v = String(row?.[ivaKey] ?? "").trim();
    if (!v) return `Impuesto IVA vacío en ${ivaKey} (fila ${idx + 1}).`;
  }

  for (let idx = 0; idx < state.rows.length; idx++) {
    const row = state.rows[idx];
    let v = String(row?.[INV_KEY] ?? "").trim();
    if (!v) continue;
    if (/^\d{13}$/.test(v)) {
      v = `${v.slice(0, 5)}-${v.slice(5)}`;
      row[INV_KEY] = v;
    }
    if (!/^\d{5}-\d{8}$/.test(v)) {
      return `Número de documento inválido en ${INV_KEY} (fila ${idx + 1}): "${v}" (esperado: 12345-12345678)`;
    }
  }

  const numericKeys = new Set(state.columns.filter((c) => c.type === "numeric").map((c) => c.key));

  const parseNumberStrict = (raw) => {
    const s = String(raw ?? "").trim();
    if (!s) return { ok: true, num: null };
    const num = tryParseNumericString(s);
    if (num == null) return { ok: false, num: null };
    return { ok: true, num };
  };

  for (let idx = 0; idx < state.rows.length; idx++) {
    const row = state.rows[idx];
    for (const k of numericKeys) {
      const v = (row?.[k] ?? "").toString().trim();
      if (!v) continue;
      const parsed = parseNumberStrict(v);
      if (!parsed.ok) return `Valor numérico inválido en ${k} (fila ${idx + 1}): "${v}"`;
      if (parsed.num != null) row[k] = normalizeNumericValue(v, k);
    }
  }

  const accountKey = "invoice_line_ids/account_id";
  for (let idx = 0; idx < state.rows.length; idx++) {
    const row = state.rows[idx];
    const hasLine =
      !!String(row?.["invoice_line_ids/name"] ?? "").trim() ||
      !!String(row?.["invoice_line_ids/quantity"] ?? "").trim() ||
      !!String(row?.["invoice_line_ids/price_unit"] ?? "").trim();
    if (!hasLine) continue;
    const acc = String(row?.[accountKey] ?? "").trim();
    if (!acc) return `Cuenta contable vacía en ${accountKey} (fila ${idx + 1}).`;
  }

  const requiredDateFormat = "DD/MM/YYYY";

  for (let idx = 0; idx < state.rows.length; idx++) {
    const row = state.rows[idx];
    for (const k of ["invoice_date", "invoice_date_due"]) {
      const v0 = String(row?.[k] ?? "").trim();
      if (!v0) continue;
      const parts = parseDateLoose(v0);
      if (!parts) {
        return `Fecha inválida en ${k} (fila ${idx + 1}): "${v0}". Debe tener formato ${requiredDateFormat} (también se acepta DD-MM-YYYY o YYYY-MM-DD al cargar).`;
      }
      row[k] = formatDateDDMMYYYY(parts);
    }
  }

  return null;
}

