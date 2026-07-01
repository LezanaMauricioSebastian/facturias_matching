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
