"""Fuzzy / Dinner notes / scores de línea factura ↔ OC."""

from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from rapidfuzz import fuzz

from facturia_matching.odoo.purchase_matching._util import (
    _normalize,
    _normalize_key,
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
    """ZERO vs no-ZERO, sin/con gas, pack 6 vs 8 (misma idea que memoria de producto)."""
    if (_invoice_has_zero_token(a)) != (_invoice_has_zero_token(b)):
        return True
    a_still, a_spark = _invoice_gas_flags(a)
    b_still, b_spark = _invoice_gas_flags(b)
    if (a_still and b_spark) or (b_still and a_spark):
        return True
    from facturia_matching.persistence.product_label_memory import pack_counts_conflict

    return pack_counts_conflict(a, b)


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

