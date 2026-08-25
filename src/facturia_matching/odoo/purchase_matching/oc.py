"""Fetch de órdenes de compra y ranking de candidatos OC."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz

from facturia_matching.odoo.purchase_matching._util import (
    _is_content_row,
    _normalize,
    _normalize_key,
    _parse_amount,
    _pkg,
    _tenant_cache_key,
)
from facturia_matching.odoo.purchase_matching.scoring import (
    _attach_dinner_po_note_labels,
    _invoice_variant_conflict,
    _line_match_score,
    _matchable_po_lines,
    _soft_recount_allowed,
)
from facturia_matching.odoo.purchase_matching.uom import _resolve_invoice_qty_um

_po_cache: Dict[str, Dict[int, Dict[str, Any]]] = {}

def _resolve_po_partner_scope(partner_id: int) -> int:
    """Usa commercial_partner_id para incluir OCs en contactos hijos del mismo proveedor."""
    pm = _pkg()
    rows = pm.odoo_search_read(
        "res.partner",
        [("id", "=", partner_id)],
        ["commercial_partner_id"],
        limit=1,
        config=pm._purchase_odoo_config(),
    )
    if not rows:
        return partner_id
    commercial = rows[0].get("commercial_partner_id")
    if isinstance(commercial, (list, tuple)) and commercial:
        return int(commercial[0])
    if isinstance(commercial, int):
        return commercial
    return partner_id


def _partner_po_search_domain(scope_id: int) -> List[Any]:
    """OC confirmadas del proveedor (incluye recepcionadas y no recepcionadas)."""
    return [
        ("partner_id", "child_of", scope_id),
        ("state", "in", ["purchase", "done"]),
    ]


def _receipt_status_label(status: Any) -> str:
    if status == "pending":
        return "No recepcionada"
    if status == "partial":
        return "Parcialmente recepcionada"
    if status == "full":
        return "Recepcionada"
    if not status:
        return "Recepcionada"
    return str(status)


def _order_deliver_to_label(po: Dict[str, Any]) -> str:
    dest = po.get("dest_address_id")
    if isinstance(dest, (list, tuple)) and len(dest) > 1:
        name = str(dest[1]).strip()
        if name:
            return name
    picking = po.get("picking_type_id")
    if isinstance(picking, (list, tuple)) and len(picking) > 1:
        return str(picking[1]).strip()
    return ""


def fetch_partner_po_lines(
    partner_id: int,
    *,
    limit_orders: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Líneas de OC confirmadas del proveedor.

    Por defecto trae **todas** las órdenes (`limit_orders=None` → Odoo `limit=False`).
    Pasar un entero solo en tests o diagnósticos.
    """
    tenant_cache = _po_cache.setdefault(_tenant_cache_key(), {})
    if partner_id in tenant_cache:
        return tenant_cache[partner_id]["lines"]

    # No cachear vacío por config ausente: si después hay credenciales, hay que poder reintentar.
    pm = _pkg()
    if not pm.is_purchase_odoo_configured():
        return []

    cfg = pm._purchase_odoo_config()
    scope_id = pm._resolve_po_partner_scope(partner_id)
    po_domain = _partner_po_search_domain(scope_id)
    orders = pm.odoo_search_read(
        "purchase.order",
        po_domain,
        [
            "id",
            "name",
            "partner_ref",
            "date_order",
            "receipt_status",
            "picking_type_id",
            "dest_address_id",
        ],
        limit=False if limit_orders is None else limit_orders,
        order="date_order desc, id desc",
        config=cfg,
    )
    if not orders:
        tenant_cache[partner_id] = {"lines": []}
        return []

    order_ids = [int(o["id"]) for o in orders]
    order_by_id = {int(o["id"]): o for o in orders}
    lines = pm.odoo_search_read(
        "purchase.order.line",
        [("order_id", "in", order_ids)],
        [
            "id",
            "order_id",
            "name",
            "product_id",
            "product_qty",
            "qty_received",
            "qty_invoiced",
            "price_unit",
            "product_uom",
        ],
        limit=5000,
        config=cfg,
    )
    enriched: List[Dict[str, Any]] = []
    for ln in lines or []:
        oid = ln.get("order_id")
        if not oid:
            continue
        order_id = int(oid[0] if isinstance(oid, (list, tuple)) else oid)
        po = order_by_id.get(order_id) or {}
        uom = ln.get("product_uom") or []
        product = ln.get("product_id") or []
        product_id = None
        if isinstance(product, (list, tuple)) and product:
            product_id = int(product[0])
        enriched.append(
            {
                "line_id": int(ln["id"]),
                "order_id": order_id,
                "order_name": po.get("name") or "",
                "partner_ref": po.get("partner_ref") or "",
                "date_order": str(po.get("date_order") or ""),
                "receipt_status": po.get("receipt_status"),
                "receipt_status_label": _receipt_status_label(po.get("receipt_status")),
                "deliver_to": _order_deliver_to_label(po),
                "line_name": _normalize(ln.get("name")),
                "product_id": product_id,
                "product_qty": float(ln.get("product_qty") or 0),
                "qty_received": float(ln.get("qty_received") or 0),
                "qty_invoiced": float(ln.get("qty_invoiced") or 0),
                "price_unit": float(ln.get("price_unit") or 0),
                "product_uom_id": int(uom[0]) if isinstance(uom, (list, tuple)) and uom else None,
                "product_uom_name": uom[1] if isinstance(uom, (list, tuple)) and len(uom) > 1 else "",
                "note_labels": [],
                "is_note": False,
            }
        )
    _attach_dinner_po_note_labels(enriched)
    tenant_cache[partner_id] = {"lines": enriched}
    return enriched



def _min_match_score(codigo: str) -> float:
    return 70.0 if _normalize_key(codigo) not in {"", "1", "NO DISPONIBLE"} else 75.0


# Soft score: filas extra del mismo producto/etiqueta reusan una línea OC (tope product_qty).
# Mismo umbral que memoria de producto (etiqueta≈etiqueta entre filas de factura).
_SOFT_SIBLING_LABEL_MIN = 88.0


def _po_line_score_capacity(product_qty: Any, *, lines_total: int) -> int:
    """Cuántas filas de factura puede contar una línea OC en el ranking del modal.

    - ``product_qty`` entero (p.ej. 3 pedidas / 1 línea CAR-CARNE): capacidad = ese entero.
    - Qty fraccional (pedido en kg): sin tope práctico → ``lines_total``.
    """
    try:
        qty = float(product_qty or 0)
    except (TypeError, ValueError):
        qty = 0.0
    if qty < 1:
        return 1
    rounded = round(qty)
    if abs(qty - rounded) <= 0.01:
        return max(1, int(rounded))
    return max(1, int(lines_total or 1))


def _integer_product_qty(product_qty: Any) -> Optional[int]:
    """Cant. pedida entera (3 unidades / 1 línea), o None si es fraccional/kg."""
    try:
        qty = float(product_qty or 0)
    except (TypeError, ValueError):
        return None
    if qty < 1:
        return None
    rounded = round(qty)
    if abs(qty - rounded) > 0.01:
        return None
    return int(rounded)


def _qty_fit_score(
    slots_used: Dict[int, int],
    po_by_lid: Dict[int, Dict[str, Any]],
) -> float:
    """Afinidad Cant. pedida ↔ filas de factura asignadas a esa línea OC.

    Exacto (pedida=3, 3 PICADAs) = 100; pedida=4 con 3 filas = 75. Desempata
    OCs con el mismo soft score (P06790 qty=3 > OC qty=4).
    """
    fits: List[float] = []
    for lid, slots in slots_used.items():
        if slots <= 0:
            continue
        po = po_by_lid.get(lid)
        if not po:
            continue
        ordered = _integer_product_qty(po.get("product_qty"))
        if ordered is None:
            continue
        fits.append(100.0 * min(slots, ordered) / max(slots, ordered))
    if not fits:
        return 100.0
    return round(sum(fits) / len(fits), 1)


def _row_match_context(row: Dict[str, Any]) -> Dict[str, Any]:
    codigo = _normalize(row.get("__item_codigo") or row.get("invoice_line_ids/name"))
    desc = _normalize(row.get("invoice_line_ids/name") or row.get("Nombre de producto"))
    qty, um_raw = _resolve_invoice_qty_um(row, desc, repair_row=False)
    return {"codigo": codigo, "descripcion": desc, "qty": qty, "um_raw": um_raw}


def _group_po_lines_by_order(po_lines: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    by_order: Dict[int, List[Dict[str, Any]]] = {}
    for po in po_lines:
        oid = int(po.get("order_id") or 0)
        if oid:
            by_order.setdefault(oid, []).append(po)
    return by_order


# Campos de fila UI / FacturIA con posible referencia de pedido (PDF Salta: PEDIDO 26.05).
_INVOICE_REF_ROW_KEYS = (
    "__fac_referencia",
    "__fac_partner_ref",
    "payment_reference",
)
_REF_DATE_TOKEN_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})\b")
# Match fuerte de ref (PEDIDO …) gana el tie-break / ranking frente a canasta empatada.
_REF_SCORE_STRONG = 85.0


def _normalize_oc_ref(raw: Any) -> str:
    s = _normalize_key(raw)
    if not s:
        return ""
    s = re.sub(r"[^\w.\s]+", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def _collect_invoice_refs(comprobante_rows: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    seen = set()
    for row in comprobante_rows or []:
        if not isinstance(row, dict):
            continue
        for key in _INVOICE_REF_ROW_KEYS:
            raw = _normalize(row.get(key))
            if not raw:
                continue
            key_n = _normalize_oc_ref(raw)
            if key_n and key_n not in seen:
                seen.add(key_n)
                out.append(raw)
    return out


def _collect_invoice_dates(comprobante_rows: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    seen = set()
    for row in comprobante_rows or []:
        if not isinstance(row, dict):
            continue
        raw = _normalize(row.get("invoice_date"))
        if raw and raw not in seen:
            seen.add(raw)
            out.append(raw)
    return out


def _parse_dd_mm_tokens(text: str) -> List[Tuple[int, int]]:
    found: List[Tuple[int, int]] = []
    for m in _REF_DATE_TOKEN_RE.finditer(text or ""):
        try:
            d, mo = int(m.group(1)), int(m.group(2))
        except ValueError:
            continue
        if 1 <= d <= 31 and 1 <= mo <= 12:
            found.append((d, mo))
    return found


def _invoice_date_dd_mm(raw: str) -> Optional[Tuple[int, int]]:
    """Extrae (día, mes) de invoice_date UI (dd/mm/yyyy o ISO)."""
    s = _normalize(raw)
    if not s:
        return None
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        return int(m.group(3)), int(m.group(2))
    return None


def _partner_ref_date_proximity_score(
    partner_ref_norm: str, invoice_dates: List[str]
) -> float:
    """Boost suave si partner_ref trae DD.MM cercano a la fecha de factura (±1 día)."""
    ref_tokens = _parse_dd_mm_tokens(partner_ref_norm)
    if not ref_tokens or not invoice_dates:
        return 0.0
    best = 0.0
    for inv in invoice_dates:
        inv_dm = _invoice_date_dd_mm(inv)
        if not inv_dm:
            continue
        d, mo = inv_dm
        for rd, rm in ref_tokens:
            if rm != mo:
                continue
            if rd == d:
                best = max(best, 60.0)
            elif abs(rd - d) == 1:
                best = max(best, 50.0)
    return best


def _ref_match_score(
    partner_ref: Any,
    invoice_refs: List[str],
    invoice_dates: Optional[List[str]] = None,
) -> float:
    """0–100: similitud partner_ref OC ↔ referencias / fecha de la factura."""
    pref = _normalize_oc_ref(partner_ref)
    if not pref:
        return 0.0
    best = 0.0
    for inv in invoice_refs or []:
        inv_n = _normalize_oc_ref(inv)
        if not inv_n:
            continue
        if pref == inv_n:
            return 100.0
        if pref in inv_n or inv_n in pref:
            best = max(best, 95.0)
            continue
        best = max(best, float(fuzz.token_set_ratio(pref, inv_n)))
        best = max(best, float(fuzz.partial_ratio(pref, inv_n)))
    if best < _REF_SCORE_STRONG:
        best = max(
            best,
            _partner_ref_date_proximity_score(pref, invoice_dates or []),
        )
    return float(best)


def _oc_date_sort_value(raw: Any) -> float:
    """Timestamp para desempate: fechas más recientes ordenan más arriba."""
    from datetime import datetime

    s = _normalize(raw)
    if not s:
        return 0.0
    # Odoo suele mandar "2026-05-26 10:30:00" o "2026-05-26".
    candidates_fmt = (
        ("%Y-%m-%d %H:%M:%S", s[:19] if len(s) >= 19 else ""),
        ("%Y-%m-%d", s[:10]),
        ("%d/%m/%Y", s[:10]),
        ("%d-%m-%Y", s[:10]),
    )
    for fmt, chunk in candidates_fmt:
        if not chunk or len(chunk) < 8:
            continue
        try:
            return datetime.strptime(chunk, fmt).timestamp()
        except ValueError:
            continue
    return 0.0


def score_oc_candidates(
    comprobante_rows: List[Dict[str, Any]],
    po_lines: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Rankea OCs del proveedor según matching de la canasta (líneas del comprobante).

    Si no hay líneas de producto en la factura (p.ej. solo encabezado), igual lista
    todas las OCs del proveedor con score 0 para que el operador pueda elegir.

    Además puntúa `partner_ref` de la OC contra referencias FacturIA (`__fac_referencia`)
    y, si no hay match fuerte, proximidad de fecha en la ref (PDF Salta: PEDIDO 26.05).
    Orden: ``basket_score`` (el % del modal) → ref fuerte → líneas matcheadas →
    ``qty_fit_score`` → ``date_order`` más reciente → ref_score → score_sum.

    Tras el greedy 1:1, un pase soft cuenta filas extra del mismo ``product_id``
    (o etiqueta hermana ≥88) contra una línea OC ya usada, hasta ``product_qty``
    (p.ej. 3× PICADA ↔ 1× CAR-CARNE con pedida=3). No cambia el vínculo Odoo.
    Con el mismo ``basket_score`` y ``lines_matched``, gana la OC cuya Cant. pedida
    entera calza mejor con las filas asignadas (``qty_fit_score``) antes que la fecha.
    """
    content_rows = [r for r in comprobante_rows if _is_content_row(r)]
    lines_total = len(content_rows)
    if not po_lines:
        return []

    invoice_refs = _collect_invoice_refs(comprobante_rows)
    invoice_dates = _collect_invoice_dates(comprobante_rows)
    by_order = _group_po_lines_by_order(po_lines)
    candidates: List[Dict[str, Any]] = []

    for order_id, oc_lines in by_order.items():
        first = oc_lines[0]
        lines_matched = 0
        score_sum = 0.0
        po_line_details: List[Dict[str, Any]] = []
        best_invoice_by_line: Dict[int, Dict[str, Any]] = {}

        pairs: List[Tuple[float, int, Dict[str, Any]]] = []
        for inv_i, inv_row in enumerate(content_rows):
            ctx = _row_match_context(inv_row)
            min_score = _min_match_score(ctx["codigo"])
            inv_pid_raw = _normalize(inv_row.get("invoice_line_ids/product_id"))
            inv_pid = int(inv_pid_raw) if inv_pid_raw.isdigit() else None
            for po in _matchable_po_lines(oc_lines):
                sc = _line_match_score(
                    codigo=ctx["codigo"],
                    descripcion=ctx["descripcion"],
                    qty=ctx["qty"],
                    po_line=po,
                )
                # Mismo product_id (PICADA ya mapeada a CAR-CARNE): cuenta como match
                # aunque el fuzzy de etiqueta falle (preview modal Gran Crianza).
                po_pid = int(po.get("product_id") or 0)
                if inv_pid and po_pid and inv_pid == po_pid:
                    sc = max(sc, 90.0)
                if sc >= min_score:
                    pairs.append((sc, inv_i, po))
        # 1 factura ↔ 1 línea OC: mejor score primero (zero↔ZERO antes que coca).
        pairs.sort(key=lambda t: t[0], reverse=True)
        used_inv: set = set()
        used_po: set = set()
        slots_used: Dict[int, int] = {}
        po_by_lid: Dict[int, Dict[str, Any]] = {
            int(p["line_id"]): p for p in _matchable_po_lines(oc_lines)
        }
        for sc, inv_i, po in pairs:
            lid = int(po["line_id"])
            if inv_i in used_inv or lid in used_po:
                continue
            used_inv.add(inv_i)
            used_po.add(lid)
            slots_used[lid] = 1
            lines_matched += 1
            score_sum += sc
            ctx = _row_match_context(content_rows[inv_i])
            best_invoice_by_line[lid] = {
                "invoice_desc": ctx["descripcion"],
                "score": sc,
            }

        # Soft: varias filas factura (mismo product_id / etiqueta hermana) cuentan
        # contra una línea OC con product_qty>1 (P06790: 3× PICADA ↔ 1× CAR-CARNE qty=3).
        # No asigna otro invoice_match en UI ni viola purchase_line_id 1:1 al importar.
        soft_pairs: List[Tuple[float, int, int]] = []
        for inv_i, inv_row in enumerate(content_rows):
            if inv_i in used_inv:
                continue
            ctx = _row_match_context(inv_row)
            min_score = _min_match_score(ctx["codigo"])
            inv_pid_raw = _normalize(inv_row.get("invoice_line_ids/product_id"))
            inv_pid = int(inv_pid_raw) if inv_pid_raw.isdigit() else None
            best_soft: Optional[Tuple[float, int]] = None
            for lid in used_po:
                po = po_by_lid.get(lid)
                if not po:
                    continue
                cap = _po_line_score_capacity(
                    po.get("product_qty"), lines_total=lines_total
                )
                if slots_used.get(lid, 0) >= cap:
                    continue
                hard = best_invoice_by_line.get(lid)
                if not _soft_recount_allowed(ctx["descripcion"], po, hard):
                    continue
                sc = _line_match_score(
                    codigo=ctx["codigo"],
                    descripcion=ctx["descripcion"],
                    qty=ctx["qty"],
                    po_line=po,
                )
                po_pid = int(po.get("product_id") or 0)
                if inv_pid and po_pid and inv_pid == po_pid:
                    sc = max(sc, 90.0)
                if hard and ctx["descripcion"] and hard.get("invoice_desc"):
                    sibling = float(
                        fuzz.token_set_ratio(
                            ctx["descripcion"].upper(),
                            str(hard["invoice_desc"]).upper(),
                        )
                    )
                    if sibling >= _SOFT_SIBLING_LABEL_MIN:
                        sc = max(sc, float(hard.get("score") or 0))
                if sc >= min_score and (
                    best_soft is None or sc > best_soft[0]
                ):
                    best_soft = (sc, lid)
            if best_soft is not None:
                soft_pairs.append((best_soft[0], inv_i, best_soft[1]))
        soft_pairs.sort(key=lambda t: t[0], reverse=True)
        for sc, inv_i, lid in soft_pairs:
            if inv_i in used_inv:
                continue
            po = po_by_lid.get(lid)
            if not po:
                continue
            cap = _po_line_score_capacity(
                po.get("product_qty"), lines_total=lines_total
            )
            if slots_used.get(lid, 0) >= cap:
                continue
            used_inv.add(inv_i)
            slots_used[lid] = slots_used.get(lid, 0) + 1
            lines_matched += 1
            score_sum += sc

        for po in _matchable_po_lines(oc_lines):
            lid = int(po["line_id"])
            inv_match = best_invoice_by_line.get(lid)
            po_line_details.append(
                {
                    "line_id": lid,
                    "line_name": po.get("line_name") or "",
                    "note_labels": list(po.get("note_labels") or []),
                    "product_qty": po.get("product_qty", 0),
                    "qty_received": po.get("qty_received", 0),
                    "qty_invoiced": po.get("qty_invoiced", 0),
                    "price_unit": po.get("price_unit", 0),
                    "product_uom_name": po.get("product_uom_name") or "",
                    "invoice_match": inv_match,
                }
            )

        partner_ref = first.get("partner_ref") or ""
        ref_score = _ref_match_score(partner_ref, invoice_refs, invoice_dates)
        basket_score = score_sum / lines_total if lines_total else 0.0
        qty_fit = _qty_fit_score(slots_used, po_by_lid)
        candidates.append(
            {
                "order_id": order_id,
                "order_name": first.get("order_name") or "",
                "partner_ref": partner_ref,
                "date_order": first.get("date_order") or "",
                "receipt_status": first.get("receipt_status"),
                "receipt_status_label": first.get("receipt_status_label")
                or _receipt_status_label(first.get("receipt_status")),
                "deliver_to": first.get("deliver_to") or "",
                "basket_score": round(basket_score, 1),
                "ref_score": round(ref_score, 1),
                "qty_fit_score": qty_fit,
                "lines_matched": lines_matched,
                "lines_total": lines_total,
                "score_sum": round(score_sum, 1),
                "lines": po_line_details,
            }
        )

    candidates.sort(
        key=lambda c: (
            float(c.get("basket_score") or 0),
            float(c.get("ref_score") or 0) >= _REF_SCORE_STRONG,
            c["lines_matched"],
            float(c.get("qty_fit_score") or 0),
            _oc_date_sort_value(c.get("date_order")),
            float(c.get("ref_score") or 0),
            c["score_sum"],
        ),
        reverse=True,
    )
    return candidates


