"""Fuzzy matching for Excel/Sheets-based padron (proveedores, productos, conceptos, formas de pago)."""

from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz, process as rf_process

from facturia_matching.infra.normalization import normalize

DEFAULT_MIN_SCORE = 72.0

UM_ALIASES = {
    "un": "unidad",
    "u": "unidad",
    "ud": "unidad",
    "uds": "unidad",
    "und": "unidad",
    "unidad": "unidad",
    "unidades": "unidad",
    "kg": "kg",
    "kgs": "kg",
    "kilo": "kg",
    "kilos": "kg",
    "kilogramo": "kg",
    "kilogramos": "kg",
    "g": "g",
    "gr": "g",
    "grs": "g",
    "gramo": "g",
    "gramos": "g",
    "lt": "l",
    "lts": "l",
    "l": "l",
    "litro": "l",
    "litros": "l",
    "ml": "ml",
    "m": "m",
    "mt": "m",
    "mts": "m",
    "metro": "m",
    "metros": "m",
    "caja": "caja",
    "cj": "caja",
    "cajas": "caja",
    "pack": "pack",
    "bulto": "bulto",
    "bolsa": "bolsa",
}


def _digits(s: Any) -> str:
    return "".join(ch for ch in normalize(s) if ch.isdigit())


def _name_score(query: str, choice: str, **_: Any) -> float:
    """Scoring function matching padron/postgres.py strategy."""
    q = normalize(query).upper()
    c = normalize(choice).upper()
    if not q or not c:
        return 0.0
    ts = float(fuzz.token_set_ratio(q, c))
    pr = float(fuzz.partial_ratio(q, c))
    return max(ts, 0.55 * ts + 0.45 * pr)


def canonical_um(raw: Any) -> str:
    s = normalize(raw).lower().rstrip(".")
    if not s:
        return ""
    return UM_ALIASES.get(s, s)


def um_matches(a: Any, b: Any) -> bool:
    ca, cb = canonical_um(a), canonical_um(b)
    if not ca or not cb:
        return False
    if ca == cb:
        return True
    return _name_score(ca, cb) >= 80.0


def match_one(
    query: str,
    choices: List[str],
    min_score: float = DEFAULT_MIN_SCORE,
) -> Optional[Tuple[str, float]]:
    """Match a single query against a list of choices. Returns (best_match, score) or None."""
    query_n = normalize(query)
    if not query_n or not choices:
        return None
    clean = [c for c in choices if normalize(c)]
    if not clean:
        return None
    best = rf_process.extractOne(query_n, clean, scorer=_name_score)
    if not best:
        return None
    score = float(best[1])
    if score < min_score:
        return None
    return (best[0], score)


def match_many(
    query: str,
    choices: List[str],
    min_score: float = DEFAULT_MIN_SCORE,
    limit: int = 5,
) -> List[Tuple[str, float]]:
    """Return top N matches above threshold."""
    query_n = normalize(query)
    if not query_n or not choices:
        return []
    clean = [c for c in choices if normalize(c)]
    if not clean:
        return []
    results = rf_process.extract(query_n, clean, scorer=_name_score, limit=limit)
    return [(r[0], float(r[1])) for r in results if float(r[1]) >= min_score]


def match_proveedor(
    nombre: str,
    proveedores: List[str],
    min_score: float = DEFAULT_MIN_SCORE,
) -> Optional[Tuple[str, float]]:
    """Match a supplier name against a flat name list (legacy)."""
    return match_one(nombre, proveedores, min_score)


def match_proveedor_excel(
    nombre: str,
    cuit: str,
    proveedores: List[Dict[str, Any]],
    min_score: float = DEFAULT_MIN_SCORE,
) -> Optional[Dict[str, Any]]:
    """CUIT exact (score 100) then fuzzy on razon_social and nombre_fantasia."""
    cuit_n = _digits(cuit)
    if cuit_n:
        for r in proveedores:
            doc = _digits(r.get("cuit"))
            if doc and doc == cuit_n:
                razon = normalize(r.get("razon_social"))
                fantasia = normalize(r.get("nombre_fantasia"))
                return {
                    "match": razon or fantasia,
                    "razon_social": razon,
                    "nombre_fantasia": fantasia,
                    "cuit": normalize(r.get("cuit")),
                    "score": 100.0,
                }

    nombre_n = normalize(nombre)
    if not nombre_n or not proveedores:
        return None

    indexed: List[Tuple[str, Dict[str, Any]]] = []
    for r in proveedores:
        razon = normalize(r.get("razon_social"))
        fantasia = normalize(r.get("nombre_fantasia"))
        if razon:
            indexed.append((razon, r))
        if fantasia and fantasia.lower() != razon.lower():
            indexed.append((fantasia, r))
    choices = [n for n, _ in indexed]
    if not choices:
        return None
    best = rf_process.extractOne(nombre_n, choices, scorer=_name_score)
    if not best:
        return None
    score = float(best[1])
    if score < min_score:
        return None
    row = indexed[int(best[2])][1]
    razon = normalize(row.get("razon_social"))
    fantasia = normalize(row.get("nombre_fantasia"))
    return {
        "match": razon or fantasia,
        "razon_social": razon,
        "nombre_fantasia": fantasia,
        "cuit": normalize(row.get("cuit")),
        "score": score,
    }


def match_concepto(
    descripcion: str,
    conceptos: List[str],
    min_score: float = DEFAULT_MIN_SCORE,
) -> Optional[Tuple[str, float]]:
    """Match a product/service description against the concepts list."""
    return match_one(descripcion, conceptos, min_score)


def match_forma_pago(
    texto: str,
    formas: List[str],
    min_score: float = DEFAULT_MIN_SCORE,
) -> Optional[Tuple[str, float]]:
    """Match payment method text."""
    return match_one(texto, formas, min_score)


def match_producto(
    descripcion: str,
    um_factura: str,
    productos: List[Dict[str, Any]],
    min_score: float = DEFAULT_MIN_SCORE,
) -> Optional[Dict[str, Any]]:
    """Fuzzy match description to product name; attach padron UoM and um_match flag."""
    desc = normalize(descripcion)
    if not desc or not productos:
        return None
    names = [(normalize(p.get("nombre")), p) for p in productos]
    choices = [n for n, _ in names if n]
    if not choices:
        return None
    best = rf_process.extractOne(desc, choices, scorer=_name_score)
    if not best:
        return None
    score = float(best[1])
    if score < min_score:
        return None
    row = names[int(best[2])][1]
    um_padron = normalize(row.get("unidad_medida"))
    factura_um = normalize(um_factura)
    matched_um = False
    if factura_um and um_padron:
        matched_um = um_matches(factura_um, um_padron)
    elif not factura_um:
        matched_um = None  # type: ignore
    return {
        "match": normalize(row.get("nombre")),
        "unidad_medida": um_padron,
        "um_factura": factura_um,
        "um_match": matched_um,
        "score": score,
    }


def match_bulk(
    queries: List[str],
    choices: List[str],
    min_score: float = DEFAULT_MIN_SCORE,
) -> List[Dict[str, Any]]:
    """Match a list of queries, returning results for each."""
    out = []
    for q in queries:
        hit = match_one(q, choices, min_score)
        out.append({
            "query": q,
            "match": hit[0] if hit else None,
            "score": hit[1] if hit else 0.0,
        })
    return out
