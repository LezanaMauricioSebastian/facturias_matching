import {
  formatDateDDMMYYYY,
  normalizeNumericValue,
  parseDateLoose,
  tryParseNumericString,
} from "../utils/index.js";
import { classifyComprobanteTaxMode } from "../comprobanteTax/totals.js";
import { groupBounds, isFirstRowOfComprobante, mixedProcesoLineModeError } from "../singleLine/index.js";
import { normalizeComprobanteNumber } from "./documentNumber.js";

const INV_KEY = "l10n_latam_document_number";

function rowHasLineContent(row) {
  return (
    !!String(row?.["invoice_line_ids/name"] ?? "").trim() ||
    !!String(row?.["invoice_line_ids/quantity"] ?? "").trim() ||
    !!String(row?.["invoice_line_ids/price_unit"] ?? "").trim()
  );
}

export function validateRows(state) {
  const rows = state.rows || [];

  const mixedErr = mixedProcesoLineModeError(rows);
  if (mixedErr) return mixedErr;

  for (let idx = 0; idx < rows.length; idx++) {
    if (!isFirstRowOfComprobante(rows, idx)) continue;
    const row = rows[idx];
    if (!String(row?.partner_id ?? "").trim()) {
      return `Proveedor vacío en partner_id (fila ${idx + 1}).`;
    }
    // Modo Excel: sin Odoo; no exigir diario/cuenta.
    if (!state.excelUser && !String(row?.journal_id ?? "").trim()) {
      return `Diario vacío en journal_id (fila ${idx + 1}).`;
    }
  }

  // En header/mixed el IVA vive en el pie; solo exigir iva_pct en modo line.
  for (let idx = 0; idx < rows.length; idx++) {
    if (!isFirstRowOfComprobante(rows, idx)) continue;
    const [s, e] = groupBounds(rows, idx);
    const groupRows = rows.slice(s, e);
    const mode = classifyComprobanteTaxMode(groupRows);
    if (mode === "header" || mode === "mixed") continue;
    for (let i = s; i < e; i++) {
      const row = rows[i];
      if (!rowHasLineContent(row)) continue;
      const v = String(row?.iva_pct ?? "").trim();
      if (!v) return `IVA vacío en iva_pct (fila ${i + 1}).`;
    }
  }

  for (let idx = 0; idx < rows.length; idx++) {
    const row = rows[idx];
    let v = String(row?.[INV_KEY] ?? "").trim();
    if (!v) continue;
    v = normalizeComprobanteNumber(v);
    row[INV_KEY] = v;
    if (!/^\d{5}-\d{8}$/.test(v)) {
      return `Número de documento inválido en ${INV_KEY} (fila ${idx + 1}): "${v}" (esperado: 00001-00000001)`;
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

  for (let idx = 0; idx < rows.length; idx++) {
    const row = rows[idx];
    for (const k of numericKeys) {
      const v = (row?.[k] ?? "").toString().trim();
      if (!v) continue;
      const parsed = parseNumberStrict(v);
      if (!parsed.ok) return `Valor numérico inválido en ${k} (fila ${idx + 1}): "${v}"`;
      if (parsed.num != null) row[k] = normalizeNumericValue(v, k);
    }
  }

  if (!state.excelUser) {
    const accountKey = "invoice_line_ids/account_id";
    for (let idx = 0; idx < rows.length; idx++) {
      const row = rows[idx];
      if (!rowHasLineContent(row)) continue;
      const acc = String(row?.[accountKey] ?? "").trim();
      if (!acc) return `Cuenta contable vacía en ${accountKey} (fila ${idx + 1}).`;
    }
  }

  const requiredDateFormat = "DD/MM/YYYY";

  for (let idx = 0; idx < rows.length; idx++) {
    const row = rows[idx];
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
