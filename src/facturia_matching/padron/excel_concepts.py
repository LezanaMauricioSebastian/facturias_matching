"""Concepto y categoría del caso Excel: fuzzy (sin prompt) o sugerencia IA."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

from facturia_matching.infra.normalization import normalize


def resolve_excel_concepts(
    items: Sequence[Dict[str, Any]],
    *,
    conceptos: Sequence[str],
    cat_map: Optional[Dict[str, str]],
    proveedor: str,
    gastos_records: Optional[Sequence[Dict[str, str]]],
    gastos_categorias: Optional[Sequence[str]],
    company_id: int,
    use_ai: bool = False,
    allow_env_ai: bool = True,
) -> List[Dict[str, Any]]:
    """Una entrada por ítem.

    ``concepto`` / ``categoria`` es lo que muestra la grilla.
    Con ``use_ai`` (tilde del template) también llena ``ai_*``.
    ``fuzzy_*`` es historial del proveedor y, si no hay, el match fuzzy.
    """
    from facturia_matching.padron.gastos_history import canonicalize_categoria

    cat_map = cat_map or {}
    lines: List[Dict[str, Any]] = []
    for it in items or []:
        lines.append(
            {
                "descripcion": normalize((it or {}).get("descripcion")),
                "concepto": "",
                "score": 0.0,
                "categoria": "",
                "fuzzy_concepto": "",
                "fuzzy_categoria": "",
                "fuzzy_score": 0.0,
                "ai_concepto": "",
                "ai_categoria": "",
            }
        )

    def _categoria_for(concepto: str, hinted: str = "") -> str:
        cat = normalize(hinted or cat_map.get(concepto) or "")
        if cat:
            return canonicalize_categoria(cat) if cat else ""
        if gastos_records and concepto:
            from facturia_matching.padron.gastos_history import infer_categoria

            inferred = infer_categoria(
                list(gastos_records),
                concepto=concepto,
                proveedor=proveedor,
            )
            return canonicalize_categoria(inferred) if inferred else ""
        return ""

    def _stamp_fuzzy(concepto: str, categoria: str, score: float) -> None:
        cat = canonicalize_categoria(categoria) if categoria else ""
        for row in lines:
            row["fuzzy_concepto"] = concepto
            row["fuzzy_categoria"] = cat
            row["fuzzy_score"] = score
            row["concepto"] = concepto
            row["categoria"] = cat
            row["score"] = score

    from facturia_matching.padron.gastos_history import dominant_concepto

    dom = dominant_concepto(
        list(gastos_records or []),
        proveedor=proveedor,
        allowed=list(conceptos or []),
    )
    if dom:
        _stamp_fuzzy(dom, _categoria_for(dom), 100.0)
    else:
        _stamp_fuzzy_vote(lines, conceptos, _categoria_for)

    if use_ai:
        ai_concepto, ai_categoria = _ai_suggestion(
            lines,
            conceptos=list(conceptos or []),
            cat_map=cat_map,
            proveedor=proveedor,
            gastos_records=gastos_records,
            gastos_categorias=gastos_categorias,
            company_id=company_id,
            categoria_for=_categoria_for,
        )
        for row in lines:
            row["ai_concepto"] = ai_concepto
            row["ai_categoria"] = ai_categoria
        return lines

    if allow_env_ai and not dom:
        from facturia_matching.padron.concept_ai import is_concept_ai_enabled

        if is_concept_ai_enabled():
            ai_concepto, ai_categoria = _ai_suggestion(
                lines,
                conceptos=list(conceptos or []),
                cat_map=cat_map,
                proveedor=proveedor,
                gastos_records=gastos_records,
                gastos_categorias=gastos_categorias,
                company_id=company_id,
                categoria_for=_categoria_for,
            )
            if ai_concepto:
                cat = canonicalize_categoria(ai_categoria) if ai_categoria else ""
                for row in lines:
                    row["concepto"] = ai_concepto
                    row["categoria"] = cat
                    row["score"] = 80.0
    return lines


def _stamp_fuzzy_vote(lines, conceptos, categoria_for) -> None:
    from facturia_matching.padron.excel import match_one

    if not conceptos:
        return
    votes: Counter = Counter()
    best_score: Dict[str, float] = {}
    for row in lines:
        desc_i = row.get("descripcion") or ""
        if not desc_i:
            continue
        hit = match_one(desc_i, list(conceptos))
        if not hit:
            continue
        votes[hit[0]] += 1
        best_score[hit[0]] = max(best_score.get(hit[0], 0.0), float(hit[1]))
    if not votes:
        return
    winner = sorted(
        votes,
        key=lambda c: (votes[c], best_score.get(c, 0.0)),
        reverse=True,
    )[0]
    score = best_score.get(winner, 0.0)
    cat = categoria_for(winner)
    for row in lines:
        row["fuzzy_concepto"] = winner
        row["fuzzy_categoria"] = cat
        row["fuzzy_score"] = score
        row["concepto"] = winner
        row["categoria"] = cat
        row["score"] = score


def _ai_suggestion(
    lines,
    *,
    conceptos: List[str],
    cat_map: Dict[str, str],
    proveedor: str,
    gastos_records,
    gastos_categorias,
    company_id: int,
    categoria_for,
) -> tuple:
    from facturia_matching.infra.normalization import normalize as _norm
    from facturia_matching.padron.concept_ai import (
        is_concept_ai_enabled,
        suggest_concepto_categoria_batch,
    )

    if not is_concept_ai_enabled():
        return "", ""
    if not any(r.get("descripcion") for r in lines) or not conceptos:
        return "", ""
    from facturia_matching.padron.gastos_history import top_k_examples

    hint_desc = next((r.get("descripcion") or "" for r in lines if r.get("descripcion")), "")
    examples = top_k_examples(
        list(gastos_records or []),
        proveedor=proveedor,
        descripcion=hint_desc,
        k=15,
    )
    cats = list(gastos_categorias or [])
    for v in cat_map.values():
        vv = _norm(v)
        if vv and vv not in cats:
            cats.append(vv)
    for canon in ("Gastos Fijos", "Gastos Var"):
        if canon not in cats:
            cats.append(canon)
    suggestions = suggest_concepto_categoria_batch(
        company_id=int(company_id),
        proveedor=proveedor,
        lines=[{"descripcion": r.get("descripcion") or ""} for r in lines],
        conceptos=conceptos,
        categorias=cats or None,
        examples=examples,
        one_per_proveedor=True,
    )
    sug = next((s for s in suggestions if s and s.get("concepto")), None)
    if not sug:
        return "", ""
    return sug["concepto"], categoria_for(sug["concepto"], sug.get("categoria") or "")
