"""Sugerencia de UM vía Claude cuando el fallback a Units del producto es ambiguo.

Se activa con FACTURIA_UOM_AI_ENABLED=1 y ANTHROPIC_API_KEY. Si falla o está
apagado, el matching sigue con el default de compra del producto (como antes).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from facturia_matching.infra.env import env_strip
from facturia_matching.odoo.purchase_matching._util import _normalize, _normalize_key

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-sonnet-4-20250514"
_CACHE: Dict[Tuple[int, str], Optional[int]] = {}
_ID_RE = re.compile(r"\b(\d+)\b")


def is_uom_ai_enabled() -> bool:
    """True si el feature flag está on y hay API key."""
    flag = env_strip("FACTURIA_UOM_AI_ENABLED", "0").lower()
    if flag not in ("1", "true", "yes", "on"):
        return False
    return bool(env_strip("ANTHROPIC_API_KEY"))


def clear_uom_ai_cache() -> None:
    _CACHE.clear()


def _cache_key(product_id: int, product_label: str) -> Tuple[int, str]:
    return (int(product_id), _normalize_key(product_label))


def _build_prompt(
    *,
    partner_name: str,
    product_label: str,
    uoms: List[Dict[str, Any]],
) -> str:
    partner = _normalize(partner_name) or "(desconocido)"
    label = _normalize(product_label) or "(sin descripción)"
    lines = [
        "Contexto: Esta es una empresa gastronómica que compra alimentos y bebidas "
        "en packs de unidades (6, 12), en paquetes, en kg, litros, etc.",
        "",
        f'La factura del proveedor "{partner}" lista literalmente este producto: "{label}".',
        "",
        "Elige cuál de las siguientes unidades de medida corresponde al producto. "
        "Responde SOLO con el número de ID (sin texto adicional).",
        "",
        "Opciones:",
    ]
    for uom in uoms:
        uid = uom.get("id")
        name = _normalize(uom.get("name") or "")
        if uid is None or not name:
            continue
        lines.append(f"- ID {int(uid)}: {name}")
    return "\n".join(lines)


def _parse_uom_id(text: str, valid_ids: set) -> Optional[int]:
    """Extrae el primer ID numérico que esté en valid_ids."""
    if not text or not valid_ids:
        return None
    for m in _ID_RE.finditer(text.strip()):
        try:
            uid = int(m.group(1))
        except ValueError:
            continue
        if uid in valid_ids:
            return uid
    return None


def _call_claude(prompt: str) -> str:
    """Llama a Anthropic Messages API. Import lazy para no exigir el paquete si está off."""
    import anthropic

    api_key = env_strip("ANTHROPIC_API_KEY")
    model = env_strip("FACTURIA_UOM_AI_MODEL") or _DEFAULT_MODEL
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=32,
        messages=[{"role": "user", "content": prompt}],
    )
    parts: List[str] = []
    for block in message.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text))
    return " ".join(parts).strip()


def suggest_uom(
    *,
    product_id: int,
    product_label: str,
    partner_name: str,
    uoms: List[Dict[str, Any]],
) -> Optional[int]:
    """
    Devuelve el id de UM sugerido por Claude, o None.

    Cache en memoria por (product_id, label_key) para no repetir llamadas en el
    mismo proceso. Ante error / respuesta inválida: log warning y None.
    """
    if not is_uom_ai_enabled():
        return None
    label = _normalize(product_label)
    if not label or not product_id:
        return None

    options = [
        {"id": int(u["id"]), "name": _normalize(u.get("name") or "")}
        for u in (uoms or [])
        if u.get("id") is not None and _normalize(u.get("name") or "")
    ]
    if len(options) < 2:
        return None

    key = _cache_key(int(product_id), label)
    if key in _CACHE:
        return _CACHE[key]

    valid_ids = {int(o["id"]) for o in options}
    prompt = _build_prompt(
        partner_name=partner_name,
        product_label=label,
        uoms=options,
    )
    try:
        raw = _call_claude(prompt)
        chosen = _parse_uom_id(raw, valid_ids)
        if chosen is None:
            logger.warning(
                "uom_ai: respuesta sin ID válido product_id=%s label=%r raw=%r",
                product_id,
                label,
                raw[:120] if raw else "",
            )
        _CACHE[key] = chosen
        return chosen
    except Exception as e:
        logger.warning(
            "uom_ai: fallo Claude product_id=%s label=%r: %s",
            product_id,
            label,
            e,
        )
        _CACHE[key] = None
        return None
