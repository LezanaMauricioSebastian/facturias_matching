"""Purchase order linking and preparation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from facturia_matching.core.comprobante_tax import reconcile_fac_iva_for_import
from facturia_matching.odoo.api import odoo_execute_kw_with_config

from facturia_matching.odoo.import_._utils import (
    _content_rows_from_group,
    _floats_differ,
    _int_id,
    _line_has_content,
    _move_line_supports_purchase_link,
    _normalize,
    _parse_amount_loose,
)
from facturia_matching.odoo.import_.rows import (
    _build_line_command,
    group_rows_into_invoices,
    propagate_invoice_headers,
)


def _purchase_line_id_raw(line: Dict[str, Any]) -> Optional[int]:
    raw = line.get("purchase_line_id")
    if isinstance(raw, (list, tuple)) and raw:
        return int(raw[0])
    if isinstance(raw, int):
        return raw
    return None


def _purchase_line_id_from_row(row: Dict[str, Any]) -> Optional[int]:
    return _int_id(row.get("__oc_line_id"))


def _existing_purchase_line_ids(config: Dict[str, Any], ids: List[int]) -> set:
    if not ids:
        return set()
    found = odoo_execute_kw_with_config(
        config,
        "purchase.order.line",
        "search",
        [[("id", "in", sorted(set(ids)))]],
    )
    return {int(x) for x in (found or [])}


def sanitize_group_purchase_lines(
    config: Dict[str, Any],
    group: List[Dict[str, Any]],
) -> List[str]:
    """Quita __oc_line_id inexistentes en Odoo para evitar fallos al crear/vincular facturas."""
    warnings: List[str] = []
    ids: List[int] = []
    for row in group:
        po_line_id = _purchase_line_id_from_row(row)
        if po_line_id:
            ids.append(po_line_id)
    if not ids:
        return warnings

    existing = _existing_purchase_line_ids(config, ids)
    for row in group:
        po_line_id = _purchase_line_id_from_row(row)
        if not po_line_id or po_line_id in existing:
            continue
        line_name = _normalize(row.get("invoice_line_ids/name")) or "?"
        oc_name = _normalize(row.get("__oc_name")) or str(po_line_id)
        warnings.append(
            f"Línea {line_name}: OC {oc_name} (purchase_line_id {po_line_id}) "
            "no existe en Odoo; se importa sin vínculo OC"
        )
        row["__oc_line_id"] = ""
        row["__oc_line_name"] = ""
        row["__oc_order_id"] = ""
    return warnings


def _should_refresh_purchase_links(rows: List[Dict[str, Any]]) -> bool:
    """
    True si hace falta re-matchear OC en Odoo antes de importar.
    Omite el round-trip cuando las filas con OC ya traen __oc_line_id.
    """
    for row in rows:
        if not _line_has_content(row):
            continue
        if _purchase_line_id_from_row(row):
            continue
        if _normalize(row.get("__oc_name")) or _normalize(row.get("__selected_oc_name")):
            return True
    return False


def _refresh_purchase_links(rows: List[Dict[str, Any]]) -> List[str]:
    """
    Re-matchea OC contra Odoo inmediatamente antes de importar.
    Garantiza __oc_line_id frescos aunque el cliente envíe filas guardadas sin IDs.
    """
    from facturia_matching.odoo.purchase_matching import clear_purchase_cache, enrich_rows_with_purchase_data

    if not rows:
        return []
    clear_purchase_cache()
    summary = enrich_rows_with_purchase_data(rows)
    warnings: List[str] = []
    if not summary.get("enabled"):
        return warnings
    matched = int(summary.get("rows_matched") or 0)
    total = int(summary.get("rows_total") or 0)
    if total and matched < total:
        warnings.append(f"OC: solo {matched}/{total} líneas tienen purchase_line_id para Odoo")
    return warnings


def _dedupe_group_oc_line_ids(group: List[Dict[str, Any]]) -> List[str]:
    """Odoo no permite dos líneas de factura con el mismo purchase_line_id."""
    warnings: List[str] = []
    seen: set = set()
    for row in group:
        if not _line_has_content(row):
            continue
        po_id = _purchase_line_id_from_row(row)
        if not po_id:
            continue
        if po_id in seen:
            line_name = _normalize(row.get("invoice_line_ids/name")) or "?"
            row["__oc_line_id"] = ""
            warnings.append(
                f"Línea {line_name}: línea OC {po_id} ya usada en otra fila; se importa sin vínculo"
            )
        else:
            seen.add(po_id)
    return warnings


def _prepare_rows_for_import(
    config: Dict[str, Any],
    rows: List[Dict[str, Any]],
) -> Tuple[List[List[Dict[str, Any]]], List[str]]:
    """
    Prepara filas para import a Odoo: refresca vínculos OC, agrupa comprobantes,
    reconcilia IVA y sanitiza purchase_line_id inexistentes.
    """
    warnings: List[str] = []
    purchase_ok = _move_line_supports_purchase_link(config)
    if purchase_ok and _should_refresh_purchase_links(rows):
        warnings.extend(_refresh_purchase_links(rows))

    groups = [propagate_invoice_headers(g) for g in group_rows_into_invoices(rows)]

    for group in groups:
        reconcile_fac_iva_for_import(group)

    if not purchase_ok:
        return groups, warnings

    sanitized_any = False
    for group in groups:
        group_warnings = sanitize_group_purchase_lines(config, group)
        if group_warnings:
            sanitized_any = True
            warnings.extend(group_warnings)

    if sanitized_any:
        warnings.extend(_refresh_purchase_links(rows))
        groups = [propagate_invoice_headers(g) for g in group_rows_into_invoices(rows)]

    for group in groups:
        warnings.extend(_dedupe_group_oc_line_ids(group))

    return groups, warnings


def plan_purchase_line_updates(
    product_lines: List[Dict[str, Any]],
    content_rows: List[Dict[str, Any]],
    *,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Planifica purchase_line_id en líneas de producto (empareja por orden con filas UI).
    Permite actualizar o quitar el vínculo OC si cambió la selección en FacturIA.
    """
    from facturia_matching.odoo.import_._utils import _content_rows_from_group

    if config is not None and not _move_line_supports_purchase_link(config):
        return [], []

    updates: List[Dict[str, Any]] = []
    warnings: List[str] = []
    rows = _content_rows_from_group(content_rows)
    if not product_lines:
        warnings.append("La factura no tiene líneas de producto")
        return updates, warnings
    if not rows:
        warnings.append("No hay filas con contenido para vincular OC")
        return updates, warnings

    n = min(len(product_lines), len(rows))
    if len(product_lines) != len(rows):
        warnings.append(
            f"OC: líneas Odoo ({len(product_lines)}) vs filas UI ({len(rows)}): "
            f"se actualizan las primeras {n} por orden"
        )

    for i in range(n):
        line = product_lines[i]
        row = rows[i]
        expected = _purchase_line_id_from_row(row)
        current = _purchase_line_id_raw(line)
        if expected == current:
            continue
        if not expected:
            # No intentar purchase_line_id=False: Odoo puede fallar con FK en líneas enlazadas.
            continue
        updates.append(
            {
                "line_id": line["id"],
                "line_name": line.get("name"),
                "row_index": i,
                "old_purchase_line_id": current,
                "new_purchase_line_id": expected,
            }
        )
    return updates, warnings


def _truthy_flag(raw: Any) -> bool:
    if raw is True:
        return True
    if isinstance(raw, (int, float)) and int(raw) == 1:
        return True
    s = str(raw or "").strip().lower()
    return s in ("1", "true", "yes", "si", "sí", "on")


def group_wants_overwrite_oc_price(group: List[Dict[str, Any]]) -> bool:
    """True si el comprobante pidió sobreescribir price_unit en la OC."""
    for row in group or []:
        if _truthy_flag(row.get("__overwrite_oc_price")):
            return True
    return False


def apply_purchase_order_price_overwrites(
    config: Dict[str, Any],
    group: List[Dict[str, Any]],
    *,
    tolerance: float = 0.001,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Si hay __overwrite_oc_price, escribe el precio de la factura en purchase.order.line.
    No toca account.move — solo la OC original en Odoo.
    """
    updates: List[Dict[str, Any]] = []
    warnings: List[str] = []
    if not group_wants_overwrite_oc_price(group):
        return updates, warnings
    if not _move_line_supports_purchase_link(config):
        return updates, warnings

    rows = _content_rows_from_group(group)
    wanted: Dict[int, float] = {}
    for row in rows:
        po_line_id = _purchase_line_id_from_row(row)
        if not po_line_id:
            continue
        _cmd, _zero, expected = _build_line_command(
            row,
            group,
            include_purchase_link=False,
            include_product_id=False,
        )
        wanted[int(po_line_id)] = float(expected["price_unit"])

    if not wanted:
        warnings.append(
            "Sobreescribir precio OC: no hay líneas con vínculo OC; no se modificó la orden"
        )
        return updates, warnings

    ids = sorted(wanted.keys())
    try:
        current_rows = odoo_execute_kw_with_config(
            config,
            "purchase.order.line",
            "search_read",
            [[("id", "in", ids)]],
            {"fields": ["id", "price_unit", "name"]},
        ) or []
    except Exception as exc:  # noqa: BLE001 — RPC Odoo
        warnings.append(f"Sobreescribir precio OC: no se pudo leer líneas PO ({exc})")
        return updates, warnings

    current_by_id = {int(r["id"]): r for r in current_rows if r.get("id") is not None}
    for po_line_id, new_price in wanted.items():
        cur = current_by_id.get(po_line_id)
        if not cur:
            warnings.append(
                f"Sobreescribir precio OC: línea PO {po_line_id} no existe; se omite"
            )
            continue
        old_price = _parse_amount_loose(cur.get("price_unit")) or 0.0
        if not _floats_differ(old_price, new_price, tolerance):
            continue
        try:
            odoo_execute_kw_with_config(
                config,
                "purchase.order.line",
                "write",
                [[po_line_id], {"price_unit": new_price}],
            )
            updates.append(
                {
                    "po_line_id": po_line_id,
                    "line_name": cur.get("name"),
                    "old_price_unit": old_price,
                    "new_price_unit": new_price,
                }
            )
        except Exception as exc:  # noqa: BLE001 — RPC Odoo
            warnings.append(
                f"Sobreescribir precio OC línea {po_line_id} "
                f"({cur.get('name') or '?'}): {exc}"
            )
    return updates, warnings
