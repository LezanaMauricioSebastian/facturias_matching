export function isPadronOptionKey(k) {
  return (
    k === "proveedores" ||
    k === "rubros" ||
    k === "journals" ||
    k === "cuentas" ||
    k === "document_types"
  );
}

/** Listas grandes: combobox con búsqueda en lugar de <select> con miles de <option>. */
export function isComboboxOptionKey(k) {
  return (
    k === "proveedores" ||
    k === "rubros" ||
    k === "journals" ||
    k === "cuentas" ||
    k === "productos"
  );
}

export function filterOptions(opts, query, limit = 50) {
  const list = Array.isArray(opts) ? opts : [];
  const q = String(query ?? "").trim().toLowerCase();
  if (!q) return list.slice(0, limit);
  const out = [];
  for (const o of list) {
    const lab = optionLabel(o).toLowerCase();
    const val = optionValue(o).toLowerCase();
    if (lab.includes(q) || val.includes(q)) {
      out.push(o);
      if (out.length >= limit) break;
    }
  }
  return out;
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
    const key = optionValue(x);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(x);
  }
  return out;
}

export function mergeEtiquetaOptions(prev, incoming) {
  const a = Array.isArray(prev) ? prev : [];
  const b = Array.isArray(incoming) ? incoming : [];
  const seen = new Set();
  const out = [];
  for (const x of [...a, ...b]) {
    const s = String(x ?? "").trim();
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
