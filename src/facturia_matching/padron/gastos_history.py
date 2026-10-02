"""Historial de hoja Gastos (memoria retrieval para concept_ai).

Parsea CSV con filas de título antes del header real (típico Google Sheets
export de pestañas tipo «Gastos 2026»).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz

from facturia_matching.infra.normalization import normalize
from facturia_matching.padron.sheet_loader import fetch_sheet_raw_rows

logger = logging.getLogger(__name__)

# Pepe / Gastos 2026 default tab.
DEFAULT_GASTOS_SHEET_GID = "541219037"

_HEADER_MARKERS = {
    "proveedor": ("proveedor", "proveedores"),
    "concepto": ("concepto", "conceptos"),
    "categoria": (
        "categoria gasto",
        "categoría gasto",
        "categoria de gasto",
        "categoría de gasto",
        "categoria",
        "categoría",
    ),
    "descripcion": (
        "descripcion",
        "descripción",
        "detalle",
        "observacion",
        "observación",
        "producto",
    ),
}

_CACHE: Dict[str, Dict[str, Any]] = {}
_DEFAULT_TTL = 900


def _norm_header(cell: Any) -> str:
    s = normalize(str(cell or "")).lower()
    # quitar acentos crudamente vía normalize ya; colapsar espacios
    return " ".join(s.split())


def _find_col(headers: List[str], aliases: Tuple[str, ...]) -> Optional[int]:
    for i, h in enumerate(headers):
        if h in aliases:
            return i
    # substring soft match
    for i, h in enumerate(headers):
        for a in aliases:
            if a and a in h:
                return i
    return None


def detect_gastos_header(raw_rows: List[List[str]]) -> Optional[Tuple[int, Dict[str, int]]]:
    """Return (header_row_index, {proveedor,concepto,categoria[,descripcion]: col_idx})."""
    for idx, row in enumerate(raw_rows[:40]):
        headers = [_norm_header(c) for c in row]
        if not any(headers):
            continue
        i_prov = _find_col(headers, _HEADER_MARKERS["proveedor"])
        i_conc = _find_col(headers, _HEADER_MARKERS["concepto"])
        if i_prov is None or i_conc is None:
            continue
        cols: Dict[str, int] = {"proveedor": i_prov, "concepto": i_conc}
        i_cat = _find_col(headers, _HEADER_MARKERS["categoria"])
        if i_cat is not None:
            cols["categoria"] = i_cat
        i_desc = _find_col(headers, _HEADER_MARKERS["descripcion"])
        if i_desc is not None:
            cols["descripcion"] = i_desc
        return idx, cols
    return None


def parse_gastos_records(raw_rows: List[List[str]]) -> List[Dict[str, str]]:
    """Filas normalizadas {proveedor, concepto, categoria, descripcion}."""
    detected = detect_gastos_header(raw_rows)
    if not detected:
        return []
    header_idx, cols = detected
    out: List[Dict[str, str]] = []
    for row in raw_rows[header_idx + 1 :]:
        if not row:
            continue

        def cell(key: str) -> str:
            i = cols.get(key)
            if i is None or i >= len(row):
                return ""
            return str(row[i] or "").strip()

        prov = cell("proveedor")
        conc = cell("concepto")
        if not prov and not conc:
            continue
        out.append(
            {
                "proveedor": prov,
                "concepto": conc,
                "categoria": cell("categoria"),
                "descripcion": cell("descripcion"),
            }
        )
    return out


def unique_categorias(records: List[Dict[str, str]]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for r in records:
        c = (r.get("categoria") or "").strip()
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


# Aliases → labels canónicos Pepe / planilla Gastos.
_CAT_CANON = {
    "gastos fijos": "Gastos Fijos",
    "gasto fijo": "Gastos Fijos",
    "fijos": "Gastos Fijos",
    "fijo": "Gastos Fijos",
    "gastos var": "Gastos Var",
    "gastos variables": "Gastos Var",
    "gasto variable": "Gastos Var",
    "gasto var": "Gastos Var",
    "variables": "Gastos Var",
    "variable": "Gastos Var",
}


def canonicalize_categoria(raw: str) -> str:
    """Normaliza a «Gastos Fijos» / «Gastos Var» cuando es reconocible; si no, strip."""
    s = (raw or "").strip()
    if not s:
        return ""
    key = normalize(s).lower()
    if key in _CAT_CANON:
        return _CAT_CANON[key]
    # substring soft
    if "fij" in key:
        return "Gastos Fijos"
    if "var" in key:
        return "Gastos Var"
    return s


def infer_categoria(
    records: List[Dict[str, str]],
    *,
    concepto: str,
    proveedor: str = "",
) -> str:
    """Categoría más frecuente en historial para ese concepto (prioriza mismo proveedor)."""
    conc = normalize(concepto).upper()
    if not conc or not records:
        return ""
    prov_q = normalize(proveedor).upper()

    def tally(rows: List[Dict[str, str]]) -> str:
        counts: Dict[str, int] = {}
        for r in rows:
            if normalize(r.get("concepto") or "").upper() != conc:
                continue
            cat = canonicalize_categoria(r.get("categoria") or "")
            if not cat:
                continue
            counts[cat] = counts.get(cat, 0) + 1
        if not counts:
            return ""
        return max(counts.items(), key=lambda x: x[1])[0]

    if prov_q:
        same = [
            r
            for r in records
            if normalize(r.get("proveedor") or "").upper() == prov_q
        ]
        hit = tally(same)
        if hit:
            return hit
    return tally(records)


def dominant_concepto(
    records: List[Dict[str, str]],
    *,
    proveedor: str,
    allowed: Optional[List[str]] = None,
    min_prov_score: float = 90.0,
) -> str:
    """Concepto más frecuente de ese proveedor en Gastos.

    El cliente clasifica por proveedor: si hay varias etiquetas, gana la mayoría.
    Primero match exacto de nombre; si no hay, fuzzy alto.
    """
    prov_q = normalize(proveedor).upper()
    if not prov_q or not records:
        return ""
    allowed_map = {
        normalize(a).upper(): a for a in (allowed or []) if (a or "").strip()
    }

    def pool_for(exact_only: bool) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for r in records:
            rp = normalize(r.get("proveedor") or "").upper()
            if not rp:
                continue
            if rp == prov_q:
                out.append(r)
                continue
            if exact_only:
                continue
            if float(fuzz.token_set_ratio(prov_q, rp)) >= min_prov_score:
                out.append(r)
        return out

    pool = pool_for(True) or pool_for(False)
    counts: Dict[str, int] = {}
    display: Dict[str, str] = {}
    for r in pool:
        raw = (r.get("concepto") or "").strip()
        if not raw:
            continue
        key = normalize(raw).upper()
        label = raw
        if allowed_map:
            mapped = allowed_map.get(key)
            if mapped:
                label = mapped
                key = normalize(mapped).upper()
        counts[key] = counts.get(key, 0) + 1
        display[key] = label
    if not counts:
        return ""
    best = max(counts.items(), key=lambda x: x[1])[0]
    return display.get(best) or ""


def _cache_key(spreadsheet_id: str, gid: str) -> str:
    return f"gastos:{spreadsheet_id}:gid={gid}"


def load_gastos_history(
    *,
    spreadsheet_id: str,
    gid: str = DEFAULT_GASTOS_SHEET_GID,
    ttl: int = _DEFAULT_TTL,
    force: bool = False,
) -> List[Dict[str, str]]:
    """Fetch + parse Gastos tab; cached in memory."""
    sid = (spreadsheet_id or "").strip()
    g = (gid or DEFAULT_GASTOS_SHEET_GID).strip() or DEFAULT_GASTOS_SHEET_GID
    if not sid:
        return []
    key = _cache_key(sid, g)
    now = time.time()
    cached = _CACHE.get(key)
    if cached and not force and (now - float(cached.get("ts") or 0)) < ttl:
        return list(cached.get("records") or [])
    try:
        raw = fetch_sheet_raw_rows(
            spreadsheet_id=sid, gid=g, ttl=ttl, force=force
        )
        records = parse_gastos_records(raw)
    except Exception as e:
        logger.warning("gastos_history: no se pudo leer sid=%s gid=%s: %s", sid, g, e)
        if cached and cached.get("records"):
            return list(cached.get("records") or [])
        records = []
    _CACHE[key] = {"records": records, "ts": now}
    return list(records)


def clear_gastos_history_cache() -> None:
    _CACHE.clear()


def top_k_examples(
    records: List[Dict[str, str]],
    *,
    proveedor: str,
    descripcion: str = "",
    k: int = 15,
    min_prov_score: float = 70.0,
) -> List[Dict[str, str]]:
    """Ejemplos del historial: mismo proveedor primero, luego fuzzy cercano."""
    if not records or k <= 0:
        return []
    prov_q = normalize(proveedor)
    desc_q = normalize(descripcion).upper()

    same: List[Dict[str, str]] = []
    others: List[Tuple[float, Dict[str, str]]] = []
    for r in records:
        rp = normalize(r.get("proveedor") or "")
        if not rp:
            continue
        if prov_q and rp.upper() == prov_q.upper():
            same.append(r)
            continue
        if not prov_q:
            continue
        score = float(fuzz.token_set_ratio(prov_q.upper(), rp.upper()))
        if score >= min_prov_score:
            others.append((score, r))

    others.sort(key=lambda x: -x[0])

    def rank_same(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
        if not desc_q:
            return rows
        scored = []
        for r in rows:
            hay = normalize(
                f"{r.get('concepto') or ''} {r.get('descripcion') or ''}"
            ).upper()
            sc = float(fuzz.token_set_ratio(desc_q, hay)) if hay else 0.0
            scored.append((sc, r))
        scored.sort(key=lambda x: -x[0])
        return [r for _, r in scored]

    ordered = rank_same(same) + [r for _, r in others]
    # dedupe by (proveedor, concepto, categoria)
    seen: set = set()
    out: List[Dict[str, str]] = []
    for r in ordered:
        key = (
            normalize(r.get("proveedor") or "").upper(),
            normalize(r.get("concepto") or "").upper(),
            normalize(r.get("categoria") or "").upper(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "proveedor": (r.get("proveedor") or "").strip(),
                "concepto": (r.get("concepto") or "").strip(),
                "categoria": (r.get("categoria") or "").strip(),
                "descripcion": (r.get("descripcion") or "").strip(),
            }
        )
        if len(out) >= k:
            break
    return out
