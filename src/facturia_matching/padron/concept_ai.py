"""Sugerencia Concepto + Categoría gasto vía DeepSeek (historial Sheet = memoria).

Generalizable: un LLM + listas/historial del cliente. Sin fine-tune.
Flag: FACTURIA_CONCEPT_AI_ENABLED=1 + DEEPSEEK_API_KEY.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from facturia_matching.infra.env import env_strip
from facturia_matching.infra.normalization import normalize

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "deepseek-flash"
_DEFAULT_BASE_URL = "https://api.deepseek.com"
_FALLBACK_CATEGORIAS = ["Gastos Fijos", "Gastos Var"]

# Cache: (company_id, proveedor_key, desc_key) -> {concepto, categoria} | None
_CACHE: Dict[Tuple[int, str, str], Optional[Dict[str, str]]] = {}


def is_concept_ai_enabled() -> bool:
    flag = env_strip("FACTURIA_CONCEPT_AI_ENABLED", "0").lower()
    if flag not in ("1", "true", "yes", "on"):
        return False
    return bool(env_strip("DEEPSEEK_API_KEY"))


def clear_concept_ai_cache() -> None:
    _CACHE.clear()


def _norm_key(s: str) -> str:
    return normalize(s).upper()


def _resolve_from_list(raw: str, allowed: List[str]) -> str:
    """Match exact / case-insensitive against allowed list."""
    r = (raw or "").strip()
    if not r or not allowed:
        return ""
    by_upper = {normalize(a).upper(): a for a in allowed if (a or "").strip()}
    hit = by_upper.get(normalize(r).upper())
    return hit or ""


def _build_prompt(
    *,
    proveedor: str,
    lines: List[Dict[str, str]],
    conceptos: List[str],
    categorias: List[str],
    examples: List[Dict[str, str]],
    one_per_proveedor: bool = False,
) -> str:
    if one_per_proveedor:
        instr = (
            "Este cliente clasifica el gasto por PROVEEDOR, no por ítem. "
            "Elegí UN solo concepto y UNA sola categoría para todo el comprobante, "
            "SOLO de las listas permitidas. Las líneas son contexto, no categorías distintas."
        )
        fmt = '[{"i":0,"concepto":"...","categoria":"..."}]'
    else:
        instr = (
            "Para cada línea de factura debés elegir UN concepto y UNA categoría "
            "SOLO de las listas permitidas."
        )
        fmt = '[{"i":0,"concepto":"...","categoria":"..."}, ...]'
    parts = [
        "Sos un asistente de clasificación de gastos para una empresa.",
        instr,
        "Respondé ÚNICAMENTE un JSON array (sin markdown):",
        fmt,
        "",
        f'Proveedor: "{normalize(proveedor) or "(desconocido)"}"',
        "",
        "Conceptos permitidos:",
    ]
    for c in conceptos:
        parts.append(f"- {c}")
    parts.append("")
    parts.append("Categorías permitidas:")
    for c in categorias:
        parts.append(f"- {c}")
    if examples:
        parts.append("")
        parts.append("Ejemplos del historial del cliente (mismo u otro proveedor similar):")
        for ex in examples[:20]:
            p = (ex.get("proveedor") or "").strip()
            conc = (ex.get("concepto") or "").strip()
            cat = (ex.get("categoria") or "").strip()
            desc = (ex.get("descripcion") or "").strip()
            bit = f'  - proveedor="{p}" concepto="{conc}" categoria="{cat}"'
            if desc:
                bit += f' desc="{desc}"'
            parts.append(bit)
    parts.append("")
    parts.append("Líneas a clasificar:")
    for i, line in enumerate(lines):
        desc = normalize(line.get("descripcion") or line.get("desc") or "")
        parts.append(f'  {i}: "{desc}"')
    return "\n".join(parts)


def _parse_json_array(text: str) -> List[Dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return []
    # strip markdown fences if any
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]", raw)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def _call_deepseek(prompt: str, *, max_tokens: int = 400) -> str:
    api_key = env_strip("DEEPSEEK_API_KEY")
    model = (
        env_strip("FACTURIA_CONCEPT_AI_MODEL")
        or env_strip("FACTURIA_UOM_AI_MODEL")
        or _DEFAULT_MODEL
    )
    base = (env_strip("DEEPSEEK_BASE_URL") or _DEFAULT_BASE_URL).rstrip("/")
    url = f"{base}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled"},
    }
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=45,
    )
    if not resp.ok:
        body = (resp.text or "")[:300]
        raise RuntimeError(f"DeepSeek HTTP {resp.status_code}: {body}")
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return str(message.get("content") or "").strip()


def _unify_supplier_concept(
    out: List[Optional[Dict[str, str]]],
    lines: List[Dict[str, str]],
    *,
    company_id: int,
    proveedor: str,
) -> List[Optional[Dict[str, str]]]:
    """Un solo concepto/categoría para todas las líneas del proveedor."""
    from collections import Counter

    counts: Counter = Counter()
    sample: Dict[str, Dict[str, str]] = {}
    for item in out:
        if not item or not item.get("concepto"):
            continue
        counts[item["concepto"]] += 1
        sample[item["concepto"]] = item
    if not counts:
        return out
    winner = counts.most_common(1)[0][0]
    chosen = dict(sample[winner])
    for i, line in enumerate(lines):
        out[i] = dict(chosen)
        desc = normalize(line.get("descripcion") or line.get("desc") or "")
        if desc:
            _CACHE[(int(company_id), _norm_key(proveedor), _norm_key(desc))] = dict(chosen)
    return out


def suggest_concepto_categoria_batch(
    *,
    company_id: int,
    proveedor: str,
    lines: List[Dict[str, str]],
    conceptos: List[str],
    categorias: Optional[List[str]] = None,
    examples: Optional[List[Dict[str, str]]] = None,
    one_per_proveedor: bool = False,
) -> List[Optional[Dict[str, str]]]:
    """
    Una llamada DeepSeek para N líneas.

    ``lines``: [{"descripcion": "..."}]
    Return: misma longitud; cada item ``{concepto, categoria}`` o None.
    """
    n = len(lines or [])
    if n == 0:
        return []
    if not is_concept_ai_enabled():
        return [None] * n

    conc_list = [c for c in (conceptos or []) if (c or "").strip()]
    cat_list = [c for c in (categorias or []) if (c or "").strip()]
    if not cat_list:
        cat_list = list(_FALLBACK_CATEGORIAS)
    if not conc_list:
        return [None] * n

    out: List[Optional[Dict[str, str]]] = [None] * n
    need_idx: List[int] = []
    for i, line in enumerate(lines):
        desc = normalize(line.get("descripcion") or line.get("desc") or "")
        if not desc:
            continue
        key = (int(company_id), _norm_key(proveedor), _norm_key(desc))
        if key in _CACHE:
            out[i] = _CACHE[key]
        else:
            need_idx.append(i)

    if not need_idx:
        if one_per_proveedor:
            return _unify_supplier_concept(
                out, lines, company_id=company_id, proveedor=proveedor
            )
        return out

    sub_lines = [
        {"descripcion": normalize(lines[i].get("descripcion") or lines[i].get("desc") or "")}
        for i in need_idx
    ]
    prompt = _build_prompt(
        proveedor=proveedor,
        lines=sub_lines,
        conceptos=conc_list,
        categorias=cat_list,
        examples=examples or [],
        one_per_proveedor=one_per_proveedor,
    )
    try:
        raw = _call_deepseek(prompt, max_tokens=min(80 * len(sub_lines) + 64, 800))
        parsed = _parse_json_array(raw)
    except Exception as e:
        logger.warning(
            "concept_ai: fallo DeepSeek company=%s prov=%r lines=%s: %s",
            company_id,
            proveedor,
            len(sub_lines),
            e,
        )
        for i in need_idx:
            desc = normalize(lines[i].get("descripcion") or "")
            _CACHE[(int(company_id), _norm_key(proveedor), _norm_key(desc))] = None
        return out

    by_i: Dict[int, Dict[str, Any]] = {}
    for j, obj in enumerate(parsed):
        try:
            idx = int(obj.get("i", j))
        except (TypeError, ValueError):
            idx = j
        by_i[idx] = obj

    for j, line_i in enumerate(need_idx):
        obj = by_i.get(j) or by_i.get(line_i) or {}
        concepto = _resolve_from_list(
            str(obj.get("concepto") or obj.get("concept") or ""), conc_list
        )
        cat_raw = str(obj.get("categoria") or obj.get("categoria_gasto") or "")
        categoria = _resolve_from_list(cat_raw, cat_list)
        if not categoria and cat_raw:
            from facturia_matching.padron.gastos_history import canonicalize_categoria

            categoria = _resolve_from_list(canonicalize_categoria(cat_raw), cat_list)
        result: Optional[Dict[str, str]] = None
        if concepto:
            result = {"concepto": concepto, "categoria": categoria}
        desc = normalize(lines[line_i].get("descripcion") or "")
        _CACHE[(int(company_id), _norm_key(proveedor), _norm_key(desc))] = result
        out[line_i] = result
        if result is None:
            logger.warning(
                "concept_ai: sin match válido i=%s raw_obj=%r",
                line_i,
                {k: obj.get(k) for k in ("concepto", "categoria", "i")} if obj else {},
            )
    if one_per_proveedor:
        return _unify_supplier_concept(
            out, lines, company_id=company_id, proveedor=proveedor
        )
    return out
