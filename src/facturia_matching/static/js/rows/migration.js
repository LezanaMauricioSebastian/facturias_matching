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
  for (let i = 1; i < rows.length; i++) {
    const prev = rows[i - 1];
    const cur = rows[i];
    const prevNro = String(prev?.["l10n_latam_document_number"] ?? "").trim();
    const curNro = String(cur?.["l10n_latam_document_number"] ?? "").trim();
    if (!curNro && prevNro) {
      const ak = "invoice_line_ids/account_id";
      if (!String(cur?.[ak] ?? "").trim() && String(prev?.[ak] ?? "").trim()) cur[ak] = prev[ak];
    }
  }
}
