"""Row grouping, validation, and line command building."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from facturia_matching.odoo.import_._utils import (
    _date_ddmm_to_iso,
    _int_id,
    _line_has_content,
    _normalize,
    _parse_amount_loose,
)
from facturia_matching.odoo.import_.taxes import _tax_ids_for_odoo_line


def _invoice_group_key(row: Dict[str, Any], row_index: int) -> str:
    idx = row.get("__comprobante_idx")
    if idx is not None:
        return f"idx:{idx}"
    doc = _normalize(row.get("l10n_latam_document_number"))
    if doc:
        return f"doc:{doc}"
    return f"row:{row_index}"


def group_rows_into_invoices(rows: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Agrupa filas por comprobante (__comprobante_idx o número de documento)."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        key = _invoice_group_key(row, i)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(dict(row))
    return [groups[k] for k in order]


def propagate_invoice_headers(group: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Copia encabezado del comprobante a líneas siguientes (misma lógica que CSV)."""
    if not group:
        return []
    out = [dict(group[0])]
    header_keys = (
        "l10n_latam_document_number",
        "partner_id",
        "l10n_latam_document_type_id",
        "invoice_date",
        "invoice_date_due",
        "x_studio_category",
        "journal_id",
        "invoice_line_ids/account_id",
    )
    for r in group[1:]:
        cur = dict(r)
        for k in header_keys:
            if not _normalize(cur.get(k)) and _normalize(out[0].get(k)):
                cur[k] = out[0][k]
        out.append(cur)
    return out


def validate_rows_for_import(rows: List[Dict[str, Any]]) -> Optional[str]:
    if not rows:
        return "No hay filas para importar."
    groups = [propagate_invoice_headers(g) for g in group_rows_into_invoices(rows)]
    for gi, group in enumerate(groups):
        header = group[0]
        label = _normalize(header.get("l10n_latam_document_number")) or f"comprobante {gi + 1}"
        if not _int_id(header.get("partner_id")):
            return f"{label}: falta proveedor (partner_id)."
        if not _int_id(header.get("journal_id")):
            return f"{label}: falta diario (journal_id)."
        if not _normalize(header.get("l10n_latam_document_number")):
            return f"Comprobante {gi + 1}: falta número de documento."
        if not _date_ddmm_to_iso(header.get("invoice_date")):
            return f"{label}: fecha de factura inválida o vacía."
        lines = [r for r in group if _line_has_content(r)]
        if not lines:
            return f"{label}: no hay líneas con descripción o importe."
        for li, line in enumerate(lines):
            if not _int_id(line.get("invoice_line_ids/account_id")):
                return f"{label}, línea {li + 1}: falta cuenta contable."
    return None


def _invoice_origin_from_group(group: List[Dict[str, Any]]) -> str:
    """Nombre(s) de OC para invoice_origin (vínculo visible en el encabezado Odoo)."""
    for row in group:
        selected = _normalize(row.get("__selected_oc_name"))
        if selected:
            return selected
    names: List[str] = []
    seen: set = set()
    for row in group:
        if not _line_has_content(row):
            continue
        name = _normalize(row.get("__oc_name"))
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return ", ".join(names)


def _build_line_command(
    row: Dict[str, Any],
    group: Optional[List[Dict[str, Any]]] = None,
    *,
    include_purchase_link: bool = True,
    include_product_id: bool = True,
) -> Tuple[int, int, Dict[str, Any]]:
    qty = _parse_amount_loose(row.get("invoice_line_ids/quantity"))
    if qty is None or qty <= 0:
        qty = 1.0
    price = _parse_amount_loose(row.get("invoice_line_ids/price_unit"))
    if price is None:
        price = 0.0
    vals: Dict[str, Any] = {
        "name": _normalize(row.get("invoice_line_ids/name")) or "Línea importada",
        "quantity": qty,
        "price_unit": price,
    }
    account_id = _int_id(row.get("invoice_line_ids/account_id"))
    if account_id:
        vals["account_id"] = account_id
    product_id = _int_id(row.get("invoice_line_ids/product_id"))
    if include_product_id and product_id:
        vals["product_id"] = product_id
    po_line_id = _int_id(row.get("__oc_line_id"))
    if include_purchase_link and po_line_id:
        vals["purchase_line_id"] = po_line_id
    tax_ids = _tax_ids_for_odoo_line(row, group)
    vals["tax_ids"] = [(6, 0, tax_ids)]
    return (0, 0, vals)


def _invoice_due_date_from_group(group: List[Dict[str, Any]]) -> Optional[str]:
    """Fecha de vencimiento del comprobante; si falta, usa la fecha de factura."""
    header = group[0] if group else {}
    due = _date_ddmm_to_iso(header.get("invoice_date_due"))
    if due:
        return due
    return _date_ddmm_to_iso(header.get("invoice_date"))
