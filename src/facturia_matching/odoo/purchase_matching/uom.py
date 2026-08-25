"""Catálogo UM Odoo, resolución y re-escalado de cantidades."""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

from facturia_matching.odoo.purchase_matching._util import (
    _normalize,
    _normalize_key,
    _parse_amount,
    _pkg,
    _tenant_cache_key,
)

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
    "TN": "Ton",
    "TON": "Ton",
    "TONELADA": "Ton",
    "TONELADAS": "Ton",
}

# Odoo traduce algunos nombres de uom.uom (es_419: 'Unidades', 'Tonelada'): al indexar
# los alias hay que aceptar cualquier variante de idioma del nombre destino.
_UOM_NAME_SYNONYMS: Dict[str, Tuple[str, ...]] = {
    "Units": ("Units", "Unidades", "Unidad"),
    "Ton": ("Ton", "Tonelada", "Toneladas"),
}

_QTY_UM_IN_DESC = re.compile(
    r"(?P<qty>\d+(?:[.,]\d+)?)\s*(?P<um>kg|kgs|kilos?|grs?|g|l|lt|litros?|un|unid(?:ades?)?)\b",
    re.I,
)
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
    # «X 500 G» en la descripción es tamaño de envase, no UM facturada.
    # Solo tomamos UM del texto si no hay cantidad de línea/FacturIA.
    if desc_um and not um_raw and fac_qty is None and invoice_qty is None:
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


def _catalog_add_name(
    by_name: Dict[str, List[Dict[str, Any]]], key: str, item: Dict[str, Any]
) -> None:
    """Indexa UM por nombre; permite colisiones (mismo nombre en distintas categorías)."""
    if not key:
        return
    bucket = by_name.setdefault(key, [])
    iid = int(item["id"])
    if any(int(u.get("id") or 0) == iid for u in bucket):
        return
    bucket.append(item)


def _by_name_candidates(
    catalog: Dict[str, Dict[str, Any]], key: str
) -> List[Dict[str, Any]]:
    """Lista de UOMs para una clave; acepta by_name legado (dict único) o lista."""
    if not key:
        return []
    raw = (catalog.get("by_name") or {}).get(key)
    if not raw:
        return []
    if isinstance(raw, dict):
        return [raw]
    return list(raw)


def _prefer_uom(candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda u: (
            0 if (u.get("uom_type") or "") == "reference" else 1,
            int(u.get("id") or 0),
        ),
    )[0]


# Odoo 19 rehizo uom.uom: sin category_id ni uom_type, con árbol relative_uom_id +
# relative_factor (y factor = razón a la raíz del árbol). Se normaliza al shape histórico
# — category_id = raíz del árbol, factor con semántica ≤ 18 — para no tocar convert_qty.
_UOM_LEGACY_FIELDS = ["id", "name", "uom_type", "factor", "category_id"]
_UOM_RELATIVE_FIELDS = ["id", "name", "factor", "relative_factor", "relative_uom_id"]

_uom_model_relative_cache: Dict[str, bool] = {}


def _uom_model_is_relative() -> bool:
    """True si el tenant es Odoo 19 (uom.uom por árbol en vez de categorías)."""
    pm = _pkg()
    key = pm._tenant_cache_key()
    if key in _uom_model_relative_cache:
        return _uom_model_relative_cache[key]
    fields = pm.odoo_model_field_names("uom.uom", pm._purchase_odoo_config())
    relative = bool(fields) and "category_id" not in fields and "relative_uom_id" in fields
    if fields:
        _uom_model_relative_cache[key] = relative
    return relative


def _relative_parent_id(row: Dict[str, Any]) -> Optional[int]:
    ref = row.get("relative_uom_id")
    if isinstance(ref, (list, tuple)) and ref:
        return int(ref[0])
    return None


def _missing_parent_ids(nodes: Dict[int, Dict[str, Any]]) -> List[int]:
    missing = set()
    for row in nodes.values():
        pid = _relative_parent_id(row)
        if pid is not None and pid not in nodes:
            missing.add(pid)
    return sorted(missing)


def _fetch_archived_uom_parents(
    raw: Dict[int, Dict[str, Any]]
) -> Dict[int, Dict[str, Any]]:
    """Padres archivados: no vienen en search_read y sin ellos no se llega a la raíz."""
    extra: Dict[int, Dict[str, Any]] = {}
    # Las cadenas son cortas (g → kg → tonelada); el tope corta ciclos o datos raros.
    for _ in range(5):
        missing = _missing_parent_ids({**extra, **raw})
        if not missing:
            break
        rows = _pkg().odoo_search_read(
            "uom.uom",
            [("id", "in", missing)],
            _UOM_RELATIVE_FIELDS,
            limit=len(missing),
            config=_pkg()._purchase_odoo_config(),
            context={"active_test": False},
        )
        fetched = {int(r["id"]): r for r in rows or [] if r.get("id") is not None}
        if not fetched:
            break
        extra.update(fetched)
    return extra


def _uom_root_and_ratio(
    row: Dict[str, Any], nodes: Dict[int, Dict[str, Any]]
) -> Tuple[int, str, float]:
    """(id raíz, nombre raíz, unidades raíz por 1 de esta UM)."""
    ratio = 1.0
    current = row
    seen = {int(row["id"])}
    while True:
        pid = _relative_parent_id(current)
        if pid is None or pid in seen:
            break
        parent = nodes.get(pid)
        if parent is None:
            break
        ratio *= float(current.get("relative_factor") or 1.0)
        seen.add(pid)
        current = parent
    # factor ya es la razón acumulada a la raíz y sobrevive a padres inaccesibles.
    stored = float(row.get("factor") or 0.0)
    if stored > 0:
        ratio = stored
    return int(current["id"]), _normalize(current.get("name")), ratio


def _relative_uom_items(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    raw = {int(r["id"]): r for r in rows or [] if r.get("id") is not None}
    nodes = {**_fetch_archived_uom_parents(raw), **raw}
    items: List[Dict[str, Any]] = []
    for iid, row in raw.items():
        root_id, root_name, ratio = _uom_root_and_ratio(row, nodes)
        if ratio <= 0:
            ratio = 1.0
        if root_id == iid:
            uom_type = "reference"
        else:
            uom_type = "bigger" if ratio > 1 else "smaller"
        items.append(
            {
                "id": iid,
                "name": _normalize(row.get("name")),
                # ≤ 18: factor = cuántas de esta UM entran en la unidad de referencia.
                "factor": 1.0 / ratio,
                "category_id": [root_id, root_name],
                "uom_type": uom_type,
            }
        )
    return items


def _legacy_uom_items(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "id": int(row["id"]),
            "name": _normalize(row.get("name")),
            "factor": float(row.get("factor") or 1.0),
            "category_id": row.get("category_id"),
            "uom_type": row.get("uom_type"),
        }
        for row in rows or []
        if row.get("id") is not None
    ]


def _fetch_uom_catalog() -> Dict[str, Dict[str, Any]]:
    pm = _pkg()
    relative = pm._uom_model_is_relative()
    rows = pm.odoo_search_read(
        "uom.uom",
        [],
        _UOM_RELATIVE_FIELDS if relative else _UOM_LEGACY_FIELDS,
        limit=500,
        config=pm._purchase_odoo_config(),
    )
    items = _relative_uom_items(rows) if relative else _legacy_uom_items(rows)
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    by_id: Dict[int, Dict[str, Any]] = {}
    for item in items:
        by_id[int(item["id"])] = item
        _catalog_add_name(by_name, _normalize_key(item["name"]), item)
        canon = _canonical_um(item["name"])
        if canon:
            _catalog_add_name(by_name, _normalize_key(canon), item)
    for alias, target in _UM_ALIASES.items():
        for target_name in _UOM_NAME_SYNONYMS.get(target, (target,)):
            for tgt in by_name.get(_normalize_key(target_name)) or []:
                _catalog_add_name(by_name, _normalize_key(alias), tgt)
    return {"by_name": by_name, "by_id": by_id}


# Caches por tenant (base_url|db): los ids de uom/product/PO no son portables entre perfiles Odoo.
_uom_cache: Dict[str, Dict[str, Any]] = {}
_UOM_TTL = 600.0


def get_uom_catalog() -> Dict[str, Dict[str, Any]]:
    pm = _pkg()
    now = time.time()
    key = pm._tenant_cache_key()
    entry = _uom_cache.get(key)
    if entry and entry.get("data") and now - float(entry.get("ts") or 0.0) < _UOM_TTL:
        return entry["data"]
    if not pm.is_purchase_odoo_configured():
        return {"by_name": {}, "by_id": {}}
    data = pm._fetch_uom_catalog()
    _uom_cache[key] = {"ts": now, "data": data}
    return data


def resolve_uom(raw: Any, catalog: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Resuelve UM por nombre/alias. Si hay colisión entre categorías, prefiere reference + id menor."""
    key = _normalize_key(_canonical_um(raw) or raw)
    if not key:
        return None
    return _prefer_uom(_by_name_candidates(catalog, key))


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


_product_uom_cache: Dict[str, Dict[int, Optional[int]]] = {}

def _category_id(uom: Dict[str, Any]) -> Optional[int]:
    cat = uom.get("category_id")
    if isinstance(cat, (list, tuple)) and cat:
        return int(cat[0])
    if isinstance(cat, int):
        return cat
    return None


def _product_default_uom_id(product_id: int) -> Optional[int]:
    pm = _pkg()
    tenant_cache = _product_uom_cache.setdefault(pm._tenant_cache_key(), {})
    if product_id in tenant_cache:
        return tenant_cache[product_id]
    if not pm.is_purchase_odoo_configured():
        tenant_cache[product_id] = None
        return None
    # Odoo 19 eliminó uom_po_id (la UM de compra se unificó en uom_id).
    fields = pm.odoo_available_fields(
        "product.product", ["uom_id", "uom_po_id"], pm._purchase_odoo_config()
    )
    rows = pm.odoo_search_read(
        "product.product",
        [("id", "=", product_id)],
        fields,
        limit=1,
        config=pm._purchase_odoo_config(),
    )
    uom_id: Optional[int] = None
    if rows:
        uom_ref = rows[0].get("uom_po_id") or rows[0].get("uom_id")
        if isinstance(uom_ref, (list, tuple)) and uom_ref:
            uom_id = int(uom_ref[0])
    tenant_cache[product_id] = uom_id
    return uom_id


def _find_uom_in_category(
    raw_um: str,
    category_id: Optional[int],
    catalog: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Matchea UM de factura contra UOMs de una categoría Odoo.
    None si no hay match por nombre (no cae al default del producto).
    """
    key = _normalize_key(_canonical_um(raw_um) or raw_um)
    if not key:
        return None
    candidates = _by_name_candidates(catalog, key)
    if category_id is not None:
        in_cat = [u for u in candidates if _category_id(u) == int(category_id)]
        if in_cat:
            return _prefer_uom(in_cat)
        # Fallback: escanear by_id (nombres custom / catálogo legado sin listas)
        for uom in (catalog.get("by_id") or {}).values():
            if _category_id(uom) != int(category_id):
                continue
            names = {
                _normalize_key(uom.get("name")),
                _normalize_key(_canonical_um(uom.get("name"))),
            }
            if key in names:
                return uom
        return None
    return _prefer_uom(candidates) or resolve_uom(raw_um, catalog)


def _resolve_uom_in_product_category(
    raw_um: str,
    product_uom_id: int,
    catalog: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Matchea UM de factura contra UOMs de la categoría del producto Odoo."""
    by_id = catalog.get("by_id") or {}
    product_uom = by_id.get(int(product_uom_id))
    if not product_uom:
        return resolve_uom(raw_um, catalog)
    cat_id = _category_id(product_uom)
    found = _find_uom_in_category(raw_um, cat_id, catalog)
    if found:
        return found
    if not _normalize_key(_canonical_um(raw_um) or raw_um):
        return product_uom
    return product_uom


def list_uoms_for_product(product_id: int) -> List[Dict[str, Any]]:
    """
    UOMs de la categoría del producto (uom_po_id / uom_id).

    Sin uom_ids por producto en Dinner: la lista usable = misma category_id.
    """
    if not product_id:
        return []
    pm = _pkg()
    product_uom_id = pm._product_default_uom_id(int(product_id))
    if not product_uom_id:
        return []
    catalog = pm.get_uom_catalog()
    by_id = catalog.get("by_id") or {}
    product_uom = by_id.get(int(product_uom_id))
    if not product_uom:
        return []
    cat_id = _category_id(product_uom)
    if cat_id is None:
        return [{"id": int(product_uom["id"]), "name": product_uom.get("name") or ""}]
    out: List[Dict[str, Any]] = []
    for uom in by_id.values():
        if _category_id(uom) != cat_id:
            continue
        uid = uom.get("id")
        if uid is None:
            continue
        out.append({"id": int(uid), "name": uom.get("name") or ""})
    out.sort(key=lambda x: ((x.get("name") or "").lower(), int(x["id"])))
    return out


def _resolve_target_uom_for_product(
    product_id: int,
    uom_catalog: Dict[str, Dict[str, Any]],
    target_uom_id: Optional[int] = None,
    invoice_um_raw: str = "",
) -> Optional[Dict[str, Any]]:
    """UM destino: elegida a mano, kg de factura si aplica, o uom_po default.

    PDF Gran Crianza: si FacturIA trae KG y el producto tiene UM de peso en la
    misma categoría, preferir kg sobre el pack/unidad de compra (uom_po).
    """
    product_uom_id = _pkg()._product_default_uom_id(product_id)
    by_id = uom_catalog.get("by_id") or {}
    default_uom = by_id.get(int(product_uom_id)) if product_uom_id else None
    if target_uom_id is not None:
        candidate = by_id.get(int(target_uom_id))
        if candidate:
            if default_uom is None or _category_id(candidate) == _category_id(default_uom):
                return candidate
    inv_canon = _normalize_key(_canonical_um(invoice_um_raw) or invoice_um_raw)
    if inv_canon in {"KG", "G", "GR", "GRS"} and default_uom is not None:
        cat_id = _category_id(default_uom)
        found = _find_uom_in_category(invoice_um_raw or inv_canon, cat_id, uom_catalog)
        if found:
            return found
    return default_uom


def _apply_uom_scaling_for_product(
    row: Dict[str, Any],
    *,
    invoice_qty: Optional[float],
    invoice_um_raw: str,
    product_id: int,
    uom_catalog: Dict[str, Dict[str, Any]],
    target_uom_id: Optional[int] = None,
) -> Dict[str, Any]:
    to_uom = _resolve_target_uom_for_product(
        product_id,
        uom_catalog,
        target_uom_id,
        invoice_um_raw=invoice_um_raw,
    )
    if not to_uom:
        return {
            "um_proveedor": invoice_um_raw or "",
            "um_empresa": "",
            "um_empresa_id": "",
            "qty_original": "" if invoice_qty is None else str(invoice_qty),
            "qty_escalada": "" if invoice_qty is None else str(invoice_qty),
            "um_factor": "",
            "um_note": "Sin UM producto",
        }
    company_name = to_uom.get("name") or ""
    return _apply_uom_scaling(
        row,
        invoice_qty=invoice_qty,
        invoice_um_raw=invoice_um_raw,
        po_uom_id=int(to_uom["id"]) if to_uom.get("id") is not None else None,
        po_uom_name=company_name,
        uom_catalog=uom_catalog,
    )


def apply_product_uom_to_row(
    row: Dict[str, Any],
    product_id: Optional[int] = None,
    uom_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Recalcula UM para una fila tras elegir/borrar producto o elegir UM a mano.

    Sin uom_id: usa uom_po_id del producto (mismo camino que match automático).
    Con uom_id: re-escala desde qty/UM original de factura hacia esa UM (misma
    categoría). Si no hay product_id, limpia __um_empresa_*. Devuelve los campos
    UM aplicados.
    """
    if not isinstance(row, dict):
        return {}
    pid = product_id
    if pid is None:
        raw = _normalize(row.get("invoice_line_ids/product_id"))
        pid = int(raw) if raw.isdigit() else None

    # Limpiar sugerencia de producto al fijar manualmente.
    row["__product_suggested"] = ""

    if not pid:
        row["__um_empresa"] = ""
        row["__um_empresa_id"] = ""
        row["__um_factor"] = ""
        row["__um_note"] = ""
        return {
            "um_empresa": "",
            "um_empresa_id": "",
            "um_factor": "",
            "um_note": "",
            "qty_escalada": row.get("invoice_line_ids/quantity") or "",
        }

    desc = _normalize(row.get("invoice_line_ids/name") or row.get("Nombre de producto"))
    # Selección manual de UM: partir de qty/UM original (no de qty ya re-escalada).
    if uom_id is not None:
        qty = _parse_amount(row.get("__qty_original"))
        um_raw = _normalize(row.get("__um_proveedor") or "")
        if qty is None:
            qty, resolved_um = _resolve_invoice_qty_um(row, desc, repair_row=True)
            if not um_raw:
                um_raw = resolved_um
    else:
        qty, um_raw = _resolve_invoice_qty_um(row, desc, repair_row=True)
        if not um_raw:
            um_raw = _normalize(row.get("__um_proveedor") or "")

    uom_catalog = _pkg().get_uom_catalog()
    uom_info = _apply_uom_scaling_for_product(
        row,
        invoice_qty=qty,
        invoice_um_raw=um_raw,
        product_id=int(pid),
        uom_catalog=uom_catalog,
        target_uom_id=int(uom_id) if uom_id is not None else None,
    )
    row["__um_proveedor"] = uom_info.get("um_proveedor") or um_raw
    row["__um_empresa"] = uom_info.get("um_empresa") or ""
    row["__um_empresa_id"] = uom_info.get("um_empresa_id") or ""
    row["__qty_original"] = uom_info.get("qty_original") or ("" if qty is None else str(qty))
    row["__qty_escalada"] = uom_info.get("qty_escalada") or row["__qty_original"]
    row["__um_factor"] = uom_info.get("um_factor") or ""
    row["__um_note"] = uom_info.get("um_note") or ""
    if uom_info.get("um_note") == "Re-escalado" and uom_info.get("qty_escalada"):
        row["invoice_line_ids/quantity"] = uom_info["qty_escalada"]
    elif uom_info.get("qty_escalada") and uom_id is not None:
        # Misma UM o factor 1: igual sincronizar qty visible con la escalada.
        row["invoice_line_ids/quantity"] = uom_info["qty_escalada"]
    return uom_info

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


def _stamp_target_uom(
    out: Dict[str, Any],
    to_uom: Optional[Dict[str, Any]],
    *,
    po_uom_name: str = "",
) -> None:
    """Marca UM destino (empresa/PO) para UI e import (`product_uom_id`)."""
    if not to_uom:
        return
    out["um_empresa"] = to_uom.get("name") or po_uom_name or out.get("um_empresa") or ""
    uom_id = to_uom.get("id")
    if uom_id is not None:
        out["um_empresa_id"] = str(int(uom_id))


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
        "um_empresa_id": "",
        "qty_original": "" if invoice_qty is None else str(invoice_qty),
        "qty_escalada": "" if invoice_qty is None else str(invoice_qty),
        "um_factor": "",
        "um_note": "",
    }
    to_uom = None
    if po_uom_id:
        to_uom = (uom_catalog.get("by_id") or {}).get(int(po_uom_id))
    if not to_uom and po_uom_name:
        to_uom = resolve_uom(po_uom_name, uom_catalog)

    if invoice_qty is None:
        # Sin qty aún: igual persistimos UM destino si la conocemos (import).
        _stamp_target_uom(out, to_uom, po_uom_name=po_uom_name)
        return out

    # Resolver UM factura dentro de la categoría del destino (evita colisión kg/L
    # entre categorías custom vs estándar, p.ej. Dinner Crema / LITROS).
    if to_uom:
        from_uom = _find_uom_in_category(
            invoice_um_raw, _category_id(to_uom), uom_catalog
        )
    else:
        from_uom = resolve_uom(invoice_um_raw, uom_catalog)

    if not from_uom or not to_uom:
        if not invoice_um_raw and to_uom:
            # Cantidad asumida en UM empresa/PO → sí mandamos product_uom_id.
            out["um_note"] = "Sin UM en factura"
            _stamp_target_uom(out, to_uom, po_uom_name=po_uom_name)
        elif invoice_um_raw and po_uom_name and _normalize_key(invoice_um_raw) != _normalize_key(po_uom_name):
            out["um_note"] = "UM sin mapeo"
        return out

    if int(from_uom["id"]) == int(to_uom["id"]):
        _stamp_target_uom(out, to_uom, po_uom_name=po_uom_name)
        out["um_factor"] = "1"
        return out

    converted = convert_qty(invoice_qty, from_uom, to_uom)
    if converted is None:
        out["um_note"] = "Categoría UM distinta"
        return out

    factor = converted / invoice_qty if invoice_qty else 1.0
    out["qty_escalada"] = f"{converted:.6g}".rstrip("0").rstrip(".")
    out["um_factor"] = f"{factor:.6g}".rstrip("0").rstrip(".")
    out["um_note"] = "Re-escalado"
    _stamp_target_uom(out, to_uom, po_uom_name=po_uom_name)
    return out
