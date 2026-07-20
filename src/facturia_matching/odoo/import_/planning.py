"""Plan updates to Odoo move headers and product lines."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from facturia_matching.odoo.import_._utils import (
    _content_rows_from_group,
    _date_ddmm_to_iso,
    _floats_differ,
    _int_id,
    _m2o_id,
    _normalize,
    _parse_amount_loose,
)
from facturia_matching.odoo.import_.purchase import (
    _purchase_line_id_from_row,
    _purchase_line_id_raw,
)
from facturia_matching.odoo.import_.rows import (
    _build_line_command,
    _invoice_due_date_from_group,
    _invoice_origin_from_group,
)
from facturia_matching.odoo.import_.taxes import _tax_ids_for_odoo_line


def plan_invoice_origin_update(
    current: Any,
    group: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Planifica invoice_origin del encabezado si difiere de la OC en filas UI."""
    expected = _invoice_origin_from_group(group)
    current_norm = _normalize(current)
    if expected == current_norm:
        return None
    return {
        "old_invoice_origin": current_norm,
        "new_invoice_origin": expected,
    }


def plan_move_header_updates(
    move: Dict[str, Any],
    group: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Planifica invoice_date / invoice_date_due del encabezado (requerido por Odoo en AP)."""
    if not group:
        return None
    header = group[0]
    vals: Dict[str, Any] = {}
    inv_date = _date_ddmm_to_iso(header.get("invoice_date"))
    if inv_date and _normalize(move.get("invoice_date")) != inv_date:
        vals["invoice_date"] = inv_date
    due = _invoice_due_date_from_group(group)
    if due and _normalize(move.get("invoice_date_due")) != due:
        vals["invoice_date_due"] = due
    return vals or None


def plan_line_tax_updates(
    product_lines: List[Dict[str, Any]],
    content_rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Planifica tax_ids en líneas de producto (paso 1 antes de pisar montos en líneas tax).
    Empareja por orden (sequence/id en Odoo ↔ filas UI del comprobante).
    """
    updates: List[Dict[str, Any]] = []
    warnings: List[str] = []
    rows = _content_rows_from_group(content_rows)
    if not product_lines:
        warnings.append("La factura no tiene líneas de producto")
        return updates, warnings
    if not rows:
        warnings.append("No hay filas con contenido para aplicar impuestos")
        return updates, warnings

    n = min(len(product_lines), len(rows))
    if len(product_lines) != len(rows):
        warnings.append(
            f"Líneas Odoo ({len(product_lines)}) vs filas UI ({len(rows)}): "
            f"se actualizan las primeras {n} por orden"
        )

    for i in range(n):
        line = product_lines[i]
        row = rows[i]
        tax_ids = _tax_ids_for_odoo_line(row, content_rows)
        old_tax_ids = line.get("tax_ids") or []
        if sorted(old_tax_ids) == sorted(tax_ids):
            continue
        updates.append(
            {
                "line_id": line["id"],
                "line_name": line.get("name"),
                "old_tax_ids": old_tax_ids,
                "new_tax_ids": tax_ids,
            }
        )
    return updates, warnings


def plan_product_line_content_updates(
    product_lines: List[Dict[str, Any]],
    content_rows: List[Dict[str, Any]],
    *,
    tolerance: float = 0.001,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Planifica product_id, quantity, price_unit, product_uom_id, name y account_id en líneas de producto.
    Empareja por orden (sequence/id en Odoo ↔ filas UI del comprobante).
    """
    updates: List[Dict[str, Any]] = []
    warnings: List[str] = []
    rows = _content_rows_from_group(content_rows)
    if not product_lines:
        warnings.append("La factura no tiene líneas de producto")
        return updates, warnings
    if not rows:
        warnings.append("No hay filas con contenido para actualizar líneas de producto")
        return updates, warnings

    n = min(len(product_lines), len(rows))
    if len(product_lines) != len(rows):
        warnings.append(
            f"Líneas Odoo ({len(product_lines)}) vs filas UI ({len(rows)}): "
            f"se actualizan producto/cantidad/precio en las primeras {n} por orden"
        )

    for i in range(n):
        line = product_lines[i]
        row = rows[i]
        defer_product = bool(_purchase_line_id_from_row(row))
        _cmd, _zero, expected = _build_line_command(
            row,
            content_rows,
            include_purchase_link=False,
            include_product_id=not defer_product,
        )
        write_vals: Dict[str, Any] = {}

        exp_qty = float(expected["quantity"])
        cur_qty = _parse_amount_loose(line.get("quantity")) or 0.0
        if _floats_differ(cur_qty, exp_qty, tolerance):
            write_vals["quantity"] = exp_qty

        exp_price = float(expected["price_unit"])
        cur_price = _parse_amount_loose(line.get("price_unit")) or 0.0
        if _floats_differ(cur_price, exp_price, tolerance):
            write_vals["price_unit"] = exp_price

        exp_name = _normalize(expected.get("name"))
        cur_name = _normalize(line.get("name"))
        if exp_name and exp_name != cur_name:
            write_vals["name"] = exp_name

        exp_account = expected.get("account_id")
        cur_account = _m2o_id(line.get("account_id"))
        if exp_account and exp_account != cur_account:
            write_vals["account_id"] = exp_account

        exp_product = expected.get("product_id")
        cur_product = _m2o_id(line.get("product_id"))
        if not defer_product and exp_product is not None and exp_product != cur_product:
            write_vals["product_id"] = exp_product

        # UM matcheada: solo si el producto va en este write o ya está en la línea
        # (con OC, producto y UM se escriben juntos en _po_link_write_vals).
        if not defer_product:
            exp_uom = _row_matched_uom_id(row)
            cur_uom = _m2o_id(line.get("product_uom_id"))
            if exp_uom is not None and exp_uom != cur_uom:
                write_vals["product_uom_id"] = exp_uom

        if not write_vals:
            continue
        updates.append(
            {
                "line_id": line["id"],
                "line_name": line.get("name"),
                "write_vals": write_vals,
            }
        )
    return updates, warnings


def _row_matched_uom_id(row: Dict[str, Any]) -> Optional[int]:
    """UM matcheada solo si la fila conserva su producto (evita UM huérfana de otra categoría)."""
    if not _int_id(row.get("invoice_line_ids/product_id")):
        return None
    return _int_id(row.get("__um_empresa_id"))


def _pair_product_line_for_row(
    product_lines: List[Dict[str, Any]],
    row: Dict[str, Any],
    fallback_index: int,
) -> Optional[Dict[str, Any]]:
    """Empareja fila UI con línea Odoo por purchase_line_id o por orden."""
    po_id = _purchase_line_id_from_row(row)
    if po_id:
        for line in product_lines:
            if _purchase_line_id_raw(line) == po_id:
                return line
    if 0 <= fallback_index < len(product_lines):
        return product_lines[fallback_index]
    return None


def plan_product_price_quantity_reapply(
    product_lines: List[Dict[str, Any]],
    content_rows: List[Dict[str, Any]],
    *,
    tolerance: float = 0.001,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Re-aplica price_unit, quantity y product_uom_id desde filas UI al final del sync.
    Odoo puede resetear precios/UM al vincular OC, asignar product_id o recalcular impuestos.
    """
    updates: List[Dict[str, Any]] = []
    warnings: List[str] = []
    rows = _content_rows_from_group(content_rows)
    if not product_lines or not rows:
        return updates, warnings

    if len(product_lines) != len(rows):
        warnings.append(
            f"Líneas Odoo ({len(product_lines)}) vs filas UI ({len(rows)}): "
            f"se re-aplica precio/cantidad/UM emparejando por OC o por orden"
        )

    used_line_ids: set = set()
    for i, row in enumerate(rows):
        line = _pair_product_line_for_row(product_lines, row, i)
        if not line or line["id"] in used_line_ids:
            if line:
                warnings.append(
                    f"Línea UI {i + 1} ({row.get('invoice_line_ids/name') or '?'}): "
                    "duplicada o sin par en Odoo; se omite re-aplicar precio"
                )
            continue
        used_line_ids.add(line["id"])
        _cmd, _zero, expected = _build_line_command(
            row,
            content_rows,
            include_purchase_link=False,
            include_product_id=False,
        )
        write_vals: Dict[str, Any] = {}

        exp_qty = float(expected["quantity"])
        cur_qty = _parse_amount_loose(line.get("quantity")) or 0.0
        if _floats_differ(cur_qty, exp_qty, tolerance):
            write_vals["quantity"] = exp_qty

        exp_price = float(expected["price_unit"])
        cur_price = _parse_amount_loose(line.get("price_unit")) or 0.0
        if _floats_differ(cur_price, exp_price, tolerance):
            write_vals["price_unit"] = exp_price

        exp_uom = _row_matched_uom_id(row)
        cur_uom = _m2o_id(line.get("product_uom_id"))
        if exp_uom is not None and exp_uom != cur_uom:
            write_vals["product_uom_id"] = exp_uom

        if not write_vals:
            continue
        updates.append(
            {
                "line_id": line["id"],
                "line_name": line.get("name"),
                "write_vals": write_vals,
                "row_index": i,
            }
        )
    return updates, warnings


def _po_link_write_vals(
    row: Dict[str, Any],
    po_line_id: int,
    *,
    group: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Vincula OC, producto, precio, cantidad y UM UI en un solo write."""
    _cmd, _zero, expected = _build_line_command(
        row,
        group,
        include_purchase_link=False,
        include_product_id=False,
    )
    write_vals: Dict[str, Any] = {
        "purchase_line_id": po_line_id,
        "price_unit": expected["price_unit"],
        "quantity": expected["quantity"],
    }
    product_id = _int_id(row.get("invoice_line_ids/product_id"))
    if product_id:
        write_vals["product_id"] = product_id
        product_uom_id = _int_id(row.get("__um_empresa_id"))
        if product_uom_id:
            write_vals["product_uom_id"] = product_uom_id
    return write_vals
