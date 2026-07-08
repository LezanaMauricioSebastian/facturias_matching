import { groupBounds } from "../singleLine/index.js";
import { normalizeIvaPctValue, otrosImpuestoKey } from "../utils/index.js";

export function migrateRowKeys(row) {
  if (!row || typeof row !== "object") return;
  if (row.etiqueta != null && row["invoice_line_ids/name"] == null) {
    row["invoice_line_ids/name"] = row.etiqueta;
  }
  if (row.cuenta != null && row["invoice_line_ids/account_id"] == null) {
    row["invoice_line_ids/account_id"] = row.cuenta;
  }
  if (row.otros_impuesto_1 != null && row.otros_impuestos == null) {
    row.otros_impuestos = row.otros_impuesto_1;
  }
  for (let n = 2; n <= 20; n++) {
    const oldK = `otros_impuesto_${n}`;
    const newK = otrosImpuestoKey(n);
    if (row[oldK] != null && row[newK] == null) row[newK] = row[oldK];
  }
  if (row.iva_monto == null) row.iva_monto = "";
  if (row.otros_impuestos_monto == null) row.otros_impuestos_monto = "";
  if (row.iva_pct != null && String(row.iva_pct).trim()) {
    row.iva_pct = normalizeIvaPctValue(row.iva_pct);
  }
}

export function applyProveedorToCuit(state, rIdx) {
  const row = state.rows?.[rIdx];
  if (!row) return;
  const prov = (row.partner_id ?? "").toString();
  if (!prov) return;
  const map = state.options?.proveedores_cuit_map || {};
  const cuit = map[prov];
  if (cuit) row.CUIT = cuit;
}

export function propagateAccountDown(rows) {
  if (!Array.isArray(rows) || !rows.length) return;
  const accountKey = "invoice_line_ids/account_id";
  let i = 0;
  while (i < rows.length) {
    const [start, end] = groupBounds(rows, i);
    const account = String(rows[start]?.[accountKey] ?? "").trim();
    if (account) {
      for (let j = start + 1; j < end; j++) {
        const cur = rows[j];
        if (!cur || typeof cur !== "object") continue;
        if (!String(cur[accountKey] ?? "").trim()) cur[accountKey] = account;
      }
    }
    i = end;
  }
}
