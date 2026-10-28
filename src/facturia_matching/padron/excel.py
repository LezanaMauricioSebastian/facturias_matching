"""Fuzzy matching for Excel/Sheets-based padron (proveedores, productos, conceptos, formas de pago)."""

import re
import unicodedata
from typing import Any, Dict, List, Optional, Sequence, Tuple

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


# Tipos societarios al final del nombre. No forman parte de la razón social.
_COMPANY_SUFFIXES = (
    "SOCIEDAD DE RESPONSABILIDAD LIMITADA",
    "SOCIEDAD ANONIMA",
    "S A S",
    "S R L",
    "S A",
    "SAS",
    "SRL",
    "SA",
    "LTDA",
    "SACI",
    "SACIF",
)


def fold_text(raw: Any) -> str:
    """Mayúsculas, sin acentos ni puntuación. «EFECTIVO» y «Francés» quedan comparables."""
    s = normalize(raw)
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return " ".join(s.split())


def company_key(raw: Any) -> str:
    """Nombre de empresa sin puntos ni tipo societario (S.A., S.R.L., S.A.S.)."""
    s = fold_text(raw)
    while s:
        stripped = False
        for suf in _COMPANY_SUFFIXES:
            tail = " " + suf
            if s.endswith(tail) and s[: -len(tail)].strip():
                s = s[: -len(tail)].strip()
                stripped = True
                break
        if not stripped:
            break
    return s


def same_company(a: Any, b: Any) -> bool:
    ka, kb = company_key(a), company_key(b)
    return bool(ka and ka == kb)


def wire_listed_value(query: str, options: Sequence[str]) -> str:
    """Valor de la lista que es el mismo texto.

    Iguala mayúsculas, acentos y el tipo societario (S.A., S.R.L., S.A.S.).
    Si la lista tiene «La Alemana» y «LA ALEMANA S.R.L», gana el más corto.
    No usa fuzzy: «Servicios crudo» no es «Servicios».
    """
    qf = fold_text(query)
    qk = company_key(query)
    if not qf or not options:
        return ""
    hits: List[str] = []
    for opt in options:
        label = str(opt or "").strip()
        if not label:
            continue
        if fold_text(label) == qf or (qk and company_key(label) == qk):
            hits.append(label)
    if not hits:
        return ""
    return min(hits, key=lambda label: (len(label), label))


def pick_listed_company(
    query: str,
    options: Sequence[str],
    min_score: float = 90.0,
) -> str:
    """Opción de la lista que es la misma empresa.

    «LA ALEMANA S.R.L» y «La Alemana» empatan: gana el nombre más corto de la
    lista. Un token corto («LA», «SA») no alcanza para elegir otra empresa.
    """
    qk = company_key(query)
    if not qk or not options:
        return ""
    best: Optional[Tuple[Tuple[float, int], str]] = None
    for opt in options:
        label = str(opt or "").strip()
        ok = company_key(label)
        if not ok:
            continue
        if ok == qk:
            score = 100.0
        elif min(len(qk), len(ok)) < 4:
            continue
        else:
            score = _name_score(qk, ok)
        if score < min_score:
            continue
        rank = (score, -len(label))
        if best is None or rank > best[0]:
            best = (rank, label)
    return best[1] if best else ""


def match_proveedor(
    nombre: str,
    proveedores: List[str],
    min_score: float = DEFAULT_MIN_SCORE,
) -> Optional[Tuple[str, float]]:
    """Match a supplier name against a flat name list (legacy)."""
    return match_one(nombre, proveedores, min_score)


def _proveedor_hit(row: Dict[str, Any], score: float) -> Dict[str, Any]:
    razon = normalize(row.get("razon_social"))
    fantasia = normalize(row.get("nombre_fantasia"))
    return {
        "match": razon or fantasia,
        "razon_social": razon,
        "nombre_fantasia": fantasia,
        "cuit": normalize(row.get("cuit")),
        "score": score,
    }


def _index_proveedor_names(
    proveedores: List[Dict[str, Any]],
) -> List[Tuple[str, Dict[str, Any]]]:
    indexed: List[Tuple[str, Dict[str, Any]]] = []
    for r in proveedores:
        razon = normalize(r.get("razon_social"))
        fantasia = normalize(r.get("nombre_fantasia"))
        if razon:
            indexed.append((razon, r))
        if fantasia and fantasia.lower() != razon.lower():
            indexed.append((fantasia, r))
    return indexed


def _best_named_proveedor(
    nombre: str,
    indexed: List[Tuple[str, Dict[str, Any]]],
    min_score: float,
) -> Optional[Dict[str, Any]]:
    """Mejor fila por nombre. A igualdad de empresa, la razón social más corta."""
    qk = company_key(nombre)
    if not qk or not indexed:
        return None
    best: Optional[Tuple[Tuple[float, int], Dict[str, Any]]] = None
    for label, row in indexed:
        ok = company_key(label)
        if not ok:
            continue
        if ok == qk:
            score = 100.0
        elif min(len(qk), len(ok)) < 4:
            continue
        else:
            score = _name_score(qk, ok)
        if score < min_score:
            continue
        razon = normalize(row.get("razon_social")) or label
        rank = (score, -len(razon))
        if best is None or rank > best[0]:
            best = (rank, _proveedor_hit(row, score))
    return best[1] if best else None


def match_proveedor_excel(
    nombre: str,
    cuit: str,
    proveedores: List[Dict[str, Any]],
    min_score: float = DEFAULT_MIN_SCORE,
) -> Optional[Dict[str, Any]]:
    """Nombre fuerte (sin S.A./S.R.L.) primero; si no, CUIT exacto; si no, fuzzy.

    Un CUIT que apunta a otra empresa no pisa un nombre que ya está en la lista.
    Sin nombre, el CUIT sigue ganando.
    """
    indexed = _index_proveedor_names(proveedores)
    strong = _best_named_proveedor(nombre, indexed, 90.0)
    if strong:
        return strong

    cuit_n = _digits(cuit)
    nombre_key = company_key(nombre)
    if cuit_n:
        for r in proveedores:
            doc = _digits(r.get("cuit"))
            if not doc or doc != cuit_n:
                continue
            hit = _proveedor_hit(r, 100.0)
            other = company_key(hit["razon_social"] or hit["nombre_fantasia"])
            # Sin nombre, el CUIT define. Con nombre, un CUIT de otra empresa no gana.
            if nombre_key and other and nombre_key != other and _name_score(nombre_key, other) < min_score:
                continue
            return hit

    if not indexed:
        return None
    choices = [n for n, _ in indexed]
    nombre_n = normalize(nombre)
    if not nombre_n:
        return None
    best = rf_process.extractOne(nombre_n, choices, scorer=_name_score)
    if not best:
        return None
    score = float(best[1])
    if score < min_score:
        return None
    row = indexed[int(best[2])][1]
    return _proveedor_hit(row, score)


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
