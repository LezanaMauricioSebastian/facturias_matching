"""Orquestación: match por fila, enrich, select-oc, rematch."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from facturia_matching.odoo.purchase_matching._util import (
    _is_content_row,
    _normalize,
    _normalize_key,
    _parse_amount,
    _pkg,
)
from facturia_matching.odoo.purchase_matching.oc import (
    _min_match_score,
    _po_cache,
    score_oc_candidates,
)
from facturia_matching.odoo.purchase_matching.scoring import (
    _matchable_po_lines,
)
from facturia_matching.odoo.purchase_matching.uom import (
    _apply_uom_scaling,
    _apply_uom_scaling_for_product,
    _compose_match_note,
    _product_uom_cache,
    _resolve_invoice_qty_um,
    _uom_cache,
    _uom_model_relative_cache,
)

def _empty_purchase_fields() -> Dict[str, str]:
    return {
        "__oc_name": "",
        "__oc_partner_ref": "",
        "__oc_line_name": "",
        "__oc_match_score": "",
        "__oc_match_note": "",
        "__qty_pedido": "",
        "__qty_recibido": "",
        "__qty_facturado_po": "",
        "__um_proveedor": "",
        "__um_empresa": "",
        "__um_empresa_id": "",
        "__qty_original": "",
        "__qty_escalada": "",
        "__um_factor": "",
        "__um_note": "",
        "__oc_order_id": "",
        "__oc_line_id": "",
        "__selected_oc_order_id": "",
        "__selected_oc_name": "",
        "__product_suggested": "",
        "__overwrite_oc_price": "",
    }


# Campos UM (+ qty visible) que el operador puede haber fijado a mano y que
# `_match_comprobante_rows` no debe pisar al rematchear en reload de conversión.
_SAVED_UOM_KEYS = (
    "__um_proveedor",
    "__um_empresa",
    "__um_empresa_id",
    "__qty_original",
    "__qty_escalada",
    "__um_factor",
    "__um_note",
    "invoice_line_ids/quantity",
)


def _snapshot_saved_uom(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Snapshot de UM guardada si la fila ya tiene `__um_empresa_id` (autosave)."""
    if not isinstance(row, dict):
        return None
    if not _normalize(row.get("__um_empresa_id")):
        return None
    return {k: row.get(k, "") for k in _SAVED_UOM_KEYS}


def _restore_saved_uom(
    row: Dict[str, Any],
    saved_uom: Optional[Dict[str, Any]],
    saved_product_id: str,
) -> None:
    """Restaura UM/qty elegida si el producto de la fila no cambió tras el rematch."""
    if not saved_uom or not isinstance(row, dict):
        return
    if _normalize(row.get("invoice_line_ids/product_id")) != _normalize(saved_product_id):
        return
    if not _normalize(saved_product_id):
        return
    for key, value in saved_uom.items():
        row[key] = value


def _group_rows_by_comprobante(rows: List[Dict[str, Any]]) -> Dict[Any, List[Dict[str, Any]]]:
    groups: Dict[Any, List[Dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        groups.setdefault(row.get("__comprobante_idx"), []).append(row)
    return groups


def _saved_oc_order_id(comprobante_rows: List[Dict[str, Any]]) -> Optional[int]:
    for row in comprobante_rows:
        raw = _normalize(row.get("__selected_oc_order_id"))
        if raw.isdigit():
            return int(raw)
    return None


def _set_comprobante_oc_selection(
    comprobante_rows: List[Dict[str, Any]],
    order_id: Optional[int],
    order_name: str = "",
) -> None:
    oid = str(order_id) if order_id else ""
    for row in comprobante_rows:
        row["__selected_oc_order_id"] = oid
        row["__selected_oc_name"] = order_name or ""


def _resolve_selected_oc(
    candidates: List[Dict[str, Any]],
    saved_order_id: Optional[int],
) -> Tuple[Optional[int], str]:
    if saved_order_id:
        for c in candidates:
            if int(c["order_id"]) == saved_order_id:
                return saved_order_id, c.get("order_name") or ""
        # OC guardada inválida (otro tenant / PO borrada): usar mejor candidata actual.
    if candidates:
        top = candidates[0]
        return int(top["order_id"]), top.get("order_name") or ""
    return None, ""


def _match_comprobante_rows(
    comprobante_rows: List[Dict[str, Any]],
    po_lines: List[Dict[str, Any]],
    uom_catalog: Dict[str, Dict[str, Any]],
    selected_order_id: Optional[int],
    *,
    product_memory: Optional[Dict[Tuple[int, str], Any]] = None,
) -> int:
    """Matchea líneas del comprobante contra la OC elegida. Devuelve filas matcheadas."""
    scoped = (
        [p for p in po_lines if int(p.get("order_id") or 0) == selected_order_id]
        if selected_order_id
        else []
    )
    matched = 0
    used_po_line_ids: set = set()
    partner_raw = ""
    for row in comprobante_rows:
        pid = _normalize(row.get("partner_id"))
        if pid:
            partner_raw = pid
            break
    for row in comprobante_rows:
        saved_sel = {
            "__selected_oc_order_id": row.get("__selected_oc_order_id", ""),
            "__selected_oc_name": row.get("__selected_oc_name", ""),
        }
        # Conservar UM elegida a mano / ya guardada y el tilde de precio OC:
        # `_empty_purchase_fields` los limpia y el rematch volvería al uom_po default.
        saved_product_id = _normalize(row.get("invoice_line_ids/product_id"))
        saved_uom = _snapshot_saved_uom(row)
        saved_overwrite = row.get("__overwrite_oc_price", "")
        if not _is_content_row(row):
            row.update(_empty_purchase_fields())
            row.update(saved_sel)
            if saved_overwrite:
                row["__overwrite_oc_price"] = saved_overwrite
            continue
        row.update(_empty_purchase_fields())
        row.update(saved_sel)
        # Restaurar UM guardada antes del match para no re-escalar qty ni perder target.
        if saved_uom:
            for key in (
                "__um_empresa",
                "__um_empresa_id",
                "__um_proveedor",
                "__qty_original",
                "__qty_escalada",
                "__um_factor",
                "__um_note",
            ):
                if key in saved_uom:
                    row[key] = saved_uom[key]
        learned_id: Optional[int] = None
        learned_uom_id: Optional[int] = None
        if product_memory and partner_raw.isdigit():
            from facturia_matching.persistence.product_label_memory import lookup_in_index

            learned = lookup_in_index(
                product_memory,
                partner_raw,
                row.get("invoice_line_ids/name") or row.get("Nombre de producto"),
            )
            if learned is not None:
                learned_id = int(learned.product_id)
                learned_uom_id = learned.uom_id
        match_fields = match_invoice_row(
            row,
            scoped,
            uom_catalog,
            suggest_pool=po_lines,
            learned_product_id=learned_id,
            learned_uom_id=learned_uom_id,
        )
        po_line_raw = match_fields.get("__oc_line_id")
        if po_line_raw and str(po_line_raw).isdigit():
            po_line_int = int(po_line_raw)
            if po_line_int in used_po_line_ids:
                # Misma línea OC ya tomada (p.ej. 3× CAR-CARNE MOLIDA): reintentar
                # contra las líneas OC *libres* de la misma OC — no tirar el vínculo
                # si hay otra línea del mismo product_id disponible.
                remaining = [
                    p
                    for p in scoped
                    if int(p.get("line_id") or 0) not in used_po_line_ids
                ]
                match_fields = match_invoice_row(
                    row,
                    remaining,
                    uom_catalog,
                    suggest_pool=po_lines,
                    learned_product_id=learned_id,
                    learned_uom_id=learned_uom_id,
                )
                retry_raw = match_fields.get("__oc_line_id")
                if retry_raw and str(retry_raw).isdigit():
                    retry_id = int(retry_raw)
                    if retry_id not in used_po_line_ids:
                        used_po_line_ids.add(retry_id)
                    else:
                        for oc_key in (
                            "__oc_line_id",
                            "__oc_name",
                            "__oc_partner_ref",
                            "__oc_line_name",
                            "__oc_match_score",
                            "__qty_pedido",
                            "__qty_recibido",
                            "__qty_facturado_po",
                        ):
                            match_fields[oc_key] = ""
                        match_fields["__oc_match_note"] = _compose_match_note(
                            match_fields.get("__oc_match_note") or "",
                            "Línea OC ya asignada a otra fila",
                        )
                else:
                    match_fields["__oc_match_note"] = _compose_match_note(
                        match_fields.get("__oc_match_note") or "",
                        "Línea OC ya asignada a otra fila",
                    )
            else:
                used_po_line_ids.add(po_line_int)
        # OC vinculada pero sin product_id en la PO: igual sugerir desde memoria.
        product_raw = _normalize(row.get("invoice_line_ids/product_id"))
        if (
            not product_raw.isdigit()
            and learned_id
            and not str(match_fields.get("__product_suggested") or "").strip()
        ):
            row["invoice_line_ids/product_id"] = str(int(learned_id))
            match_fields["__product_suggested"] = "memory"
            match_fields["__oc_match_note"] = _compose_match_note(
                "Producto aprendido (proceso pasado)",
                match_fields.get("__oc_match_note") or "",
            )
        row.update(match_fields)
        row.update(saved_sel)
        if saved_overwrite:
            row["__overwrite_oc_price"] = saved_overwrite
        _restore_saved_uom(row, saved_uom, saved_product_id)
        if match_fields.get("__oc_line_id"):
            matched += 1
    return matched


def _suggest_product_from_pool(
    codigo: str,
    descripcion: str,
    qty: Optional[float],
    pool: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Fuzzy de la etiqueta contra los productos de las OC del proveedor.

    Devuelve el mejor producto (sin vincular línea OC) cuando supera el umbral.
    Se usa para sugerir producto cuando no hubo match de OC en la línea.
    """
    best: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for po in _matchable_po_lines(pool):
        product_id = po.get("product_id")
        if not product_id:
            continue
        sc = _pkg()._line_match_score(codigo=codigo, descripcion=descripcion, qty=qty, po_line=po)
        if sc > best_score:
            best_score = sc
            best = po
    if not best or best_score < _min_match_score(codigo):
        return None
    return {
        "product_id": int(best["product_id"]),
        "score": best_score,
        "line_name": best.get("line_name") or "",
    }


def _best_po_line_by_score(
    po_lines: List[Dict[str, Any]],
    *,
    codigo: str,
    descripcion: str,
    qty: Optional[float],
) -> Tuple[Optional[Dict[str, Any]], float]:
    best: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for po in _matchable_po_lines(po_lines):
        sc = _pkg()._line_match_score(codigo=codigo, descripcion=descripcion, qty=qty, po_line=po)
        if sc > best_score:
            best_score = sc
            best = {**po, "score": sc}
    return best, best_score


def _best_po_line_for_product(
    po_lines: List[Dict[str, Any]],
    product_id: int,
    *,
    codigo: str,
    descripcion: str,
    qty: Optional[float],
) -> Optional[Dict[str, Any]]:
    """Mejor línea OC con el mismo product_id (producto↔producto), sin umbral de etiqueta."""
    same = [
        p
        for p in _matchable_po_lines(po_lines)
        if int(p.get("product_id") or 0) == int(product_id)
    ]
    if not same:
        return None
    best: Optional[Dict[str, Any]] = None
    best_score = -1.0
    for po in same:
        sc = _pkg()._line_match_score(codigo=codigo, descripcion=descripcion, qty=qty, po_line=po)
        if sc > best_score:
            best_score = sc
            best = {**po, "score": sc}
    return best


def _apply_oc_link_fields(result: Dict[str, Any], po: Dict[str, Any]) -> None:
    result.update(
        {
            "__oc_name": po.get("order_name") or "",
            "__oc_partner_ref": po.get("partner_ref") or "",
            "__oc_line_name": po.get("line_name") or "",
            "__oc_match_score": f"{float(po.get('score') or 0):.0f}",
            "__qty_pedido": f"{po.get('product_qty', 0):g}",
            "__qty_recibido": f"{po.get('qty_received', 0):g}",
            "__qty_facturado_po": f"{po.get('qty_invoiced', 0):g}",
            "__oc_order_id": str(po.get("order_id") or ""),
            "__oc_line_id": str(po.get("line_id") or ""),
        }
    )


def match_invoice_row(
    row: Dict[str, Any],
    po_lines: List[Dict[str, Any]],
    uom_catalog: Dict[str, Dict[str, Any]],
    *,
    suggest_pool: Optional[List[Dict[str, Any]]] = None,
    learned_product_id: Optional[int] = None,
    learned_uom_id: Optional[int] = None,
) -> Dict[str, Any]:
    codigo = _normalize(row.get("__item_codigo") or row.get("invoice_line_ids/name"))
    desc = _normalize(row.get("invoice_line_ids/name") or row.get("Nombre de producto"))
    qty, um_raw = _resolve_invoice_qty_um(row, desc, repair_row=True)

    best, best_score = _best_po_line_by_score(
        po_lines, codigo=codigo, descripcion=desc, qty=qty
    )

    result: Dict[str, Any] = _empty_purchase_fields()
    result["__um_proveedor"] = um_raw
    result["__qty_original"] = "" if qty is None else str(qty)
    result["__qty_escalada"] = "" if qty is None else str(qty)

    min_score = _min_match_score(codigo)
    product_raw = _normalize(row.get("invoice_line_ids/product_id"))
    # Prioridad: producto ya en fila > memoria (elección confirmada) > match OC > fuzzy.
    # Memoria gana al match OC para no pisar lo que el operador ya decidió.

    def _link_oc_keep_product(
        *,
        product_id: int,
        oc_note: str,
        target_uom_id: Optional[int],
        keep_qty: bool,
        product_suggested: str = "",
    ) -> Dict[str, Any]:
        uom_info = _apply_uom_scaling_for_product(
            row,
            invoice_qty=qty,
            invoice_um_raw=um_raw,
            product_id=product_id,
            uom_catalog=uom_catalog,
            target_uom_id=target_uom_id,
        )
        if keep_qty and uom_info.get("um_note") == "Re-escalado":
            if product_suggested == "memory" and target_uom_id:
                keep_note = "UM aprendida sin re-escalar qty"
            elif target_uom_id:
                keep_note = "UM guardada sin re-escalar qty"
            else:
                keep_note = "UM sugerida sin re-escalar qty"
            uom_info = {
                **uom_info,
                "qty_escalada": result["__qty_original"],
                "um_factor": "",
                "um_note": keep_note,
            }
        note = oc_note
        if target_uom_id and (uom_info.get("um_empresa") or ""):
            note = _compose_match_note(note, f"UM {uom_info.get('um_empresa')}")
        out = {
            "__um_proveedor": uom_info.get("um_proveedor") or um_raw,
            "__um_empresa": uom_info.get("um_empresa") or "",
            "__um_empresa_id": uom_info.get("um_empresa_id") or "",
            "__qty_original": uom_info.get("qty_original") or result["__qty_original"],
            "__qty_escalada": uom_info.get("qty_escalada") or result["__qty_escalada"],
            "__um_factor": uom_info.get("um_factor") or "",
            "__um_note": uom_info.get("um_note") or "",
            "__product_suggested": product_suggested,
        }
        result.update(out)
        oc_link = _best_po_line_for_product(
            po_lines,
            product_id,
            codigo=codigo,
            descripcion=desc,
            qty=qty,
        )
        if not oc_link and best and best_score >= min_score:
            oc_link = best
            if int(oc_link.get("product_id") or 0) != product_id:
                oc_link = None
        if oc_link:
            _apply_oc_link_fields(result, oc_link)
            note = _compose_match_note(
                note,
                f"OC {oc_link.get('order_name') or ''} · {oc_link.get('line_name') or ''}".strip(
                    " ·"
                ),
            )
        result["__oc_match_note"] = _compose_match_note(note, result.get("__um_note") or "")
        return result

    # Producto ya en fila (operador / autosave): no pisar con match por etiqueta OC.
    if product_raw.isdigit():
        confirmed_id = int(product_raw)
        saved_uom_raw = _normalize(row.get("__um_empresa_id"))
        target_uom = int(saved_uom_raw) if saved_uom_raw.isdigit() else None
        return _link_oc_keep_product(
            product_id=confirmed_id,
            oc_note="Producto confirmado en fila",
            target_uom_id=target_uom,
            keep_qty=bool(target_uom),
            product_suggested="",
        )

    if (
        learned_product_id is not None
        and int(learned_product_id) > 0
    ):
        learned_id = int(learned_product_id)
        product_raw = str(learned_id)
        row["invoice_line_ids/product_id"] = product_raw
        target_uom = (
            int(learned_uom_id)
            if learned_uom_id is not None and int(learned_uom_id) > 0
            else None
        )
        return _link_oc_keep_product(
            product_id=learned_id,
            oc_note="Producto aprendido (proceso pasado)",
            target_uom_id=target_uom,
            keep_qty=True,
            product_suggested="memory",
        )

    if not best or best_score < min_score:
        suggested: Optional[Dict[str, Any]] = None
        if not product_raw.isdigit() and suggest_pool:
            suggested = _suggest_product_from_pool(codigo, desc, qty, suggest_pool)
            if suggested:
                product_raw = str(suggested["product_id"])
                row["invoice_line_ids/product_id"] = product_raw
        if product_raw.isdigit():
            uom_info = _apply_uom_scaling_for_product(
                row,
                invoice_qty=qty,
                invoice_um_raw=um_raw,
                product_id=int(product_raw),
                uom_catalog=uom_catalog,
            )
            # Sugerencia fuzzy (sin OC): stamp UM pero no reescribir cantidad.
            # UM factura suele ser ambigua (UNID/KG) y el re-escalado a packs
            # de peso inventa qtys (20 → 0.32 en Sal fina / PDF Mauri).
            if suggested and uom_info.get("um_note") == "Re-escalado":
                uom_info = {
                    **uom_info,
                    "qty_escalada": result["__qty_original"],
                    "um_factor": "",
                    "um_note": "UM sugerida sin re-escalar qty",
                }
            result.update(
                {
                    "__um_proveedor": uom_info.get("um_proveedor") or um_raw,
                    "__um_empresa": uom_info.get("um_empresa") or "",
                    "__um_empresa_id": uom_info.get("um_empresa_id") or "",
                    "__qty_original": uom_info.get("qty_original") or result["__qty_original"],
                    "__qty_escalada": uom_info.get("qty_escalada") or result["__qty_escalada"],
                    "__um_factor": uom_info.get("um_factor") or "",
                    "__um_note": uom_info.get("um_note") or "",
                }
            )
            if (
                not suggested
                and uom_info.get("um_note") == "Re-escalado"
                and uom_info.get("qty_escalada")
            ):
                row["invoice_line_ids/quantity"] = uom_info["qty_escalada"]
        if suggested:
            result["__product_suggested"] = f"{suggested['score']:.0f}"
            result["__oc_match_note"] = _compose_match_note(
                f"Producto sugerido (fuzzy {suggested['score']:.0f}%)",
                result.get("__um_note") or "",
            )
        else:
            result["__oc_match_note"] = _compose_match_note(
                "Sin match OC" if po_lines else "Sin OC en Odoo",
                result.get("__um_note") or "",
            )
        return result

    # TODO / invariante: UM inferida = lista/default del *producto* (uom_po_id),
    # no la UM de la línea OC. La OC sigue vinculada vía __oc_line_id.
    product_id = best.get("product_id")
    if product_id:
        uom_info = _apply_uom_scaling_for_product(
            row,
            invoice_qty=qty,
            invoice_um_raw=um_raw,
            product_id=int(product_id),
            uom_catalog=uom_catalog,
        )
    else:
        uom_info = _apply_uom_scaling(
            row,
            invoice_qty=qty,
            invoice_um_raw=um_raw,
            po_uom_id=best.get("product_uom_id"),
            po_uom_name=best.get("product_uom_name") or "",
            uom_catalog=uom_catalog,
        )

    oc_note = f"OC {best.get('order_name') or ''} · {best.get('line_name') or ''}".strip(" ·")
    _apply_oc_link_fields(result, best)
    result.update(
        {
            "__um_proveedor": uom_info.get("um_proveedor") or um_raw,
            "__um_empresa": uom_info.get("um_empresa") or "",
            "__um_empresa_id": uom_info.get("um_empresa_id") or "",
            "__qty_original": uom_info.get("qty_original") or result["__qty_original"],
            "__qty_escalada": uom_info.get("qty_escalada") or result["__qty_escalada"],
            "__um_factor": uom_info.get("um_factor") or "",
            "__um_note": uom_info.get("um_note") or "",
        }
    )

    if uom_info.get("um_note") == "Re-escalado" and uom_info.get("qty_escalada"):
        row["invoice_line_ids/quantity"] = uom_info["qty_escalada"]

    if product_id:
        row["invoice_line_ids/product_id"] = str(product_id)

    result["__oc_match_note"] = _compose_match_note(oc_note, result.get("__um_note") or "")

    return result


def _propagate_partner_for_matching(rows: List[Dict[str, Any]]) -> None:
    """Unifica partner_id del comprobante (encabezado → todas las líneas)."""
    for comprobante_rows in _group_rows_by_comprobante(rows).values():
        canonical = ""
        for row in comprobante_rows:
            if not isinstance(row, dict):
                continue
            pid = _normalize(row.get("partner_id"))
            if pid:
                canonical = pid
                break
        if not canonical:
            continue
        for row in comprobante_rows:
            if isinstance(row, dict):
                row["partner_id"] = canonical


def row_has_odoo_purchase_data(row: Dict[str, Any]) -> bool:
    """True si la fila tiene match OC o UM re-escalada desde Odoo."""
    if not isinstance(row, dict):
        return False
    if row.get("__oc_line_id"):
        return True
    if str(row.get("__um_empresa") or "").strip():
        return True
    note = str(row.get("__oc_match_note") or "").strip()
    return note.startswith("OC ")


def compute_show_purchase_columns(rows: List[Dict[str, Any]]) -> bool:
    return any(row_has_odoo_purchase_data(r) for r in rows)


def has_any_oc_candidates(oc_candidates_by_comprobante: Dict[str, Any]) -> bool:
    """True si al menos un comprobante tiene OCs del proveedor en Odoo."""
    return any(bool(cands) for cands in (oc_candidates_by_comprobante or {}).values())


def enrich_rows_with_purchase_data(
    rows: List[Dict[str, Any]],
    *,
    fetch_candidates: bool = True,
    company_id: Optional[int] = None,
    product_memory: Optional[Dict[Tuple[int, str], Any]] = None,
) -> Dict[str, Any]:
    """
    Enriquece filas UI con OC, comparación pedido/recibido/facturado y re-escalado UM.
    Devuelve resumen para debug/API.

    Si se pasa `company_id` (o un `product_memory` prearmado), sugiere producto
    desde elecciones confirmadas de procesos pasados antes del fuzzy de OCs.
    """
    summary: Dict[str, Any] = {
        "enabled": False,
        "partners": 0,
        "rows_matched": 0,
        "rows_total": 0,
        "show_purchase_columns": False,
        "oc_candidates_by_comprobante": {},
        "selected_oc_by_comprobante": {},
        "oc_searched_by_comprobante": {},
        "oc_provider_has_ocs_by_comprobante": {},
    }
    if not rows or not _pkg().is_purchase_odoo_configured():
        return summary

    summary["enabled"] = True
    _propagate_partner_for_matching(rows)
    pm = _pkg()
    uom_catalog = pm.get_uom_catalog()
    partner_lines: Dict[int, List[Dict[str, Any]]] = {}
    oc_detected_names: List[str] = []
    memory_index = product_memory
    if memory_index is None and company_id is not None:
        from facturia_matching.persistence.product_label_memory import (
            build_memory_index_for_company,
        )

        memory_index = build_memory_index_for_company(company_id)

    for comprobante_rows in _group_rows_by_comprobante(rows).values():
        content_rows = [r for r in comprobante_rows if _is_content_row(r)]
        summary["rows_total"] += len(content_rows)

        partner_raw = ""
        for row in comprobante_rows:
            pid = _normalize(row.get("partner_id"))
            if pid:
                partner_raw = pid
                break

        comp_idx = comprobante_rows[0].get("__comprobante_idx")
        comp_key = str(comp_idx) if comp_idx is not None else "0"

        # Solo encabezado: re-aplica OC guardada para el header tras reload;
        # no auto-elige ni matchea líneas (no hay).
        if not content_rows:
            if not partner_raw.isdigit():
                continue
            partner_id = int(partner_raw)
            if partner_id not in partner_lines:
                partner_lines[partner_id] = pm.fetch_partner_po_lines(partner_id)
                summary["partners"] += 1
            po_lines = partner_lines[partner_id]
            summary["oc_provider_has_ocs_by_comprobante"][comp_key] = bool(po_lines)
            summary["oc_candidates_by_comprobante"][comp_key] = (
                score_oc_candidates(comprobante_rows, po_lines) if fetch_candidates else []
            )
            saved_oid = _saved_oc_order_id(comprobante_rows)
            selected_oid: Optional[int] = None
            selected_name = ""
            if saved_oid and any(int(p.get("order_id") or 0) == saved_oid for p in po_lines):
                selected_oid = saved_oid
                selected_name = _normalize(comprobante_rows[0].get("__selected_oc_name"))
                for po in po_lines:
                    if int(po.get("order_id") or 0) == saved_oid:
                        selected_name = selected_name or po.get("order_name") or ""
                        break
            elif saved_oid and not po_lines:
                selected_oid = saved_oid
                selected_name = _normalize(comprobante_rows[0].get("__selected_oc_name"))
            elif saved_oid and po_lines:
                _set_comprobante_oc_selection(comprobante_rows, None, "")
            if selected_oid:
                summary["selected_oc_by_comprobante"][comp_key] = selected_oid
                summary.setdefault("oc_searched_by_comprobante", {})[comp_key] = True
                _set_comprobante_oc_selection(comprobante_rows, selected_oid, selected_name)
                if selected_name:
                    oc_detected_names.append(selected_name)
            continue

        if not partner_raw.isdigit():
            for row in content_rows:
                saved_product_id = _normalize(row.get("invoice_line_ids/product_id"))
                saved_uom = _snapshot_saved_uom(row)
                saved_overwrite = row.get("__overwrite_oc_price", "")
                row.update(_empty_purchase_fields())
                row["__oc_match_note"] = "Sin proveedor Odoo"
                if saved_overwrite:
                    row["__overwrite_oc_price"] = saved_overwrite
                _restore_saved_uom(row, saved_uom, saved_product_id)
            continue

        partner_id = int(partner_raw)
        if partner_id not in partner_lines:
            partner_lines[partner_id] = pm.fetch_partner_po_lines(partner_id)
            summary["partners"] += 1

        po_lines = partner_lines[partner_id]
        summary["oc_provider_has_ocs_by_comprobante"][comp_key] = bool(po_lines)

        if fetch_candidates:
            candidates = score_oc_candidates(comprobante_rows, po_lines)
            summary["oc_candidates_by_comprobante"][comp_key] = candidates
            saved_oid = _saved_oc_order_id(comprobante_rows)
            selected_oid, selected_name = _resolve_selected_oc(candidates, saved_oid)
        else:
            summary["oc_candidates_by_comprobante"][comp_key] = []
            saved_oid = _saved_oc_order_id(comprobante_rows)
            selected_oid = None
            selected_name = ""
            if saved_oid and any(int(p.get("order_id") or 0) == saved_oid for p in po_lines):
                selected_oid = saved_oid
                selected_name = _normalize(comprobante_rows[0].get("__selected_oc_name"))
                for po in po_lines:
                    if int(po.get("order_id") or 0) == saved_oid:
                        selected_name = selected_name or po.get("order_name") or ""
                        break
            elif saved_oid and po_lines:
                # Solo limpiar si pudimos leer OCs del proveedor y la guardada no está.
                _set_comprobante_oc_selection(comprobante_rows, None, "")
            elif saved_oid:
                # Sin líneas PO (Odoo down / sin fetch): conservar la OC guardada.
                selected_oid = saved_oid
                selected_name = _normalize(comprobante_rows[0].get("__selected_oc_name"))
        if selected_oid:
            summary["selected_oc_by_comprobante"][comp_key] = selected_oid
            # Marca «ya buscado» para que el header muestre la pastilla OC tras reload
            # (sin forzar una lista de candidatos nueva).
            summary.setdefault("oc_searched_by_comprobante", {})[comp_key] = True
            _set_comprobante_oc_selection(comprobante_rows, selected_oid, selected_name)
            if selected_name:
                oc_detected_names.append(selected_name)

        matched = _match_comprobante_rows(
            comprobante_rows,
            po_lines,
            uom_catalog,
            selected_oid,
            product_memory=memory_index,
        )
        summary["rows_matched"] += matched

    summary["oc_detected"] = oc_detected_names[0] if oc_detected_names else ""
    # Columnas UM/OC: con candidatos en memoria (tras buscar) O con datos ya
    # matcheados/guardados en filas (reload tras select-oc).
    summary["show_purchase_columns"] = has_any_oc_candidates(
        summary["oc_candidates_by_comprobante"]
    ) or compute_show_purchase_columns(rows)
    return summary


def search_oc_candidates_for_comprobante(
    rows: List[Dict[str, Any]],
    comprobante_idx: Any,
) -> Dict[str, Any]:
    """Busca y rankea OCs similares para un comprobante (bajo demanda desde la UI)."""
    pm = _pkg()
    if not pm.is_purchase_odoo_configured():
        raise ValueError(
            "Odoo no está configurado para este perfil; no se pueden buscar OCs."
        )
    clear_purchase_cache()
    _propagate_partner_for_matching(rows)
    groups = _group_rows_by_comprobante(rows)
    comprobante_rows = groups.get(comprobante_idx) or groups.get(str(comprobante_idx))
    if not comprobante_rows:
        raise ValueError(f"Comprobante {comprobante_idx} no encontrado.")

    partner_raw = ""
    for row in comprobante_rows:
        pid = _normalize(row.get("partner_id"))
        if pid:
            partner_raw = pid
            break
    if not partner_raw.isdigit():
        raise ValueError("Sin proveedor Odoo para este comprobante.")

    partner_id = int(partner_raw)
    po_lines = pm.fetch_partner_po_lines(partner_id)
    candidates = score_oc_candidates(comprobante_rows, po_lines)
    comp_key = str(comprobante_rows[0].get("__comprobante_idx", comprobante_idx))

    summary = enrich_rows_with_purchase_data(rows, fetch_candidates=False)
    summary["oc_candidates_by_comprobante"][comp_key] = candidates
    summary["oc_provider_has_ocs_by_comprobante"][comp_key] = bool(po_lines)
    summary.setdefault("oc_searched_by_comprobante", {})[comp_key] = True
    summary["show_purchase_columns"] = has_any_oc_candidates(
        summary["oc_candidates_by_comprobante"]
    ) or compute_show_purchase_columns(rows)
    return summary


def apply_oc_selection(
    rows: List[Dict[str, Any]],
    comprobante_idx: Any,
    order_id: int,
    *,
    company_id: Optional[int] = None,
    product_memory: Optional[Dict[Tuple[int, str], Any]] = None,
) -> Dict[str, Any]:
    """Aplica selección manual de OC y re-matchea solo ese comprobante.

    Con `company_id` (o `product_memory`) se consulta la memoria de producto
    para no perder elecciones aprendidas al vincular OC (PDF Gran Crianza).
    """
    groups = _group_rows_by_comprobante(rows)
    comprobante_rows = groups.get(comprobante_idx) or groups.get(str(comprobante_idx))
    if not comprobante_rows:
        raise ValueError(f"Comprobante {comprobante_idx} no encontrado.")

    memory_index = product_memory
    if memory_index is None and company_id is not None:
        from facturia_matching.persistence.product_label_memory import (
            build_memory_index_for_company,
        )

        memory_index = build_memory_index_for_company(company_id)

    if int(order_id) == 0:
        clear_comprobante_purchase_fields(comprobante_rows)
        _set_comprobante_oc_selection(comprobante_rows, None, "")
        # Re-listar OCs del proveedor: el botón/modal deben seguir disponibles
        # aunque el operador haya elegido «Sin OC».
        if _pkg().is_purchase_odoo_configured():
            return search_oc_candidates_for_comprobante(rows, comprobante_idx)
        comp_key = str(comprobante_rows[0].get("__comprobante_idx", comprobante_idx))
        summary = enrich_rows_with_purchase_data(
            rows, fetch_candidates=False, company_id=company_id, product_memory=memory_index
        )
        summary.setdefault("oc_searched_by_comprobante", {})[comp_key] = True
        return summary

    _propagate_partner_for_matching(rows)
    partner_raw = ""
    for row in comprobante_rows:
        pid = _normalize(row.get("partner_id"))
        if pid:
            partner_raw = pid
            break
    if not partner_raw.isdigit():
        raise ValueError("Sin proveedor Odoo para este comprobante.")

    partner_id = int(partner_raw)
    pm = _pkg()
    po_lines = pm.fetch_partner_po_lines(partner_id)
    candidates = score_oc_candidates(comprobante_rows, po_lines)
    order_name = ""
    for c in candidates:
        if int(c["order_id"]) == int(order_id):
            order_name = c.get("order_name") or ""
            break

    _set_comprobante_oc_selection(comprobante_rows, int(order_id), order_name)
    uom_catalog = pm.get_uom_catalog()
    _match_comprobante_rows(
        comprobante_rows,
        po_lines,
        uom_catalog,
        int(order_id),
        product_memory=memory_index,
    )
    summary = enrich_rows_with_purchase_data(
        rows, fetch_candidates=True, company_id=company_id, product_memory=memory_index
    )
    comp_key = str(comprobante_rows[0].get("__comprobante_idx", comprobante_idx))
    summary.setdefault("oc_searched_by_comprobante", {})[comp_key] = True
    return summary


def clear_comprobante_purchase_fields(comprobante_rows: List[Dict[str, Any]]) -> None:
    """Limpia datos OC/UM y selección de un comprobante (p. ej. al cambiar proveedor)."""
    empty = _empty_purchase_fields()
    for row in comprobante_rows:
        row.update(empty)
        if _is_content_row(row):
            row["invoice_line_ids/product_id"] = ""


def rematch_comprobante_purchase(
    rows: List[Dict[str, Any]],
    comprobante_idx: Any,
) -> Dict[str, Any]:
    """Re-matchea OC/UM de un comprobante tras cambio de proveedor u otros datos de cabecera."""
    clear_purchase_cache()
    groups = _group_rows_by_comprobante(rows)
    comprobante_rows = groups.get(comprobante_idx) or groups.get(str(comprobante_idx))
    if not comprobante_rows:
        raise ValueError(f"Comprobante {comprobante_idx} no encontrado.")

    clear_comprobante_purchase_fields(comprobante_rows)
    _propagate_partner_for_matching(rows)
    return enrich_rows_with_purchase_data(rows)


def clear_purchase_cache() -> None:
    _po_cache.clear()
    _product_uom_cache.clear()
    _uom_cache.clear()
    _uom_model_relative_cache.clear()
    _pkg().clear_odoo_model_fields_cache()
    from facturia_matching.odoo.purchase_matching.uom_ai import clear_uom_ai_cache

    clear_uom_ai_cache()

