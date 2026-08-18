"""
Matching factura ↔ orden de compra Odoo + re-escalado de UM.

Se integra después del parseo FacturIA sin alterar el flujo CSV/import existente.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from rapidfuzz import fuzz, process as rf_process

from facturia_matching.odoo.api import (
    clear_odoo_model_fields_cache,
    get_active_odoo_config,
    is_odoo_config_ready,
    odoo_available_fields,
    odoo_model_field_names,
    odoo_search_read,
)


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


# Tokens de envase / ruido que no discriminan producto.
_NOISE_MATCH_TOKENS = {
    "KG",
    "KG.",
    "UN",
    "UNID",
    "UNIDS",
    "LT",
    "LTS",
    "LTS.",
    "GR",
    "GRS",
    "UND",
    "UDS",
    "PACK",
    "CAJA",
    "BOLSA",
}
# Prefijos de categoría Odoo (ALM-, CON-, …) — no cuentan como overlap de producto.
_PREFIX_MATCH_TOKENS = {"ALM", "CON", "BEB", "MOT", "SER", "LIM", "CAR"}

# Pares de modificadores incompatibles (factura vs OC).
_CONFLICTING_MODIFIER_PAIRS: Tuple[Tuple[FrozenSet[str], FrozenSet[str]], ...] = (
    (
        frozenset({"SECO", "SECOS", "SECA", "SECAS"}),
        frozenset({"TRITURADO", "TRITURADA", "TRITURADOS", "TRITURADAS", "MOLIDO", "MOLIDA"}),
    ),
    (
        frozenset({"ENTERO", "ENTEROS", "ENTERA", "ENTERAS"}),
        frozenset({"FILETEADO", "FILETEADA", "FILETEADOS", "TROCADO", "TROCADA"}),
    ),
    (
        frozenset({"FRESCO", "FRESCA", "FRESCOS", "FRESCAS"}),
        frozenset({"CONGELADO", "CONGELADA", "CONGELADOS", "CONGELADAS"}),
    ),
)


def _content_match_tokens(tokens: List[str]) -> List[str]:
    out: List[str] = []
    for tok in tokens:
        key = tok.upper().rstrip(".")
        if key in _NOISE_MATCH_TOKENS or key in _PREFIX_MATCH_TOKENS:
            continue
        if key.isdigit():
            continue
        out.append(key)
    return out


def _has_conflicting_modifiers(inv_tokens: List[str], po_tokens: List[str]) -> bool:
    inv = set(_content_match_tokens(inv_tokens))
    po = set(_content_match_tokens(po_tokens))
    for left, right in _CONFLICTING_MODIFIER_PAIRS:
        if (inv & left and po & right) or (inv & right and po & left):
            return True
    return False


def _invoice_content_token_set(descripcion: str) -> set:
    return set(_content_match_tokens(_split_desc_tokens(_normalize(descripcion).upper())))


def _invoice_has_zero_token(descripcion: str) -> bool:
    """True si la etiqueta de factura es variante Zero (Coca Zero, etc.)."""
    return "ZERO" in _invoice_content_token_set(descripcion)


def _invoice_gas_flags(descripcion: str) -> Tuple[bool, bool]:
    """(sin_gas, con_gas) sobre la etiqueta de factura."""
    u = _normalize(descripcion).upper().replace("/", " ")
    toks = set(t for t in re.split(r"\s+", u) if t)
    still = "SIN" in toks and "GAS" in toks
    spark = (
        ("CON" in toks and "GAS" in toks) or ({"C", "G"} <= toks)
    ) and not still
    return still, spark


def _invoice_variant_conflict(a: str, b: str) -> bool:
    """ZERO vs no-ZERO, agua sin gas vs con gas (misma idea que memoria de producto)."""
    if (_invoice_has_zero_token(a)) != (_invoice_has_zero_token(b)):
        return True
    a_still, a_spark = _invoice_gas_flags(a)
    b_still, b_spark = _invoice_gas_flags(b)
    return (a_still and b_spark) or (b_still and a_spark)


def _soft_recount_allowed(
    inv_desc: str, po: Dict[str, Any], hard: Optional[Dict[str, Any]]
) -> bool:
    """El pase soft es para extra unidades del mismo SKU (3× PICADA), no variantes.

    Coca Zero no cuenta sobre la línea nota ``coca``; Benedictino C/G no cuenta
    sobre la línea ya matcheada a Benedictino sin gas.
    """
    if hard and _invoice_variant_conflict(inv_desc, str(hard.get("invoice_desc") or "")):
        return False
    notes = [_normalize(n) for n in (po.get("note_labels") or []) if _normalize(n)]
    if not notes:
        return True
    best_note = max(_score_dinner_note(inv_desc, n) for n in notes)
    # 70 = Coca Zero vs nota "coca": marca, no el mismo SKU.
    return best_note >= 100.0


_SODA_BRAND_RE = re.compile(r"\b(COCA|SPRITE|FANTA|PEPSI|SCHWEPPES)\b")


def _invoice_is_soda_brand(descripcion: str) -> bool:
    return bool(_SODA_BRAND_RE.search(_normalize(descripcion).upper()))


def _po_invoice_family_mismatch(po_name: str, descripcion: str) -> bool:
    """Gaseosa ≠ agua saborizada ≠ agua mineral (FANTA NARANJA ≠ nota naranja)."""
    po_u = _normalize_key(po_name)
    d = _normalize(descripcion).upper()
    soda = _invoice_is_soda_brand(descripcion)
    if "SABORIZ" in po_u and soda:
        return True
    if "GASEOSAS" in po_u and (
        "BENEDICTINO" in d or (not soda and ("AGUA" in d or "SIN GAS" in d or "C/G" in d))
    ):
        return True
    if "AGUA" in po_u and "SABORIZ" not in po_u and soda:
        return True
    return False


def _score_dinner_note(descripcion: str, note: str) -> float:
    """Score nota Dinner (coca/sprite/zero/…) vs etiqueta de factura.

    Notas cortas: solo token/contención real. Evita partial_ratio falso
    (p. ej. ACUERDO≈ZERO vía 'ERDO' → 75%).
    Si la factura es ZERO, la nota ``zero`` gana; ``coca`` queda por debajo.
    Notas multi-palabra: no alcanza un token suelto dentro de la nota
    (``GAS`` ∈ ``AGUA CON GAS`` no vale para Benedictino sin gas).
    """
    note_u = _normalize_key(note)
    desc = _normalize(descripcion)
    if not note_u or not desc:
        return 0.0
    desc_u = desc.upper()
    inv_tokens = _invoice_content_token_set(desc)
    inv_has_zero = "ZERO" in inv_tokens
    note_is_zero = (
        note_u == "ZERO"
        or note_u.startswith("ZERO")
        or "ZERO" in note_u.split()
    )
    n_still, n_spark = _invoice_gas_flags(note)
    i_still, i_spark = _invoice_gas_flags(desc)
    if (n_still and i_spark) or (n_spark and i_still):
        return 0.0
    waterish = "BENEDICTINO" in desc_u or "AGUA" in desc_u
    if (n_still or n_spark) and waterish and not _invoice_is_soda_brand(desc):
        if (n_still and i_still) or (n_spark and i_spark):
            return 100.0
        return 0.0

    if note_is_zero and not inv_has_zero:
        return 0.0

    note_parts = [t for t in re.split(r"[\s/\-]+", note_u) if len(t) >= 3 and t != "CON"]
    multi = len(note_parts) > 1

    hit = note_u in inv_tokens
    if not hit and multi:
        hit = all(
            any(p == tok or p in tok or tok in p for tok in inv_tokens)
            for p in note_parts
        )
    if not hit and not multi:
        for tok in inv_tokens:
            if len(note_u) >= 3 and len(tok) >= 3 and (note_u in tok or tok in note_u):
                hit = True
                break
    if not hit and re.search(rf"\b{re.escape(note_u)}\b", desc_u):
        hit = True

    if not hit:
        # Notas largas: token_set; nunca partial_ratio en notas cortas (falsos +).
        if len(note_u) >= 6:
            return float(fuzz.token_set_ratio(desc_u, note_u))
        return 0.0

    if inv_has_zero and not note_is_zero:
        # COCA-COLA ZERO vs nota "coca": brand match débil; "zero" debe ganar.
        return 70.0
    return 100.0


def _agua_affinity_score(descripcion: str, po_name: str) -> float:
    """Afinidad Benedictino/aguas ↔ línea BEB-AGUA C/S GAS (sin nota de sabor)."""
    po_u = _normalize_key(po_name)
    if "AGUA" not in po_u:
        return 0.0
    # Sabores (pera/pomelo) van por nota, no por afinidad genérica.
    if "SABORIZ" in po_u:
        return 0.0
    d = _normalize(descripcion).upper()
    # Gaseosas de marca no son agua mineral.
    if _invoice_is_soda_brand(descripcion):
        return 0.0
    if "AGUA" in d or "BENEDICTINO" in d:
        return 82.0
    water_hints = ("SIN GAS", "CON GAS", "C/G", "S/G", "VILLAVICENCIO", "GLACIAR", "ECO DE LOS ANDES")
    if any(h in d for h in water_hints):
        return 82.0
    return 0.0


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
    from facturia_matching.core.amounts import parse_amount_loose

    return parse_amount_loose(s)


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
    key = _tenant_cache_key()
    if key in _uom_model_relative_cache:
        return _uom_model_relative_cache[key]
    fields = odoo_model_field_names("uom.uom", _purchase_odoo_config())
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
        rows = odoo_search_read(
            "uom.uom",
            [("id", "in", missing)],
            _UOM_RELATIVE_FIELDS,
            limit=len(missing),
            config=_purchase_odoo_config(),
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
    relative = _uom_model_is_relative()
    rows = odoo_search_read(
        "uom.uom",
        [],
        _UOM_RELATIVE_FIELDS if relative else _UOM_LEGACY_FIELDS,
        limit=500,
        config=_purchase_odoo_config(),
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


def _tenant_cache_key() -> str:
    cfg = _purchase_odoo_config()
    return f"{cfg.get('base_url', '')}|{cfg.get('db', '')}"


def get_uom_catalog() -> Dict[str, Dict[str, Any]]:
    now = time.time()
    key = _tenant_cache_key()
    entry = _uom_cache.get(key)
    if entry and entry.get("data") and now - float(entry.get("ts") or 0.0) < _UOM_TTL:
        return entry["data"]
    if not is_purchase_odoo_configured():
        return {"by_name": {}, "by_id": {}}
    data = _fetch_uom_catalog()
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


_po_cache: Dict[str, Dict[int, Dict[str, Any]]] = {}
_product_uom_cache: Dict[str, Dict[int, Optional[int]]] = {}


def _category_id(uom: Dict[str, Any]) -> Optional[int]:
    cat = uom.get("category_id")
    if isinstance(cat, (list, tuple)) and cat:
        return int(cat[0])
    if isinstance(cat, int):
        return cat
    return None


def _product_default_uom_id(product_id: int) -> Optional[int]:
    tenant_cache = _product_uom_cache.setdefault(_tenant_cache_key(), {})
    if product_id in tenant_cache:
        return tenant_cache[product_id]
    if not is_purchase_odoo_configured():
        tenant_cache[product_id] = None
        return None
    # Odoo 19 eliminó uom_po_id (la UM de compra se unificó en uom_id).
    fields = odoo_available_fields(
        "product.product", ["uom_id", "uom_po_id"], _purchase_odoo_config()
    )
    rows = odoo_search_read(
        "product.product",
        [("id", "=", product_id)],
        fields,
        limit=1,
        config=_purchase_odoo_config(),
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
    product_uom_id = _product_default_uom_id(int(product_id))
    if not product_uom_id:
        return []
    catalog = get_uom_catalog()
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
    product_uom_id = _product_default_uom_id(product_id)
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

    uom_catalog = get_uom_catalog()
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
    if not is_purchase_odoo_configured():
        return []

    cfg = _purchase_odoo_config()
    scope_id = _resolve_po_partner_scope(partner_id)
    po_domain = _partner_po_search_domain(scope_id)
    orders = odoo_search_read(
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


# Dinner: líneas de producto en OC suelen verse como "[B0003] BEB-GASEOSAS".
_PO_BRACKET_CODE_RE = re.compile(r"^\[([^\]]+)\]")


def _po_line_has_bracket_code(name: Any) -> bool:
    return bool(_PO_BRACKET_CODE_RE.match(_normalize(name) or ""))


def _po_line_qty_zero(po: Dict[str, Any]) -> bool:
    return float(po.get("product_qty") or 0) <= 0 and float(po.get("qty_received") or 0) <= 0


def _attach_dinner_po_note_labels(po_lines: List[Dict[str, Any]]) -> None:
    """Heurística Dinner: qty pedida+recibida 0 bajo un padre con [CÓDIGO] = nota/etiqueta.

    La nota no se matchea sola: su texto se agrega a ``note_labels`` del padre
    (producto↔etiqueta). Escala mal en tenants sin ese patrón; en Dinner sí.
    """
    last_parent_by_order: Dict[int, Dict[str, Any]] = {}
    for ln in po_lines:
        if not isinstance(ln, dict):
            continue
        ln.setdefault("note_labels", [])
        ln["is_note"] = False
        oid = int(ln.get("order_id") or 0)
        parent = last_parent_by_order.get(oid)
        name = ln.get("line_name")
        if (
            parent is not None
            and _po_line_qty_zero(ln)
            and not _po_line_qty_zero(parent)
            and _po_line_has_bracket_code(parent.get("line_name"))
            and not _po_line_has_bracket_code(name)
        ):
            note = _normalize(name)
            if note:
                labels = parent.setdefault("note_labels", [])
                if note not in labels:
                    labels.append(note)
            ln["is_note"] = True
            ln["parent_line_id"] = parent.get("line_id")
            continue
        if not _po_line_qty_zero(ln):
            last_parent_by_order[oid] = ln


def _matchable_po_lines(po_lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [p for p in po_lines if isinstance(p, dict) and not p.get("is_note")]


def _line_match_score(
    *,
    codigo: str,
    descripcion: str,
    qty: Optional[float],
    po_line: Dict[str, Any],
) -> float:
    if po_line.get("is_note"):
        return 0.0
    # Probar también etiquetas/notas Dinner colgadas del padre.
    notes = [
        _normalize(n)
        for n in (po_line.get("note_labels") or [])
        if _normalize(n)
    ]
    if _po_invoice_family_mismatch(str(po_line.get("line_name") or ""), descripcion):
        return 0.0
    if notes:
        # Con notas Dinner, el match útil es etiqueta↔factura (coca/zero/…).
        # El nombre genérico (BEB-AGUA + afinidad 82) no debe tapar una nota
        # incompatible (agua con gas ≠ Benedictino sin gas).
        best = 0.0
        for note in notes:
            best = max(best, _score_dinner_note(descripcion, note))
        return best
    return _line_match_score_against_name(
        codigo=codigo, descripcion=descripcion, qty=qty, po_line=po_line
    )


def _line_match_score_against_name(
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

    best_sc = 0.0
    po_compact_len = len(re.sub(r"[^A-Z0-9]", "", po_name.upper()))
    if desc and po_name:
        po_upper = po_name.upper()
        po_tokens = [t for t in re.split(r"[\s/\-]+", po_upper) if len(t) >= 3]
        inv_tokens = _split_desc_tokens(desc.upper())
        if _has_conflicting_modifiers(inv_tokens, po_tokens):
            # Misma familia (TOMATE) pero forma distinta (SECO vs TRITURADO).
            partial_best = 0.0
            for desc_variant in _desc_match_variants(desc):
                partial_best = max(
                    partial_best, float(fuzz.token_set_ratio(desc_variant, po_upper))
                )
                if po_compact_len >= 6:
                    partial_best = max(
                        partial_best, float(fuzz.partial_ratio(desc_variant, po_upper))
                    )
            return min(partial_best, 60.0)

        for desc_variant in _desc_match_variants(desc):
            sc = float(fuzz.token_set_ratio(desc_variant, po_upper))
            best_sc = max(best_sc, sc)
            if sc >= 80:
                break
            # tokens cortos tipo "pan" vs "ALM-PAN FRANCES" (con OCR fix en CHOCL0→CHOCLO)
            # Solo boost a 75 si hay overlap real y no es un solo género compartido
            # con otros discriminadores distintos (TOMATE SECO ≠ TOMATE TRITURADO).
            inv_content = set(_content_match_tokens(_split_desc_tokens(desc_variant)))
            po_content = set(_content_match_tokens(po_tokens))
            overlap = inv_content & po_content
            if overlap:
                if len(overlap) >= 2 or len(inv_content) <= 2:
                    for dt in inv_content:
                        for pt in po_content:
                            if dt in pt or pt in dt:
                                best_sc = max(best_sc, 75.0)
                                break
            # partial_ratio solo con nombre OC suficientemente largo (evita
            # falsos tipo ACUERDO≈ZERO vía 'ERDO').
            if po_compact_len >= 6:
                best_sc = max(best_sc, float(fuzz.partial_ratio(desc_variant, po_upper)))

    agua = _agua_affinity_score(desc, po_name)
    if agua:
        best_sc = max(best_sc, agua)

    if best_sc >= 75.0:
        return best_sc

    if qty is not None and po_line.get("product_qty"):
        if abs(float(qty) - float(po_line["product_qty"])) <= 0.01:
            partial_best = best_sc
            if po_compact_len >= 6:
                for desc_variant in _desc_match_variants(desc):
                    partial_best = max(
                        partial_best, float(fuzz.partial_ratio(desc_variant, po_name.upper()))
                    )
            return max(55.0, partial_best)

    if desc and best_sc <= 0 and po_compact_len >= 6:
        partial_best = 0.0
        for desc_variant in _desc_match_variants(desc):
            partial_best = max(partial_best, float(fuzz.partial_ratio(desc_variant, po_name.upper())))
        return partial_best
    return best_sc

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


def _is_content_row(row: Dict[str, Any]) -> bool:
    if row.get("__solo_encabezado"):
        return False
    desc = _normalize(row.get("invoice_line_ids/name"))
    qty = _parse_amount(row.get("invoice_line_ids/quantity"))
    return bool(desc or qty is not None)


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
        sc = _line_match_score(codigo=codigo, descripcion=descripcion, qty=qty, po_line=po)
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
        sc = _line_match_score(codigo=codigo, descripcion=descripcion, qty=qty, po_line=po)
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
        sc = _line_match_score(codigo=codigo, descripcion=descripcion, qty=qty, po_line=po)
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
    if not rows or not is_purchase_odoo_configured():
        return summary

    summary["enabled"] = True
    _propagate_partner_for_matching(rows)
    uom_catalog = get_uom_catalog()
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
                partner_lines[partner_id] = fetch_partner_po_lines(partner_id)
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
            partner_lines[partner_id] = fetch_partner_po_lines(partner_id)
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
    if not is_purchase_odoo_configured():
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
    po_lines = fetch_partner_po_lines(partner_id)
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
        if is_purchase_odoo_configured():
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
    po_lines = fetch_partner_po_lines(partner_id)
    candidates = score_oc_candidates(comprobante_rows, po_lines)
    order_name = ""
    for c in candidates:
        if int(c["order_id"]) == int(order_id):
            order_name = c.get("order_name") or ""
            break

    _set_comprobante_oc_selection(comprobante_rows, int(order_id), order_name)
    uom_catalog = get_uom_catalog()
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
    clear_odoo_model_fields_cache()
