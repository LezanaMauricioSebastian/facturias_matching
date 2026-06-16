export function isPadronOptionKey(k) {
  return (
    k === "proveedores" ||
    k === "rubros" ||
    k === "journals" ||
    k === "cuentas" ||
    k === "document_types"
  );
}

/** Opción de select: string legacy o {id, name, vat?}. */
export function optionValue(opt) {
  if (opt == null) return "";
  if (typeof opt === "string" || typeof opt === "number") return String(opt);
  if (typeof opt === "object" && opt.id != null) return String(opt.id);
  return String(opt.name ?? opt.label ?? "");
}

export function optionLabel(opt) {
  if (opt == null) return "";
  if (typeof opt === "string" || typeof opt === "number") return String(opt);
  if (typeof opt === "object") {
    const name = String(opt.name ?? opt.label ?? "").trim();
    const id = opt.id != null ? String(opt.id) : "";
    if (name && id && name !== id) return `${name} (${id})`;
    return name || id;
  }
  return String(opt);
}

export function findOptionLabel(opts, value) {
  const v = String(value ?? "");
  if (!v || !Array.isArray(opts)) return v;
  for (const o of opts) {
    if (optionValue(o) === v) return optionLabel(o);
  }
  return v;
}

export function mergeProductOptions(prev, incoming) {
  const a = Array.isArray(prev) ? prev : [];
  const b = Array.isArray(incoming) ? incoming : [];
  const seen = new Set();
  const out = [];
  for (const x of [...a, ...b]) {
    const s = (x ?? "").toString();
    if (!s || seen.has(s)) continue;
    seen.add(s);
    out.push(s);
  }
  return out;
}

export function otrosImpuestoKey(n) {
  return n === 1 ? "otros_impuestos" : `otros_impuestos_${n}`;
}

export function otrosImpuestoMontoKey(n) {
  return n === 1 ? "otros_impuestos_monto" : `otros_impuestos_${n}_monto`;
}

const IVA_PCT_SPECIAL = new Set(["IVA No Corresponde", "IVA No Gravado", "IVA Exento"]);

/** Impuesto IVA (alícuota %): 10.5 → 10,5 para el selector. */
export function normalizeIvaPctValue(raw) {
  const s = String(raw ?? "").trim();
  if (!s || IVA_PCT_SPECIAL.has(s)) return s;
  const cleaned = s.replace(/\s+/g, "");
  if (/^\d+\.\d+$/.test(cleaned)) return cleaned.replace(".", ",");
  return s;
}

export function isFacturaCTypeId(docTypeId, state) {
  const v = String(docTypeId ?? "").trim();
  if (!v) return false;
  const ids = state?.options?.facturas_c_type_ids;
  if (Array.isArray(ids) && ids.length) {
    return ids.map(String).includes(v);
  }
  return false;
}

export function toNumberLoose(v) {
  if (v == null) return 0;
  const s = String(v).trim();
  if (!s) return 0;
  const hasComma = s.includes(",");
  const dotCount = (s.match(/\./g) || []).length;
  const normalized = hasComma
    ? s.replace(/\./g, "").replace(",", ".")
    : (() => {
        const m = /^([+-]?\d+)\.(\d+)$/.exec(s);
        if (dotCount === 1 && m && m[2].length !== 3) return s.replace(/,/g, "");
        return s.replace(/\./g, "").replace(/,/g, "");
      })();
  const n = Number(normalized);
  return Number.isFinite(n) ? n : 0;
}

/** Parsea strings/números con convención es-AR (y "10.5" sin coma). null si no es numérico. */
export function tryParseNumericString(raw) {
  if (raw == null) return null;
  if (typeof raw === "number") return Number.isFinite(raw) ? raw : null;
  const s = String(raw).trim();
  if (!s) return null;
  const cleaned = s.replace(/\s+/g, "");
  const okEsAr = /^[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?$/.test(cleaned);
  const okDotDecimal = /^[+-]?\d+\.\d+$/.test(cleaned) && !cleaned.includes(",");
  if (!okEsAr && !okDotDecimal) return null;
  const num = toNumberLoose(cleaned);
  return Number.isFinite(num) ? num : null;
}

function isMoneyNumericKey(key) {
  return (
    key === "iva_monto" ||
    key === "otros_impuestos_monto" ||
    /^otros_impuestos_\d+_monto$/.test(key)
  );
}

/** Opciones de formato es-AR: punto miles, coma decimal (ej. 82.000,52). */
export function numericFormatOptions(key) {
  if (isMoneyNumericKey(key)) return { max: 2, min: 2 };
  return { max: 6, min: 0 };
}

export function numericMaxFractionDigits(key) {
  return numericFormatOptions(key).max;
}

export function numericMinFractionDigits(key) {
  return numericFormatOptions(key).min;
}

/** Formato manual es-AR: 82000.52 → "82.000,52" */
function formatNumberEsARManual(n, maxFractionDigits, minFractionDigits) {
  const negative = n < 0;
  const abs = Math.abs(n);
  const factor = Math.pow(10, maxFractionDigits);
  const rounded = Math.round(abs * factor) / factor;
  let [intPart, decPart = ""] = rounded.toFixed(maxFractionDigits).split(".");
  intPart = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  if (minFractionDigits > 0) decPart = decPart.padEnd(minFractionDigits, "0");
  else decPart = decPart.replace(/0+$/, "");
  const body = decPart ? `${intPart},${decPart}` : intPart;
  return negative ? `-${body}` : body;
}

/** Valor para mostrar en inputs numéricos (es-AR). Respeta texto no parseable (edición parcial). */
export function formatNumericForDisplay(raw, keyOrMax = 6, minFractionDigits = 0) {
  const opts =
    typeof keyOrMax === "string"
      ? numericFormatOptions(keyOrMax)
      : { max: keyOrMax, min: minFractionDigits };
  const num = tryParseNumericString(raw);
  if (num == null) return String(raw ?? "").trim();
  return formatNumberEsAR(num, opts.max, opts.min);
}

/** Normaliza fila/estado: string parseable → formato es-AR. */
export function normalizeNumericValue(raw, keyOrMax = 6, minFractionDigits = 0) {
  const opts =
    typeof keyOrMax === "string"
      ? numericFormatOptions(keyOrMax)
      : { max: keyOrMax, min: minFractionDigits };
  const num = tryParseNumericString(raw);
  if (num == null) return String(raw ?? "").trim();
  return formatNumberEsAR(num, opts.max, opts.min);
}

export function normalizeNumericFieldsInRows(state) {
  const numericCols = (state.columns || []).filter((c) => c.type === "numeric");
  for (const row of state.rows || []) {
    for (const c of numericCols) {
      const v = row[c.key];
      if (v == null || String(v).trim() === "") continue;
      row[c.key] = normalizeNumericValue(v, c.key);
    }
  }
}

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

/** Punto = miles, coma = decimales (ej. 82.000,52). */
export function formatNumberEsAR(n, maxFractionDigits = 2, minFractionDigits = 0) {
  const num = Number(n);
  if (!Number.isFinite(num)) return "";
  try {
    return new Intl.NumberFormat("es-AR", {
      minimumFractionDigits: minFractionDigits,
      maximumFractionDigits: maxFractionDigits,
      useGrouping: true,
    }).format(num);
  } catch {
    return formatNumberEsARManual(num, maxFractionDigits, minFractionDigits);
  }
}

export function formatMoney(n) {
  try {
    return new Intl.NumberFormat("es-AR", { style: "currency", currency: "ARS" }).format(n);
  } catch {
    return "$" + (Math.round(n * 100) / 100).toFixed(2);
  }
}
