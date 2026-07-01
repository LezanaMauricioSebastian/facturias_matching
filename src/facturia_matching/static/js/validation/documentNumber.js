/** Normaliza a formato Odoo 00001-00000001 (5 + 8 dígitos). Vacío si no hay dígitos. */
export function normalizeComprobanteNumber(raw) {
  const v = String(raw ?? "").trim();
  if (!v) return "";
  if (/^\d{13}$/.test(v)) return `${v.slice(0, 5)}-${v.slice(5)}`;
  const m = /^(\d+)-(\d+)$/.exec(v);
  if (m) return `${m[1].padStart(5, "0")}-${m[2].padStart(8, "0")}`;
  return v;
}

/** UI en tiempo real: null = válido o vacío; warn = se normalizará; bad = no cumple formato. */
export function comprobanteDigitUiHint(raw) {
  const v = String(raw ?? "").trim();
  if (!v) return null;
  const norm = normalizeComprobanteNumber(v);
  if (!/^\d{5}-\d{8}$/.test(norm)) {
    return {
      kind: "bad",
      text: "Formato inválido. Usá punto de venta y número (ej. 0001-6501 o 00001-00006501).",
    };
  }
  if (v === norm) return null;
  if (/^\d{13}$/.test(v)) {
    return { kind: "warn", text: `Sin guión: al exportar quedará ${norm}.` };
  }
  return { kind: "warn", text: `Se normalizará a ${norm} al guardar.` };
}
