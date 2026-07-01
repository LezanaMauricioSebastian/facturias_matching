const INV_KEY = "l10n_latam_document_number";

export function groupBounds(rows, idx) {
  if (!Array.isArray(rows) || idx < 0 || idx >= rows.length) return [0, 0];
  const r = rows[idx];
  const rawIdx = r?.__comprobante_idx;
  const hasComprobanteIdx =
    rawIdx !== undefined &&
    rawIdx !== null &&
    !(typeof rawIdx === "string" && String(rawIdx).trim() === "");
  if (hasComprobanteIdx) {
    const target = Number(rawIdx);
    let s = idx;
    while (s > 0 && Number(rows[s - 1].__comprobante_idx) === target) s--;
    let e = idx + 1;
    while (e < rows.length && Number(rows[e].__comprobante_idx) === target) e++;
    return [s, e];
  }
  let s = idx;
  while (s > 0 && !String(rows[s]?.[INV_KEY] ?? "").trim()) s--;
  let e = idx + 1;
  while (e < rows.length && !String(rows[e]?.[INV_KEY] ?? "").trim()) e++;
  return [s, e];
}

export function isFirstRowOfComprobante(rows, rIdx) {
  const [s] = groupBounds(rows, rIdx);
  return s === rIdx;
}

export function comprobanteHasMultipleLines(rows, rIdx) {
  const [s, e] = groupBounds(rows, rIdx);
  return e - s > 1;
}
