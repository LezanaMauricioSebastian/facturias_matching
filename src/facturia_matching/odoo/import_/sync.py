"""Sync existing Odoo moves with UI row groups."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from facturia_matching.odoo.api import odoo_execute_kw_with_config

from facturia_matching.odoo.import_._utils import (
    _content_rows_from_group,
    _move_line_supports_purchase_link,
    _normalize,
)
from facturia_matching.odoo.import_.move_lines import (
    _batch_write_move_lines,
    _batch_write_move_lines_with_fallback,
    _get_move_product_lines,
)
from facturia_matching.odoo.import_.planning import (
    _po_link_write_vals,
    plan_invoice_origin_update,
    plan_line_tax_updates,
    plan_move_header_updates,
    plan_product_line_content_updates,
    plan_product_price_quantity_reapply,
)
from facturia_matching.odoo.import_.purchase import (
    apply_purchase_order_price_overwrites,
    plan_purchase_line_updates,
)
from facturia_matching.odoo.import_.rows import _invoice_due_date_from_group
from facturia_matching.odoo.import_.taxes import (
    _apply_tax_line_amount_overwrites,
    _ensure_move_line_maturity,
)


def sync_move_taxes_from_group(
    config: Dict[str, Any],
    move_id: int,
    group: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Sincroniza una factura ya creada en Odoo (borrador) con las filas UI:

    1. invoice_origin del encabezado.
    2. product_id, cantidad, precio, etiqueta y cuenta en líneas de producto.
    3. tax_ids en líneas de producto.
    4. Vínculos OC (purchase_line_id + product_id).
    5. Re-aplicar price_unit / quantity / product_uom_id (Odoo puede pisar precio/UM al vincular OC).
    6. Montos en líneas display_type=tax — último paso (IVA / IIBB del pie de FacturIA).
    """
    move_rows = odoo_execute_kw_with_config(
        config,
        "account.move",
        "read",
        [[move_id]],
        {
            "fields": [
                "id",
                "name",
                "state",
                "l10n_latam_document_number",
                "invoice_origin",
                "invoice_date",
                "invoice_date_due",
            ]
        },
    )
    if not move_rows:
        raise ValueError(f"Factura {move_id} no encontrada")
    move = move_rows[0]
    state = _normalize(move.get("state"))
    if state and state != "draft":
        raise ValueError(
            f"Factura {move.get('name') or move_id} no está en borrador (state={state})"
        )

    warnings: List[str] = []
    # sanitize + refresh ya corrieron en _prepare_rows_for_import; no repetir aquí.

    header_plan = plan_move_header_updates(move, group)
    header_update: Optional[Dict[str, Any]] = None
    due_date_iso = _invoice_due_date_from_group(group)
    origin_plan = plan_invoice_origin_update(move.get("invoice_origin"), group)
    invoice_origin_update: Optional[Dict[str, Any]] = None
    header_write_vals: Dict[str, Any] = {}
    if header_plan:
        header_write_vals.update(header_plan)
    if origin_plan:
        origin_vals: Dict[str, Any] = (
            {"invoice_origin": origin_plan["new_invoice_origin"]}
            if origin_plan["new_invoice_origin"]
            else {"invoice_origin": False}
        )
        header_write_vals.update(origin_vals)
        invoice_origin_update = {**origin_plan, "write_vals": origin_vals}
    if header_write_vals:
        odoo_execute_kw_with_config(
            config,
            "account.move",
            "write",
            [[move_id], header_write_vals],
        )
        header_update = dict(header_plan or {})
        move = {**move, **header_write_vals}
        due_date_iso = header_write_vals.get("invoice_date_due") or due_date_iso

    if due_date_iso:
        _ensure_move_line_maturity(config, move_id, due_date_iso)

    product_lines = _get_move_product_lines(config, move_id)

    planned_content, warnings_content = plan_product_line_content_updates(product_lines, group)
    warnings.extend(warnings_content)
    content_line_updates: List[Dict[str, Any]] = list(planned_content)

    planned_ids, warnings_ids = plan_line_tax_updates(product_lines, group)
    warnings.extend(warnings_ids)
    product_updates: List[Dict[str, Any]] = list(planned_ids)

    merged_line_writes: Dict[int, Dict[str, Any]] = {}
    for item in planned_content:
        lid = int(item["line_id"])
        bucket = merged_line_writes.setdefault(
            lid,
            {
                "line_id": lid,
                "line_name": item.get("line_name"),
                "write_vals": {},
            },
        )
        bucket["write_vals"].update(item["write_vals"])
    for item in planned_ids:
        lid = int(item["line_id"])
        bucket = merged_line_writes.setdefault(
            lid,
            {
                "line_id": lid,
                "line_name": item.get("line_name"),
                "write_vals": {},
            },
        )
        bucket["write_vals"]["tax_ids"] = [(6, 0, item["new_tax_ids"])]
    line_batch = list(merged_line_writes.values())
    if line_batch:
        _batch_write_move_lines(config, move_id, line_batch, warnings, context="contenido")
        product_lines = _get_move_product_lines(config, move_id)

    if due_date_iso:
        maturity_fixed = _ensure_move_line_maturity(config, move_id, due_date_iso)
        if maturity_fixed:
            warnings.append(
                f"Se completó fecha límite en {maturity_fixed} apunte(s) contable(s)"
            )

    ui_rows = _content_rows_from_group(group)
    purchase_line_updates: List[Dict[str, Any]] = []
    if _move_line_supports_purchase_link(config):
        planned_po, warnings_po = plan_purchase_line_updates(
            product_lines, group, config=config
        )
        warnings.extend(warnings_po)
        po_batch: List[Dict[str, Any]] = []
        used_po_line_ids: set = set()
        for item in planned_po:
            po_line_id = item["new_purchase_line_id"]
            if not po_line_id or po_line_id in used_po_line_ids:
                if po_line_id in used_po_line_ids:
                    warnings.append(
                        f"OC línea {po_line_id} duplicada; se omite en {item.get('line_name') or '?'}"
                    )
                continue
            row_idx = int(item.get("row_index", 0))
            ui_row = ui_rows[row_idx] if row_idx < len(ui_rows) else {}
            write_vals = _po_link_write_vals(ui_row, int(po_line_id), group=group)
            po_batch.append(
                {
                    "line_id": item["line_id"],
                    "line_name": item.get("line_name"),
                    "write_vals": write_vals,
                }
            )
            used_po_line_ids.add(int(po_line_id))
        purchase_line_updates = _batch_write_move_lines_with_fallback(
            config,
            move_id,
            po_batch,
            warnings,
            context="OC",
        )
        if purchase_line_updates:
            product_lines = _get_move_product_lines(config, move_id)

    price_qty_reapply_updates: List[Dict[str, Any]] = []
    if _move_line_supports_purchase_link(config):
        # Siempre necesitamos leer product_lines para plan_product_price_quantity_reapply
        # aunque ya se haya leído antes (el costo es menor que el riesgo de NameError)
        product_lines = _get_move_product_lines(config, move_id)
        planned_reapply, warnings_reapply = plan_product_price_quantity_reapply(
            product_lines, group
        )
        warnings.extend(warnings_reapply)
        if planned_reapply:
            price_qty_reapply_updates = _batch_write_move_lines(
                config, move_id, planned_reapply, warnings, context="precio"
            )

    po_price_overwrite_updates: List[Dict[str, Any]] = []
    if _move_line_supports_purchase_link(config):
        po_price_overwrite_updates, warnings_po_price = apply_purchase_order_price_overwrites(
            config, group
        )
        warnings.extend(warnings_po_price)

    # Último paso: pisar montos IVA / IIBB tras cualquier recálculo de Odoo (OC, precio, tax_ids).
    tax_line_updates, warnings_amt, expected_amounts = _apply_tax_line_amount_overwrites(
        config,
        move_id,
        group,
        due_date_iso=due_date_iso,
    )
    warnings.extend(warnings_amt)

    return {
        "move_id": move_id,
        "name": move.get("name"),
        "document_number": move.get("l10n_latam_document_number"),
        "state": move.get("state"),
        "product_lines_updated": len(product_updates),
        "content_lines_updated": len(content_line_updates),
        "purchase_lines_updated": len(purchase_line_updates),
        "price_qty_reapply_updates": price_qty_reapply_updates,
        "po_price_overwrite_updates": po_price_overwrite_updates,
        "tax_lines_updated": len(tax_line_updates),
        "lines_updated": len(tax_line_updates),
        "product_updates": product_updates,
        "content_line_updates": content_line_updates,
        "purchase_line_updates": purchase_line_updates,
        "invoice_origin_updated": invoice_origin_update is not None,
        "invoice_origin_update": invoice_origin_update,
        "tax_line_updates": tax_line_updates,
        "expected_tax_amounts": expected_amounts,
        "warnings": warnings,
    }


def update_move_taxes_from_group(
    config: Dict[str, Any],
    move_id: int,
    group: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Alias retrocompatible → sync_move_taxes_from_group."""
    return sync_move_taxes_from_group(config, move_id, group)
