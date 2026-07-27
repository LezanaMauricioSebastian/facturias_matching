"""Aprendizaje de producto: última elección confirmada por proveedor + etiqueta.

Spike: lee conversiones recientes en `process_conversions` (sin tabla dedicada).
Solo considera filas con `invoice_line_ids/product_id` y sin `__product_suggested`
(elecciones del operador / match OC, no fuzzy sin confirmar).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from facturia_matching.infra.config import PROCESS_SCHEMA, _mysql_table_ref, get_mysql_connection
from facturia_matching.odoo.env import get_conversion_template_id
from facturia_matching.persistence.process_conversions import (
    CONVERSIONS_TABLE,
    parse_converted_payload,
)

logger = logging.getLogger(__name__)

DEFAULT_CONVERSION_LIMIT = 40
_MIN_LABEL_LEN = 2

# partner_id + label_key → product_id
ProductMemoryIndex = Dict[Tuple[int, str], int]


def normalize_label_key(raw: Any) -> str:
    if raw is None:
        return ""
    return " ".join(str(raw).strip().split()).upper()


def _normalize(raw: Any) -> str:
    if raw is None:
        return ""
    return " ".join(str(raw).strip().split())


def is_confirmed_product_choice(row: Dict[str, Any]) -> bool:
    """True si la fila tiene producto elegido (no sugerencia fuzzy pendiente)."""
    if not isinstance(row, dict):
        return False
    if str(row.get("__product_suggested") or "").strip():
        return False
    pid = _normalize(row.get("invoice_line_ids/product_id"))
    return pid.isdigit() and int(pid) > 0


def _partner_id_from_rows(rows: Iterable[Dict[str, Any]]) -> Optional[int]:
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = _normalize(row.get("partner_id"))
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
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


def iter_confirmed_choices(
    rows: List[Dict[str, Any]],
) -> Iterable[Tuple[int, str, int]]:
    """Yield (partner_id, label_key, product_id) from confirmed row choices."""
    for comp_rows in _group_by_comprobante(rows):
        partner_id = _partner_id_from_rows(comp_rows)
        if partner_id is None:
            continue
        for row in comp_rows:
            if not is_confirmed_product_choice(row):
                continue
            label = normalize_label_key(
                row.get("invoice_line_ids/name") or row.get("Nombre de producto")
            )
            if len(label) < _MIN_LABEL_LEN:
                continue
            product_id = int(_normalize(row.get("invoice_line_ids/product_id")))
            yield partner_id, label, product_id


def build_product_memory_index(
    conversion_row_lists: List[List[Dict[str, Any]]],
) -> ProductMemoryIndex:
    """Índice partner+label → product_id. La primera aparición gana (más reciente)."""
    index: ProductMemoryIndex = {}
    for rows in conversion_row_lists or []:
        if not isinstance(rows, list):
            continue
        for partner_id, label_key, product_id in iter_confirmed_choices(rows):
            key = (partner_id, label_key)
            if key not in index:
                index[key] = product_id
    return index


def lookup_in_index(
    index: ProductMemoryIndex,
    partner_id: Any,
    label: Any,
) -> Optional[int]:
    raw_partner = _normalize(partner_id)
    if not raw_partner.isdigit():
        return None
    label_key = normalize_label_key(label)
    if len(label_key) < _MIN_LABEL_LEN:
        return None
    return index.get((int(raw_partner), label_key))


def fetch_recent_conversion_row_lists(
    company_id: int,
    *,
    template_id: Optional[int] = None,
    limit: int = DEFAULT_CONVERSION_LIMIT,
) -> List[List[Dict[str, Any]]]:
    """Trae filas de conversiones recientes (más nuevas primero) para una empresa/perfil."""
    if company_id is None:
        return []
    tid = int(template_id) if template_id is not None else get_conversion_template_id()
    lim = max(1, min(int(limit or DEFAULT_CONVERSION_LIMIT), 200))
    table_ref = _mysql_table_ref(PROCESS_SCHEMA, CONVERSIONS_TABLE)
    conn = get_mysql_connection()
    out: List[List[Dict[str, Any]]] = []
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                f"""
                SELECT converted_data
                FROM {table_ref}
                WHERE company_id = %s AND template_id = %s
                ORDER BY updated_at DESC, id DESC
                LIMIT %s
                """,
                (int(company_id), tid, lim),
            )
            for row in cur.fetchall() or []:
                try:
                    rows = parse_converted_payload(row.get("converted_data"))
                except Exception as e:
                    logger.debug("product_label_memory: skip bad conversion payload: %s", e)
                    continue
                if rows:
                    out.append(rows)
        finally:
            cur.close()
    finally:
        conn.close()
    return out


def build_memory_index_for_company(
    company_id: Optional[int],
    *,
    template_id: Optional[int] = None,
    limit: int = DEFAULT_CONVERSION_LIMIT,
) -> ProductMemoryIndex:
    """Carga conversiones recientes y arma el índice. Vacío si no hay company_id."""
    if company_id is None:
        return {}
    try:
        payloads = fetch_recent_conversion_row_lists(
            int(company_id), template_id=template_id, limit=limit
        )
    except Exception as e:
        logger.warning("product_label_memory: no se pudo leer historial: %s", e)
        return {}
    return build_product_memory_index(payloads)
