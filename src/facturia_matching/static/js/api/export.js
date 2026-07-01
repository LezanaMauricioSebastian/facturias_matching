import { flushAutoSave } from "./autoSave.js";
import { odooImportTargetName } from "./bootstrap.js";
import { apiContextBody, apiOdooQueryParams, buildApiQuery } from "../utils/index.js";

export async function descargarCsv(state, setStatusFn, validateFn, refs) {
  const err = validateFn(state);
  if (err) {
    setStatusFn(err, "bad");
    return;
  }
  await flushAutoSave(state, refs, setStatusFn);
  setStatusFn("Generando CSV…");
  try {
    const res = await fetch("/api/csv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows: state.rows }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data?.detail || "No se pudo generar CSV");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "resultado.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setStatusFn("CSV descargado.", "ok");
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
  }
}

export async function importarOdoo(state, setStatusFn, validateFn, refs) {
  const err = validateFn(state);
  if (err) {
    setStatusFn(err, "bad");
    return;
  }
  if (!state.rows?.length) {
    setStatusFn("No hay filas para importar.", "bad");
    return;
  }
  const odooTarget = odooImportTargetName(state);
  const msg =
    `¿Importar estos comprobantes a ${odooTarget}? ` +
    "Se crearán facturas en borrador (con OC vinculada si hay match) y se sincronizarán OC e impuestos " +
    "(líneas y origen Odoo con la selección actual de FacturIA). " +
    "Si ya existen, se actualizan en lugar de duplicar.";
  if (!window.confirm(msg)) return;

  await flushAutoSave(state, refs, setStatusFn);
  setStatusFn(`Importando a ${odooTarget}…`);
  if (refs?.btnOdooImport) refs.btnOdooImport.disabled = true;
  try {
    const res = await fetch(
      `/api/odoo/import${buildApiQuery(apiOdooQueryParams(state))}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rows: state.rows,
          skip_duplicates: true,
          update_taxes_if_exists: true,
          ...apiContextBody(state),
        }),
      }
    );
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.detail || data?.error || `No se pudo importar a ${odooTarget}`);

    const created = data.created || [];
    const updatedTaxes = data.updated_taxes || [];
    const skipped = data.skipped || [];
    const errors = data.errors || [];

    if (data.error && !created.length) {
      throw new Error(data.error);
    }

    const parts = [];
    if (created.length) {
      const names = created.map((c) => c.name || `#${c.id}`).join(", ");
      parts.push(`Creadas: ${created.length} (${names})`);
    }
    if (updatedTaxes.length) {
      const names = updatedTaxes
        .map((u) => {
          const bits = [];
          const contentN = u.content_lines_updated ?? 0;
          if (contentN) bits.push(`${contentN} línea${contentN === 1 ? "" : "s"}`);
          const taxN = u.tax_lines_updated ?? u.lines_updated ?? 0;
          if (taxN) bits.push(`${taxN} impuesto${taxN === 1 ? "" : "s"}`);
          const poN = u.purchase_lines_updated ?? 0;
          if (poN) bits.push(`${poN} OC`);
          if (u.invoice_origin_updated) bits.push("origen OC");
          const detail = bits.length ? bits.join(", ") : "sin cambios";
          return `${u.name || u.document_number || `#${u.move_id}`} (${detail})`;
        })
        .join(", ");
      parts.push(`Actualizadas en Odoo: ${updatedTaxes.length} (${names})`);
    }
    if (skipped.length) {
      parts.push(`Omitidas (ya existían): ${skipped.length}`);
    }
    if (errors.length) {
      const e0 = errors[0];
      parts.push(`Errores: ${errors.length} — ${e0.document_number || ""}: ${e0.error || ""}`);
    }

    const kind = errors.length ? (created.length || updatedTaxes.length ? "ok" : "bad") : "ok";
    setStatusFn(parts.join(" · ") || "Importación finalizada.", kind);
  } catch (e) {
    setStatusFn(e?.message || String(e), "bad");
  } finally {
    if (refs?.btnOdooImport && state.rows?.length) refs.btnOdooImport.disabled = false;
  }
}
