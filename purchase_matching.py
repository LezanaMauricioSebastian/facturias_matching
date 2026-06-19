"""
Matching factura ↔ orden de compra Odoo + re-escalado de UM.

Se integra después del parseo FacturIA sin alterar el flujo CSV/import existente.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz, process as rf_process

from odoo_api import is_odoo_configured, odoo_search_read

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


def _fetch_uom_catalog() -> Dict[str, Dict[str, Any]]:
    rows = odoo_search_read(
        "uom.uom",
        [],
        ["id", "name", "uom_type", "factor", "category_id"],
        limit=500,
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
    if not is_odoo_configured():
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


def fetch_partner_po_lines(partner_id: int, *, limit_orders: int = 12) -> List[Dict[str, Any]]:
    if partner_id in _po_cache:
        return _po_cache[partner_id]["lines"]

    if not is_odoo_configured():
        _po_cache[partner_id] = {"lines": []}
        return []

    orders = odoo_search_read(
        "purchase.order",
        [("partner_id", "=", partner_id), ("state", "in", ["purchase", "done"])],
        ["id", "name", "partner_ref", "date_order"],
        limit=limit_orders,
        order="date_order desc, id desc",
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


def _pick_po_for_matches(matches: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not matches:
        return None
    by_order: Dict[int, Dict[str, Any]] = {}
    for m in matches:
        oid = int(m["order_id"])
        bucket = by_order.setdefault(
            oid,
            {
                "order_id": oid,
                "order_name": m.get("order_name") or "",
                "partner_ref": m.get("partner_ref") or "",
                "score_sum": 0.0,
                "count": 0,
            },
        )
        bucket["score_sum"] += float(m.get("score") or 0)
        bucket["count"] += 1
    ranked = sorted(by_order.values(), key=lambda x: (x["count"], x["score_sum"]), reverse=True)
    return ranked[0] if ranked else None


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
    }


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
    qty = _parse_amount(row.get("invoice_line_ids/quantity"))
    um_raw = _normalize(row.get("__um_proveedor") or "")

    desc_qty, desc_um = _extract_qty_um_from_description(desc)
    if desc_qty is not None:
        qty = desc_qty
        row["invoice_line_ids/quantity"] = f"{desc_qty:g}"
    if desc_um and not um_raw:
        um_raw = desc_um

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

    min_score = 70.0 if _normalize_key(codigo) not in {"", "1", "NO DISPONIBLE"} else 75.0
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
    """Copia partner_id del encabezado a líneas del mismo comprobante."""
    last_by_idx: Dict[Any, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        idx = row.get("__comprobante_idx")
        pid = _normalize(row.get("partner_id"))
        if pid:
            last_by_idx[idx] = pid
        elif idx in last_by_idx and not pid:
            row["partner_id"] = last_by_idx[idx]


def enrich_rows_with_purchase_data(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Enriquece filas UI con OC, comparación pedido/recibido/facturado y re-escalado UM.
    Devuelve resumen para debug/API.
    """
    summary = {"enabled": False, "partners": 0, "rows_matched": 0, "rows_total": 0}
    if not rows or not is_odoo_configured():
        return summary

    summary["enabled"] = True
    _propagate_partner_for_matching(rows)
    uom_catalog = get_uom_catalog()
    partner_lines: Dict[int, List[Dict[str, Any]]] = {}
    line_matches: List[Dict[str, Any]] = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        if not _is_content_row(row):
            continue
        summary["rows_total"] += 1
        row.update(_empty_purchase_fields())

        partner_raw = _normalize(row.get("partner_id"))
        if not partner_raw.isdigit():
            row["__oc_match_note"] = "Sin proveedor Odoo"
            continue
        partner_id = int(partner_raw)
        if partner_id not in partner_lines:
            partner_lines[partner_id] = fetch_partner_po_lines(partner_id)
            summary["partners"] += 1

        po_lines = partner_lines[partner_id]
        match_fields = match_invoice_row(row, po_lines, uom_catalog)
        row.update(match_fields)
        if match_fields.get("__oc_line_id"):
            line_matches.append(
                {
                    "order_id": int(match_fields["__oc_order_id"]),
                    "order_name": match_fields.get("__oc_name") or "",
                    "partner_ref": match_fields.get("__oc_partner_ref") or "",
                    "score": float(match_fields.get("__oc_match_score") or 0),
                }
            )
            summary["rows_matched"] += 1

    po_pick = _pick_po_for_matches(line_matches)
    if po_pick:
        matched_idxs = {
            row.get("__comprobante_idx")
            for row in rows
            if isinstance(row, dict) and row.get("__oc_line_id")
        }
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("__comprobante_idx") not in matched_idxs:
                continue
            if not row.get("__oc_name"):
                row["__oc_name"] = po_pick.get("order_name") or ""
            if not row.get("__oc_partner_ref"):
                row["__oc_partner_ref"] = po_pick.get("partner_ref") or ""

    summary["oc_detected"] = po_pick.get("order_name") if po_pick else ""
    return summary


def clear_purchase_cache() -> None:
    _po_cache.clear()
    _uom_cache["ts"] = 0.0
    _uom_cache["data"] = None
