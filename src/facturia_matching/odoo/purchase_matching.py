"""
Matching factura ↔ orden de compra Odoo + re-escalado de UM.

Se integra después del parseo FacturIA sin alterar el flujo CSV/import existente.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz, process as rf_process

from facturia_matching.odoo.api import get_active_odoo_config, is_odoo_config_ready, odoo_search_read


def _purchase_odoo_config() -> Dict[str, Any]:
    """Tenant Odoo para OC: misma instancia que import (Dinner o Aliare según perfil)."""
    return get_active_odoo_config()


def is_purchase_odoo_configured() -> bool:
    return is_odoo_config_ready(_purchase_odoo_config())

# Alias UM proveedor (FacturIA) → nombre canónico Odoo
_UM_ALIASES: Dict[str, str] = {
    "UN": "Units",
    "U": "Units",
    "UNIDAD": "Units",
    "UNIDADES": "Units",
    "UNIDAD(ES)": "Units",
    "UNIT": "Units",
    "UNITS": "Units",
    "PIEZA": "Units",
    "PIEZAS": "Units",
    "KG": "kg",
    "KGS": "kg",
    "KILO": "kg",
    "KILOS": "kg",
    "GR": "g",
    "GRS": "g",
    "G": "g",
    "LT": "L",
    "L": "L",
    "LTS": "L",
    "LITRO": "L",
    "LITROS": "L",
    "ML": "ml",
    "M": "m",
    "MT": "m",
    "M2": "m²",
    "MES": "Units",
}

_QTY_UM_IN_DESC = re.compile(
    r"(?P<qty>\d+(?:[.,]\d+)?)\s*(?P<um>kg|kgs|kilos?|grs?|g|l|lt|litros?|un|unid(?:ades?)?)\b",
    re.I,
)
_OCR_IN_ALPHA_TOKEN = str.maketrans({"0": "O", "1": "I", "5": "S"})


def _ocr_fix_token(token: str) -> str:
    """Corrige confusiones OCR (0/O, 1/I) en tokens mayormente alfabéticos."""
    if len(token) < 3:
        return token
    letters = sum(1 for c in token if c.isalpha())
    if letters >= max(2, len(token) - 1):
        return token.translate(_OCR_IN_ALPHA_TOKEN)
    return token


def _desc_match_variants(desc: str) -> List[str]:
    """Variantes de descripción para fuzzy match (original + OCR corregido)."""
    base = _normalize(desc)
    if not base:
        return []
    fixed_tokens = [_ocr_fix_token(t) for t in re.split(r"([\s/\-]+)", base)]
    fixed = "".join(fixed_tokens)
    variants = [base.upper()]
    if fixed.upper() != base.upper():
        variants.append(fixed.upper())
    return variants


def _split_desc_tokens(desc_upper: str) -> List[str]:
    raw = [_ocr_fix_token(t) for t in re.split(r"[\s/\-]+", desc_upper) if len(t) >= 3]
    seen = set()
    out: List[str] = []
    for tok in raw:
        key = tok.upper()
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _normalize(s: Any) -> str:
    if s is None:
        return ""
    return " ".join(str(s).strip().split())


def _normalize_key(s: Any) -> str:
    return _normalize(s).upper()


def _parse_amount(raw: Any) -> Optional[float]:
    s = _normalize(raw)
    if not s or s.lower() in {"nan", "none", "null"}:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts) >= 2 and all(p.isdigit() and len(p) == 3 for p in parts[1:]):
            s = "".join(parts)
    try:
        return float(s)
    except ValueError:
        return None


def _canonical_um(raw: Any) -> str:
    key = _normalize_key(raw)
    if not key or key in {"NAN", "NONE", "NULL"}:
        return ""
    return _UM_ALIASES.get(key, key)


def _extract_qty_um_from_description(desc: str) -> Tuple[Optional[float], str]:
    m = _QTY_UM_IN_DESC.search(desc or "")
    if not m:
        return None, ""
    qty = _parse_amount(m.group("qty"))
    um = _canonical_um(m.group("um"))
    return qty, um


def _resolve_invoice_qty_um(
    row: Dict[str, Any],
    desc: str,
    *,
    repair_row: bool = False,
) -> Tuple[Optional[float], str]:
    """
    Cantidad/UM para matching OC.

    Prioridad: fila UI (tras reparación) → cantidad FacturIA → descripción.
    La descripción suele traer el tamaño del envase (p. ej. «X 2 KG»), no la cantidad facturada.
    """
    fac_qty = _parse_amount(row.get("__fac_item_cantidad"))
    invoice_qty = _parse_amount(row.get("invoice_line_ids/quantity"))
    desc_qty, desc_um = _extract_qty_um_from_description(desc)

    um_raw = _normalize(row.get("__um_proveedor") or "")
    if desc_um and not um_raw:
        um_raw = desc_um

    polluted_by_desc = (
        fac_qty is not None
        and desc_qty is not None
        and invoice_qty is not None
        and abs(invoice_qty - desc_qty) < 0.01
        and abs(fac_qty - desc_qty) > 0.01
    )
    partial_sanitize_qty_one = (
        fac_qty is not None
        and fac_qty > 1
        and invoice_qty is not None
        and abs(invoice_qty - 1) < 0.01
        and desc_qty is not None
        and desc_qty > fac_qty
    )

    if repair_row and fac_qty is not None and (
        polluted_by_desc or partial_sanitize_qty_one or invoice_qty is None
    ):
        row["invoice_line_ids/quantity"] = f"{fac_qty:g}"
        invoice_qty = fac_qty

    if invoice_qty is not None:
        qty = invoice_qty
    elif fac_qty is not None:
        qty = fac_qty
    elif desc_qty is not None:
        qty = desc_qty
    else:
        qty = None

    return qty, um_raw


def _fetch_uom_catalog() -> Dict[str, Dict[str, Any]]:
    rows = odoo_search_read(
        "uom.uom",
        [],
        ["id", "name", "uom_type", "factor", "category_id"],
        limit=500,
        config=_purchase_odoo_config(),
    )
    by_name: Dict[str, Dict[str, Any]] = {}
    by_id: Dict[int, Dict[str, Any]] = {}
    for row in rows or []:
        iid = int(row["id"])
        name = _normalize(row.get("name"))
        item = {
            "id": iid,
            "name": name,
            "factor": float(row.get("factor") or 1.0),
            "category_id": row.get("category_id"),
            "uom_type": row.get("uom_type"),
        }
        by_id[iid] = item
        by_name[_normalize_key(name)] = item
        canon = _canonical_um(name)
        if canon:
            by_name[_normalize_key(canon)] = item
    for alias, target in _UM_ALIASES.items():
        tgt = by_name.get(_normalize_key(target))
        if tgt:
            by_name[_normalize_key(alias)] = tgt
    return {"by_name": by_name, "by_id": by_id}


_uom_cache: Dict[str, Any] = {"ts": 0.0, "data": None}
_UOM_TTL = 600.0


def get_uom_catalog() -> Dict[str, Dict[str, Any]]:
    now = time.time()
    if _uom_cache["data"] and now - float(_uom_cache["ts"]) < _UOM_TTL:
        return _uom_cache["data"]
    if not is_purchase_odoo_configured():
        return {"by_name": {}, "by_id": {}}
    data = _fetch_uom_catalog()
    _uom_cache["ts"] = now
    _uom_cache["data"] = data
    return data


def resolve_uom(raw: Any, catalog: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    key = _normalize_key(_canonical_um(raw) or raw)
    if not key:
        return None
    return (catalog.get("by_name") or {}).get(key)


def convert_qty(qty: float, from_uom: Dict[str, Any], to_uom: Dict[str, Any]) -> Optional[float]:
    if qty is None:
        return None
    cat_from = from_uom.get("category_id")
    cat_to = to_uom.get("category_id")
    if not cat_from or not cat_to:
        return None
    if cat_from[0] != cat_to[0]:
        return None
    f_from = float(from_uom.get("factor") or 1.0)
    f_to = float(to_uom.get("factor") or 1.0)
    if f_from == 0:
        return None
    # Odoo: qty_dest = qty_orig * (factor_dest / factor_orig)
    return qty * (f_to / f_from)


_po_cache: Dict[int, Dict[str, Any]] = {}


def _resolve_po_partner_scope(partner_id: int) -> int:
    """Usa commercial_partner_id para incluir OCs en contactos hijos del mismo proveedor."""
    rows = odoo_search_read(
        "res.partner",
        [("id", "=", partner_id)],
        ["commercial_partner_id"],
        limit=1,
        config=_purchase_odoo_config(),
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
    """OC confirmadas con recepción iniciada (excluye receipt_status=pending / «No recibido»)."""
    return [
        ("partner_id", "child_of", scope_id),
        ("state", "in", ["purchase", "done"]),
        ("receipt_status", "!=", "pending"),
    ]


def fetch_partner_po_lines(partner_id: int, *, limit_orders: int = 12) -> List[Dict[str, Any]]:
    if partner_id in _po_cache:
        return _po_cache[partner_id]["lines"]

    if not is_purchase_odoo_configured():
        _po_cache[partner_id] = {"lines": []}
        return []

    cfg = _purchase_odoo_config()
    scope_id = _resolve_po_partner_scope(partner_id)
    po_domain = _partner_po_search_domain(scope_id)
    orders = odoo_search_read(
        "purchase.order",
        po_domain,
        ["id", "name", "partner_ref", "date_order"],
        limit=limit_orders,
        order="date_order desc, id desc",
        config=cfg,
    )
    if not orders:
        _po_cache[partner_id] = {"lines": []}
        return []

    order_ids = [int(o["id"]) for o in orders]
    order_by_id = {int(o["id"]): o for o in orders}
    lines = odoo_search_read(
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
                "line_name": _normalize(ln.get("name")),
                "product_id": product_id,
                "product_qty": float(ln.get("product_qty") or 0),
                "qty_received": float(ln.get("qty_received") or 0),
                "qty_invoiced": float(ln.get("qty_invoiced") or 0),
                "price_unit": float(ln.get("price_unit") or 0),
                "product_uom_id": int(uom[0]) if isinstance(uom, (list, tuple)) and uom else None,
                "product_uom_name": uom[1] if isinstance(uom, (list, tuple)) and len(uom) > 1 else "",
            }
        )
    _po_cache[partner_id] = {"lines": enriched}
    return enriched


def _line_match_score(
    *,
    codigo: str,
    descripcion: str,
    qty: Optional[float],
    po_line: Dict[str, Any],
) -> float:
    code = _normalize_key(codigo)
    desc = _normalize(descripcion)
    po_name = _normalize(po_line.get("line_name"))
    if not po_name:
        return 0.0

    if code and code not in {"1", "NO DISPONIBLE", "NONE", "NULL"}:
        if code == _normalize_key(po_name):
            return 100.0
        if code in _normalize_key(po_name) or _normalize_key(po_name) in code:
            return 92.0

    if desc and po_name:
        po_upper = po_name.upper()
        po_tokens = [t for t in re.split(r"[\s/\-]+", po_upper) if len(t) >= 3]
        best_sc = 0.0
        for desc_variant in _desc_match_variants(desc):
            sc = float(fuzz.token_set_ratio(desc_variant, po_upper))
            best_sc = max(best_sc, sc)
            if sc >= 80:
                return sc
            # tokens cortos tipo "pan" vs "ALM-PAN FRANCES" (con OCR fix en CHOCL0→CHOCLO)
            for dt in _split_desc_tokens(desc_variant):
                for pt in po_tokens:
                    if dt in pt or pt in dt:
                        best_sc = max(best_sc, 75.0)
            best_sc = max(best_sc, float(fuzz.partial_ratio(desc_variant, po_upper)))
        if best_sc >= 75.0:
            return best_sc
        if best_sc > 0:
            return best_sc

    if qty is not None and po_line.get("product_qty"):
        if abs(float(qty) - float(po_line["product_qty"])) <= 0.01:
            partial_best = 0.0
            for desc_variant in _desc_match_variants(desc):
                partial_best = max(partial_best, float(fuzz.partial_ratio(desc_variant, po_name.upper())))
            return max(55.0, partial_best)

    if desc:
        partial_best = 0.0
        for desc_variant in _desc_match_variants(desc):
            partial_best = max(partial_best, float(fuzz.partial_ratio(desc_variant, po_name.upper())))
        return partial_best
    return 0.0


def _compose_match_note(*parts: str) -> str:
    out: List[str] = []
    seen = set()
    for raw in parts:
        p = _normalize(raw)
        if not p or p in seen:
            continue
        seen.add(p)
        out.append(p)
    return " · ".join(out)


def _apply_uom_scaling(
    row: Dict[str, Any],
    *,
    invoice_qty: Optional[float],
    invoice_um_raw: str,
    po_uom_id: Optional[int],
    po_uom_name: str,
    uom_catalog: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "um_proveedor": invoice_um_raw or "",
        "um_empresa": po_uom_name or "",
        "qty_original": "" if invoice_qty is None else str(invoice_qty),
        "qty_escalada": "" if invoice_qty is None else str(invoice_qty),
        "um_factor": "",
        "um_note": "",
    }
    if invoice_qty is None:
        return out

    from_uom = resolve_uom(invoice_um_raw, uom_catalog)
    to_uom = None
    if po_uom_id:
        to_uom = (uom_catalog.get("by_id") or {}).get(int(po_uom_id))
    if not to_uom and po_uom_name:
        to_uom = resolve_uom(po_uom_name, uom_catalog)

    if not from_uom or not to_uom:
        if not invoice_um_raw and po_uom_name:
            out["um_note"] = "Sin UM en factura"
        elif invoice_um_raw and po_uom_name and _normalize_key(invoice_um_raw) != _normalize_key(po_uom_name):
            out["um_note"] = "UM sin mapeo"
        return out

    if int(from_uom["id"]) == int(to_uom["id"]):
        out["um_empresa"] = to_uom.get("name") or po_uom_name
        out["um_factor"] = "1"
        return out

    converted = convert_qty(invoice_qty, from_uom, to_uom)
    if converted is None:
        out["um_note"] = "Categoría UM distinta"
        return out

    factor = converted / invoice_qty if invoice_qty else 1.0
    out["qty_escalada"] = f"{converted:.6g}".rstrip("0").rstrip(".")
    out["um_empresa"] = to_uom.get("name") or po_uom_name
    out["um_factor"] = f"{factor:.6g}".rstrip("0").rstrip(".")
    out["um_note"] = "Re-escalado"
    return out


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
        "__qty_original": "",
        "__qty_escalada": "",
        "__um_factor": "",
        "__um_note": "",
        "__oc_order_id": "",
        "__oc_line_id": "",
        "__selected_oc_order_id": "",
        "__selected_oc_name": "",
    }


def _min_match_score(codigo: str) -> float:
    return 70.0 if _normalize_key(codigo) not in {"", "1", "NO DISPONIBLE"} else 75.0


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


def score_oc_candidates(
    comprobante_rows: List[Dict[str, Any]],
    po_lines: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Rankea OCs del proveedor según matching de la canasta (líneas del comprobante)."""
    content_rows = [r for r in comprobante_rows if _is_content_row(r)]
    lines_total = len(content_rows)
    if not lines_total or not po_lines:
        return []

    by_order = _group_po_lines_by_order(po_lines)
    candidates: List[Dict[str, Any]] = []

    for order_id, oc_lines in by_order.items():
        first = oc_lines[0]
        lines_matched = 0
        score_sum = 0.0
        po_line_details: List[Dict[str, Any]] = []
        best_invoice_by_line: Dict[int, Dict[str, Any]] = {}

        for inv_row in content_rows:
            ctx = _row_match_context(inv_row)
            min_score = _min_match_score(ctx["codigo"])
            best_sc = 0.0
            best_po: Optional[Dict[str, Any]] = None
            for po in oc_lines:
                sc = _line_match_score(
                    codigo=ctx["codigo"],
                    descripcion=ctx["descripcion"],
                    qty=ctx["qty"],
                    po_line=po,
                )
                if sc > best_sc:
                    best_sc = sc
                    best_po = po
            if best_po and best_sc >= min_score:
                lines_matched += 1
                score_sum += best_sc
                lid = int(best_po["line_id"])
                prev = best_invoice_by_line.get(lid)
                if not prev or best_sc > float(prev.get("score") or 0):
                    best_invoice_by_line[lid] = {
                        "invoice_desc": ctx["descripcion"],
                        "score": best_sc,
                    }

        for po in oc_lines:
            lid = int(po["line_id"])
            inv_match = best_invoice_by_line.get(lid)
            po_line_details.append(
                {
                    "line_id": lid,
                    "line_name": po.get("line_name") or "",
                    "product_qty": po.get("product_qty", 0),
                    "qty_received": po.get("qty_received", 0),
                    "qty_invoiced": po.get("qty_invoiced", 0),
                    "price_unit": po.get("price_unit", 0),
                    "product_uom_name": po.get("product_uom_name") or "",
                    "invoice_match": inv_match,
                }
            )

        basket_score = score_sum / lines_total if lines_total else 0.0
        candidates.append(
            {
                "order_id": order_id,
                "order_name": first.get("order_name") or "",
                "partner_ref": first.get("partner_ref") or "",
                "date_order": first.get("date_order") or "",
                "basket_score": round(basket_score, 1),
                "lines_matched": lines_matched,
                "lines_total": lines_total,
                "score_sum": round(score_sum, 1),
                "lines": po_line_details,
            }
        )

    candidates.sort(
        key=lambda c: (c["lines_matched"], c["score_sum"], c["basket_score"]),
        reverse=True,
    )
    return candidates


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
) -> int:
    """Matchea líneas del comprobante contra la OC elegida. Devuelve filas matcheadas."""
    scoped = (
        [p for p in po_lines if int(p.get("order_id") or 0) == selected_order_id]
        if selected_order_id
        else []
    )
    matched = 0
    used_po_line_ids: set = set()
    for row in comprobante_rows:
        saved_sel = {
            "__selected_oc_order_id": row.get("__selected_oc_order_id", ""),
            "__selected_oc_name": row.get("__selected_oc_name", ""),
        }
        if not _is_content_row(row):
            row.update(_empty_purchase_fields())
            row.update(saved_sel)
            continue
        row.update(_empty_purchase_fields())
        row.update(saved_sel)
        match_fields = match_invoice_row(row, scoped, uom_catalog)
        po_line_raw = match_fields.get("__oc_line_id")
        if po_line_raw and str(po_line_raw).isdigit():
            po_line_int = int(po_line_raw)
            if po_line_int in used_po_line_ids:
                match_fields["__oc_line_id"] = ""
                match_fields["__oc_match_note"] = _compose_match_note(
                    match_fields.get("__oc_match_note") or "",
                    "Línea OC ya asignada a otra fila",
                )
            else:
                used_po_line_ids.add(po_line_int)
        row.update(match_fields)
        row.update(saved_sel)
        if match_fields.get("__oc_line_id"):
            matched += 1
    return matched


def _is_content_row(row: Dict[str, Any]) -> bool:
    if row.get("__solo_encabezado"):
        return False
    desc = _normalize(row.get("invoice_line_ids/name"))
    qty = _parse_amount(row.get("invoice_line_ids/quantity"))
    return bool(desc or qty is not None)


def match_invoice_row(
    row: Dict[str, Any],
    po_lines: List[Dict[str, Any]],
    uom_catalog: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    codigo = _normalize(row.get("__item_codigo") or row.get("invoice_line_ids/name"))
    desc = _normalize(row.get("invoice_line_ids/name") or row.get("Nombre de producto"))
    qty, um_raw = _resolve_invoice_qty_um(row, desc, repair_row=True)

    best: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for po in po_lines:
        sc = _line_match_score(codigo=codigo, descripcion=desc, qty=qty, po_line=po)
        if sc > best_score:
            best_score = sc
            best = {**po, "score": sc}

    result: Dict[str, Any] = _empty_purchase_fields()
    result["__um_proveedor"] = um_raw
    result["__qty_original"] = "" if qty is None else str(qty)
    result["__qty_escalada"] = "" if qty is None else str(qty)

    min_score = _min_match_score(codigo)
    if not best or best_score < min_score:
        result["__oc_match_note"] = _compose_match_note(
            "Sin match OC" if po_lines else "Sin OC en Odoo",
            result.get("__um_note") or "",
        )
        return result

    uom_info = _apply_uom_scaling(
        row,
        invoice_qty=qty,
        invoice_um_raw=um_raw,
        po_uom_id=best.get("product_uom_id"),
        po_uom_name=best.get("product_uom_name") or "",
        uom_catalog=uom_catalog,
    )

    oc_note = f"OC {best.get('order_name') or ''} · {best.get('line_name') or ''}".strip(" ·")
    result.update(
        {
            "__oc_name": best.get("order_name") or "",
            "__oc_partner_ref": best.get("partner_ref") or "",
            "__oc_line_name": best.get("line_name") or "",
            "__oc_match_score": f"{best_score:.0f}",
            "__qty_pedido": f"{best.get('product_qty', 0):g}",
            "__qty_recibido": f"{best.get('qty_received', 0):g}",
            "__qty_facturado_po": f"{best.get('qty_invoiced', 0):g}",
            "__oc_order_id": str(best.get("order_id") or ""),
            "__oc_line_id": str(best.get("line_id") or ""),
            "__um_proveedor": uom_info.get("um_proveedor") or um_raw,
            "__um_empresa": uom_info.get("um_empresa") or "",
            "__qty_original": uom_info.get("qty_original") or result["__qty_original"],
            "__qty_escalada": uom_info.get("qty_escalada") or result["__qty_escalada"],
            "__um_factor": uom_info.get("um_factor") or "",
            "__um_note": uom_info.get("um_note") or "",
        }
    )

    if uom_info.get("um_note") == "Re-escalado" and uom_info.get("qty_escalada"):
        row["invoice_line_ids/quantity"] = uom_info["qty_escalada"]

    product_id = best.get("product_id")
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


def enrich_rows_with_purchase_data(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Enriquece filas UI con OC, comparación pedido/recibido/facturado y re-escalado UM.
    Devuelve resumen para debug/API.
    """
    summary: Dict[str, Any] = {
        "enabled": False,
        "partners": 0,
        "rows_matched": 0,
        "rows_total": 0,
        "show_purchase_columns": False,
        "oc_candidates_by_comprobante": {},
        "selected_oc_by_comprobante": {},
    }
    if not rows or not is_purchase_odoo_configured():
        return summary

    summary["enabled"] = True
    _propagate_partner_for_matching(rows)
    uom_catalog = get_uom_catalog()
    partner_lines: Dict[int, List[Dict[str, Any]]] = {}
    oc_detected_names: List[str] = []

    for comprobante_rows in _group_rows_by_comprobante(rows).values():
        content_rows = [r for r in comprobante_rows if _is_content_row(r)]
        summary["rows_total"] += len(content_rows)
        if not content_rows:
            continue

        partner_raw = ""
        for row in comprobante_rows:
            pid = _normalize(row.get("partner_id"))
            if pid:
                partner_raw = pid
                break

        if not partner_raw.isdigit():
            for row in content_rows:
                row.update(_empty_purchase_fields())
                row["__oc_match_note"] = "Sin proveedor Odoo"
            continue

        partner_id = int(partner_raw)
        if partner_id not in partner_lines:
            partner_lines[partner_id] = fetch_partner_po_lines(partner_id)
            summary["partners"] += 1

        po_lines = partner_lines[partner_id]
        candidates = score_oc_candidates(comprobante_rows, po_lines)
        comp_idx = comprobante_rows[0].get("__comprobante_idx")
        comp_key = str(comp_idx) if comp_idx is not None else "0"
        summary["oc_candidates_by_comprobante"][comp_key] = candidates

        saved_oid = _saved_oc_order_id(comprobante_rows)
        selected_oid, selected_name = _resolve_selected_oc(candidates, saved_oid)
        if selected_oid:
            summary["selected_oc_by_comprobante"][comp_key] = selected_oid
            _set_comprobante_oc_selection(comprobante_rows, selected_oid, selected_name)
            if selected_name:
                oc_detected_names.append(selected_name)

        matched = _match_comprobante_rows(
            comprobante_rows, po_lines, uom_catalog, selected_oid
        )
        summary["rows_matched"] += matched

    summary["oc_detected"] = oc_detected_names[0] if oc_detected_names else ""
    summary["show_purchase_columns"] = has_any_oc_candidates(
        summary["oc_candidates_by_comprobante"]
    )
    return summary


def apply_oc_selection(
    rows: List[Dict[str, Any]],
    comprobante_idx: Any,
    order_id: int,
) -> Dict[str, Any]:
    """Aplica selección manual de OC y re-matchea solo ese comprobante."""
    groups = _group_rows_by_comprobante(rows)
    comprobante_rows = groups.get(comprobante_idx) or groups.get(str(comprobante_idx))
    if not comprobante_rows:
        raise ValueError(f"Comprobante {comprobante_idx} no encontrado.")

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
    po_lines = fetch_partner_po_lines(partner_id)
    candidates = score_oc_candidates(comprobante_rows, po_lines)
    order_name = ""
    for c in candidates:
        if int(c["order_id"]) == int(order_id):
            order_name = c.get("order_name") or ""
            break

    _set_comprobante_oc_selection(comprobante_rows, int(order_id), order_name)
    uom_catalog = get_uom_catalog()
    _match_comprobante_rows(comprobante_rows, po_lines, uom_catalog, int(order_id))
    return enrich_rows_with_purchase_data(rows)


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
    groups = _group_rows_by_comprobante(rows)
    comprobante_rows = groups.get(comprobante_idx) or groups.get(str(comprobante_idx))
    if not comprobante_rows:
        raise ValueError(f"Comprobante {comprobante_idx} no encontrado.")

    clear_comprobante_purchase_fields(comprobante_rows)
    _propagate_partner_for_matching(rows)
    return enrich_rows_with_purchase_data(rows)


def clear_purchase_cache() -> None:
    _po_cache.clear()
    _uom_cache["ts"] = 0.0
    _uom_cache["data"] = None
