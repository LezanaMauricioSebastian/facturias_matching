"""Memoria de cabecera (diario/cuenta/rubro) desde conversiones pasadas.

Sin tabla dedicada: indexa las últimas ~100 filas de `process_conversions`
por `partner_id` (más reciente gana). Al cargar un proceso nuevo, si el
proveedor ya tuvo un diario corregido en otra conversión de la misma
empresa/template, se reusa en lugar del fuzzy del padrón.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from facturia_matching.odoo.env import get_conversion_template_id
from facturia_matching.persistence.product_label_memory import (
    DEFAULT_CONVERSION_LIMIT,
    fetch_recent_conversion_row_lists,
)

logger = logging.getLogger(__name__)

# partner_id → HeaderChoice
HeaderIndex = Dict[int, "HeaderChoice"]

_cache_lock = threading.Lock()
# (company_id, template_id) → HeaderIndex
_HEADER_INDEX_CACHE: Dict[Tuple[int, int], HeaderIndex] = {}


@dataclass(frozen=True)
class HeaderChoice:
    """Última cabecera vista en una conversión para un proveedor."""

    journal_id: str = ""
    account_id: str = ""
    rubro_id: str = ""


def _normalize(raw: Any) -> str:
    if raw is None:
        return ""
    return " ".join(str(raw).strip().split())


def _positive_id(raw: Any) -> str:
    s = _normalize(raw)
    if s.isdigit() and int(s) > 0:
        return s
    return ""


def _partner_id_from_rows(rows: Iterable[Dict[str, Any]]) -> Optional[int]:
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = _positive_id(row.get("partner_id"))
        if pid:
            return int(pid)
    return None


def _group_by_comprobante(rows: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    groups: Dict[Any, List[Dict[str, Any]]] = {}
    order: List[Any] = []
    for idx, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue
        key = row.get("__comprobante_idx")
        if key is None:
            key = f"_row_{idx}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    return [groups[k] for k in order]


def extract_header_choice(rows: List[Dict[str, Any]]) -> Optional[Tuple[int, HeaderChoice]]:
    """De un comprobante (o lista de filas): (partner_id, HeaderChoice) si hay partner."""
    if not rows:
        return None
    partner_id = _partner_id_from_rows(rows)
    if partner_id is None:
        return None
    journal_id = ""
    account_id = ""
    rubro_id = ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not journal_id:
            journal_id = _positive_id(row.get("journal_id"))
        if not account_id:
            account_id = _positive_id(row.get("invoice_line_ids/account_id"))
        if not rubro_id:
            rubro_id = _positive_id(row.get("x_studio_category"))
        if journal_id and account_id and rubro_id:
            break
    if not (journal_id or account_id or rubro_id):
        return None
    return partner_id, HeaderChoice(
        journal_id=journal_id,
        account_id=account_id,
        rubro_id=rubro_id,
    )


def build_header_index_from_row_lists(
    conversion_row_lists: List[List[Dict[str, Any]]],
) -> HeaderIndex:
    """Índice partner → HeaderChoice. Primera aparición gana (listas más recientes primero)."""
    index: HeaderIndex = {}
    for rows in conversion_row_lists or []:
        if not isinstance(rows, list):
            continue
        for comp_rows in _group_by_comprobante(rows):
            extracted = extract_header_choice(comp_rows)
            if extracted is None:
                continue
            partner_id, choice = extracted
            if partner_id not in index:
                index[partner_id] = choice
    return index


def catalog_contains_id(items: List[Dict[str, Any]], raw_id: Any) -> bool:
    """True si `raw_id` está en la lista de opciones del catálogo Odoo."""
    want = _positive_id(raw_id)
    if not want or not items:
        return False
    for it in items:
        if not isinstance(it, dict):
            continue
        if _positive_id(it.get("id")) == want:
            return True
    return False


def lookup_header(
    index: HeaderIndex,
    partner_id: Any,
) -> Optional[HeaderChoice]:
    pid = _positive_id(partner_id)
    if not pid:
        return None
    return index.get(int(pid))


def apply_learned_header_ids(
    *,
    partner_id: Any,
    journal_id: str,
    account_id: str,
    rubro_id: str,
    header_index: Optional[HeaderIndex],
    journals: List[Dict[str, Any]],
    cuentas: List[Dict[str, Any]],
    rubros: List[Dict[str, Any]],
    supports_rubro: bool,
) -> Tuple[str, str, str]:
    """Preferí ids aprendidos (válidos en catálogo) sobre los del padrón.

    Si el id aprendido no está en el catálogo del perfil activo, se conserva
    el valor que vino del fuzzy/padrón.
    """
    if not header_index:
        return journal_id, account_id, rubro_id
    choice = lookup_header(header_index, partner_id)
    if choice is None:
        return journal_id, account_id, rubro_id

    out_journal = journal_id
    out_account = account_id
    out_rubro = rubro_id

    if choice.journal_id and catalog_contains_id(journals, choice.journal_id):
        out_journal = choice.journal_id
    if choice.account_id and catalog_contains_id(cuentas, choice.account_id):
        out_account = choice.account_id
    if (
        supports_rubro
        and choice.rubro_id
        and catalog_contains_id(rubros, choice.rubro_id)
    ):
        out_rubro = choice.rubro_id

    return out_journal, out_account, out_rubro


def invalidate_header_index_cache(
    company_id: Optional[int] = None,
    *,
    template_id: Optional[int] = None,
) -> None:
    """Invalida cache. Sin args → todo; con company_id → esa empresa (y template)."""
    with _cache_lock:
        if company_id is None:
            _HEADER_INDEX_CACHE.clear()
            return
        tid = (
            int(template_id)
            if template_id is not None
            else get_conversion_template_id()
        )
        _HEADER_INDEX_CACHE.pop((int(company_id), tid), None)


def build_header_index_for_company(
    company_id: Optional[int],
    *,
    template_id: Optional[int] = None,
    limit: int = DEFAULT_CONVERSION_LIMIT,
    use_cache: bool = True,
) -> HeaderIndex:
    """Arma índice desde conversiones recientes. Cache por (company, template)."""
    if company_id is None:
        return {}
    tid = int(template_id) if template_id is not None else get_conversion_template_id()
    cache_key = (int(company_id), tid)

    if use_cache:
        with _cache_lock:
            cached = _HEADER_INDEX_CACHE.get(cache_key)
            if cached is not None:
                return cached

    try:
        payloads = fetch_recent_conversion_row_lists(
            int(company_id), template_id=tid, limit=limit
        )
    except Exception as e:
        logger.warning(
            "partner_header_memory: no se pudo leer conversiones company_id=%s: %s",
            company_id,
            e,
        )
        return {}

    row_lists: List[List[Dict[str, Any]]] = []
    for payload in payloads or []:
        if isinstance(payload, dict):
            rows = payload.get("rows")
            if isinstance(rows, list):
                row_lists.append(rows)
        elif isinstance(payload, list):
            row_lists.append(payload)

    index = build_header_index_from_row_lists(row_lists)

    if use_cache:
        with _cache_lock:
            _HEADER_INDEX_CACHE[cache_key] = index
    return index
