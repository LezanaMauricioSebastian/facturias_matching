import { groupBounds } from "../singleLine/index.js";

export function listComprobanteGroups(rows) {
  if (!Array.isArray(rows) || !rows.length) return [];
  const groups = [];
  let i = 0;
  while (i < rows.length) {
    const [s, e] = groupBounds(rows, i);
    const rowIndices = [];
    for (let j = s; j < e; j++) rowIndices.push(j);
    groups.push({
      compIdx: rows[s]?.__comprobante_idx ?? s,
      start: s,
      end: e,
      rowIndices,
    });
    i = e;
  }
  return groups;
}

export function comprobanteGroupByIdx(rows, compIdx) {
  return listComprobanteGroups(rows).find((g) => String(g.compIdx) === String(compIdx)) ?? null;
}
