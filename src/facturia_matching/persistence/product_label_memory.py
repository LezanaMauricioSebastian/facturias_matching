"""Aprendizaje de producto: última elección confirmada por proveedor + etiqueta.

Tabla dedicada `product_label_memory` en `PROCESS_SCHEMA`
(staging: sudataco_staging, prod: sudataco_facturia).

Solo persiste filas con `invoice_line_ids/product_id` y sin `__product_suggested`
(elecciones del operador / match OC, no fuzzy sin confirmar).
"""

from __future__ import annotations

import logging
import re
import threading
import unicodedata
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from facturia_matching.infra.config import PROCESS_SCHEMA, _mysql_table_ref, get_mysql_connection
from facturia_matching.odoo.env import get_conversion_template_id
from facturia_matching.persistence.process_conversions import (
    CONVERSIONS_TABLE,
    parse_converted_payload,
)

logger = logging.getLogger(__name__)

MEMORY_TABLE = "product_label_memory"
DEFAULT_CONVERSION_LIMIT = 100
_MIN_LABEL_LEN = 2
_MAX_LABEL_LEN = 512

# Separadores frecuentes en etiquetas de factura (packs, OCR).
_SEP_RE = re.compile(r"[*×·•_/\\|]+")
# Puntuación restante (salvo punto decimal); se vuelve espacio.
_PUNCT_RE = re.compile(r"[^\w.\s]+", re.UNICODE)
# Ceros a la izquierda: 06 → 6, 06PET → 6PET (no toca 600 / 600PET).
_LEADING_ZERO_RE = re.compile(r"\b0+(\d+)(?=[A-Z]|\b)")
_WS_RE = re.compile(r"\s+")

from dataclasses import dataclass

from rapidfuzz import fuzz

# partner_id + label_key → MemoryChoice
ProductMemoryIndex = Dict[Tuple[int, str], "MemoryChoice"]

# Fuzzy sobre keys ya normalizadas (exacto siempre gana).
# 88: une variantes OCR/formato (SPRITE …06PET vs …6 6PET) sin bajar tanto
# como para confiar ciegamente en un solo token compartido.
MEMORY_FUZZY_MIN_SCORE = 88.0

_table_ensured = False
_table_lock = threading.Lock()


@dataclass(frozen=True)
class MemoryChoice:
    """Última elección confirmada: producto Odoo + UM opcional."""

    product_id: int
    uom_id: Optional[int] = None

    def __int__(self) -> int:
        """Compat: tratar como product_id en contextos legacy."""
        return int(self.product_id)


def normalize_label_key(raw: Any) -> str:
    """Clave estable para memoria: misma función al guardar y al buscar.

    - Unicode NFKD sin acentos
    - Mayúsculas
    - `,` decimal → `.` (`0,5L` → `0.5L`)
    - `*` / `×` / `/` etc. → espacio
    - Resto de puntuación → espacio
    - Ceros a la izquierda (`06` → `6`, `06PET` → `6PET`)
    - Espacios colapsados; trunca a `_MAX_LABEL_LEN`
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.upper()
    s = s.replace(",", ".")
    s = _SEP_RE.sub(" ", s)
    s = _PUNCT_RE.sub(" ", s)
    s = _LEADING_ZERO_RE.sub(r"\1", s)
    s = _WS_RE.sub(" ", s).strip(" .")
    if len(s) > _MAX_LABEL_LEN:
        return s[:_MAX_LABEL_LEN]
    return s


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
) -> Iterable[Tuple[int, str, int, Optional[int]]]:
    """Yield (partner_id, label_key, product_id, uom_id) from confirmed row choices."""
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
            uom_raw = _normalize(row.get("__um_empresa_id"))
            uom_id = int(uom_raw) if uom_raw.isdigit() and int(uom_raw) > 0 else None
            yield partner_id, label, product_id, uom_id


def build_product_memory_index(
    conversion_row_lists: List[List[Dict[str, Any]]],
) -> ProductMemoryIndex:
    """Índice partner+label → MemoryChoice. La primera aparición gana (más reciente)."""
    index: ProductMemoryIndex = {}
    for rows in conversion_row_lists or []:
        if not isinstance(rows, list):
            continue
        for partner_id, label_key, product_id, uom_id in iter_confirmed_choices(rows):
            key = (partner_id, label_key)
            if key not in index:
                index[key] = MemoryChoice(product_id=product_id, uom_id=uom_id)
    return index


def _memory_labels_conflict(a: str, b: str) -> bool:
    """Rechaza pares que RapidFuzz acerca pero son variantes incompatibles."""
    ta = set(a.split())
    tb = set(b.split())
    # Agua sin gas vs con gas (tras normalize: C/G → C G).
    a_still = "SIN" in ta and "GAS" in ta
    b_still = "SIN" in tb and "GAS" in tb
    a_spark = (("CON" in ta and "GAS" in ta) or ({"C", "G"} <= ta)) and not a_still
    b_spark = (("CON" in tb and "GAS" in tb) or ({"C", "G"} <= tb)) and not b_still
    if (a_still and b_spark) or (b_still and a_spark):
        return True
    # ZERO solo de un lado (Coca vs Coca Zero).
    if ("ZERO" in ta) != ("ZERO" in tb):
        return True
    return False


def _coerce_memory_choice(value: Any) -> Optional[MemoryChoice]:
    """Acepta MemoryChoice o product_id int (tests / índices viejos)."""
    if value is None:
        return None
    if isinstance(value, MemoryChoice):
        return value if value.product_id > 0 else None
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return MemoryChoice(product_id=pid) if pid > 0 else None


def lookup_in_index(
    index: ProductMemoryIndex,
    partner_id: Any,
    label: Any,
    *,
    fuzzy_min_score: float = MEMORY_FUZZY_MIN_SCORE,
) -> Optional[MemoryChoice]:
    """Busca elección: exacto sobre label normalizada, luego fuzzy RapidFuzz."""
    raw_partner = _normalize(partner_id)
    if not raw_partner.isdigit():
        return None
    label_key = normalize_label_key(label)
    if len(label_key) < _MIN_LABEL_LEN:
        return None
    partner = int(raw_partner)
    exact = _coerce_memory_choice(index.get((partner, label_key)))
    if exact is not None:
        return exact

    best: Optional[MemoryChoice] = None
    best_score = 0.0
    for (pid, key), raw_choice in index.items():
        if pid != partner or len(key) < _MIN_LABEL_LEN:
            continue
        if _memory_labels_conflict(label_key, key):
            continue
        choice = _coerce_memory_choice(raw_choice)
        if choice is None:
            continue
        score = float(fuzz.token_set_ratio(label_key, key))
        if score > best_score:
            best_score = score
            best = choice
    if best is not None and best_score >= float(fuzzy_min_score):
        return best
    return None


def _memory_table_ref() -> str:
    return _mysql_table_ref(PROCESS_SCHEMA, MEMORY_TABLE)


def ensure_product_label_memory_table() -> None:
    """CREATE TABLE IF NOT EXISTS (+ columna uom_id si falta) en el schema actual."""
    global _table_ensured
    if _table_ensured:
        return
    with _table_lock:
        if _table_ensured:
            return
        table_ref = _memory_table_ref()
        conn = get_mysql_connection()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {table_ref} (
                        id BIGINT NOT NULL AUTO_INCREMENT,
                        company_id INT NOT NULL,
                        template_id INT NOT NULL,
                        partner_id INT NOT NULL,
                        label_key VARCHAR({_MAX_LABEL_LEN}) NOT NULL,
                        product_id INT NOT NULL,
                        uom_id INT NULL,
                        source_process_id INT NULL,
                        source_conversion_id INT NULL,
                        updated_at DATETIME NOT NULL,
                        PRIMARY KEY (id),
                        UNIQUE KEY uq_product_label_memory
                            (company_id, template_id, partner_id, label_key),
                        KEY idx_product_label_memory_lookup
                            (company_id, template_id, partner_id, label_key)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                # Tablas creadas antes de aprender UM.
                cur.execute(f"SHOW COLUMNS FROM {table_ref} LIKE 'uom_id'")
                if not cur.fetchone():
                    cur.execute(
                        f"ALTER TABLE {table_ref} ADD COLUMN uom_id INT NULL AFTER product_id"
                    )
                conn.commit()
                _table_ensured = True
                logger.info(
                    "product_label_memory: tabla lista en schema=%s",
                    PROCESS_SCHEMA,
                )
            finally:
                cur.close()
        finally:
            conn.close()


def fetch_memory_index_from_table(
    company_id: int,
    *,
    template_id: Optional[int] = None,
) -> ProductMemoryIndex:
    """Lee el índice desde la tabla dedicada."""
    ensure_product_label_memory_table()
    tid = int(template_id) if template_id is not None else get_conversion_template_id()
    table_ref = _memory_table_ref()
    conn = get_mysql_connection()
    index: ProductMemoryIndex = {}
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                f"""
                SELECT partner_id, label_key, product_id, uom_id
                FROM {table_ref}
                WHERE company_id = %s AND template_id = %s
                """,
                (int(company_id), tid),
            )
            for row in cur.fetchall() or []:
                try:
                    partner_id = int(row["partner_id"])
                    product_id = int(row["product_id"])
                    label_key = normalize_label_key(row.get("label_key"))
                    uom_raw = row.get("uom_id")
                    uom_id = (
                        int(uom_raw)
                        if uom_raw is not None and str(uom_raw).strip().isdigit()
                        and int(uom_raw) > 0
                        else None
                    )
                except (TypeError, ValueError, KeyError):
                    continue
                if partner_id <= 0 or product_id <= 0 or len(label_key) < _MIN_LABEL_LEN:
                    continue
                index[(partner_id, label_key)] = MemoryChoice(
                    product_id=product_id, uom_id=uom_id
                )
        finally:
            cur.close()
    finally:
        conn.close()
    return index


def upsert_product_memory_choices(
    company_id: int,
    rows: List[Dict[str, Any]],
    *,
    template_id: Optional[int] = None,
    source_process_id: Optional[int] = None,
    source_conversion_id: Optional[int] = None,
) -> int:
    """Persiste elecciones confirmadas (producto + UM). Devuelve filas tocadas."""
    if company_id is None or not rows:
        return 0
    choices = list(iter_confirmed_choices(rows))
    if not choices:
        return 0

    ensure_product_label_memory_table()
    tid = int(template_id) if template_id is not None else get_conversion_template_id()
    now = datetime.now().replace(microsecond=0)
    table_ref = _memory_table_ref()
    # Última aparición de cada clave en este save gana.
    by_key: Dict[Tuple[int, str], MemoryChoice] = {}
    for partner_id, label_key, product_id, uom_id in choices:
        by_key[(partner_id, label_key)] = MemoryChoice(
            product_id=product_id, uom_id=uom_id
        )

    conn = get_mysql_connection()
    touched = 0
    try:
        cur = conn.cursor()
        try:
            sql = f"""
                INSERT INTO {table_ref}
                    (company_id, template_id, partner_id, label_key, product_id, uom_id,
                     source_process_id, source_conversion_id, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    product_id = VALUES(product_id),
                    uom_id = VALUES(uom_id),
                    source_process_id = VALUES(source_process_id),
                    source_conversion_id = VALUES(source_conversion_id),
                    updated_at = VALUES(updated_at)
            """
            for (partner_id, label_key), choice in by_key.items():
                cur.execute(
                    sql,
                    (
                        int(company_id),
                        tid,
                        partner_id,
                        label_key,
                        choice.product_id,
                        choice.uom_id,
                        source_process_id,
                        source_conversion_id,
                        now,
                    ),
                )
                touched += 1
            conn.commit()
        finally:
            cur.close()
    finally:
        conn.close()
    return touched


def fetch_recent_conversion_row_lists(
    company_id: int,
    *,
    template_id: Optional[int] = None,
    limit: int = DEFAULT_CONVERSION_LIMIT,
) -> List[List[Dict[str, Any]]]:
    """Fallback / seed: conversiones recientes (más nuevas primero).

    Excluye conversiones cuyo `process` tiene baja lógica (`deleted_at` no nulo).
    """
    if company_id is None:
        return []
    tid = int(template_id) if template_id is not None else get_conversion_template_id()
    lim = max(1, min(int(limit or DEFAULT_CONVERSION_LIMIT), 200))
    conv_ref = _mysql_table_ref(PROCESS_SCHEMA, CONVERSIONS_TABLE)
    process_ref = _mysql_table_ref(PROCESS_SCHEMA, "process")
    conn = get_mysql_connection()
    out: List[List[Dict[str, Any]]] = []
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                f"""
                SELECT pc.id, pc.process_id, pc.converted_data
                FROM {conv_ref} pc
                INNER JOIN {process_ref} p ON p.id = pc.process_id
                WHERE pc.company_id = %s
                  AND pc.template_id = %s
                  AND p.deleted_at IS NULL
                ORDER BY pc.updated_at DESC, pc.id DESC
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
                    # Attach source ids as private attrs via wrapper dicts? Keep plain rows;
                    # seed upsert uses process_id from outer loop.
                    out.append(
                        {
                            "process_id": row.get("process_id"),
                            "conversion_id": row.get("id"),
                            "rows": rows,
                        }
                    )
        finally:
            cur.close()
    finally:
        conn.close()
    return out


def _seed_table_from_conversions(
    company_id: int,
    *,
    template_id: Optional[int] = None,
    limit: int = DEFAULT_CONVERSION_LIMIT,
) -> ProductMemoryIndex:
    """Rellena la tabla desde conversiones recientes (lazy, una vez si está vacía)."""
    tid = int(template_id) if template_id is not None else get_conversion_template_id()
    payloads = fetch_recent_conversion_row_lists(
        int(company_id), template_id=tid, limit=limit
    )
    # payloads más recientes primero → iterar al revés para que lo nuevo pise.
    for payload in reversed(payloads or []):
        if isinstance(payload, dict):
            rows = payload.get("rows") or []
            upsert_product_memory_choices(
                int(company_id),
                rows,
                template_id=tid,
                source_process_id=payload.get("process_id"),
                source_conversion_id=payload.get("conversion_id"),
            )
        elif isinstance(payload, list):
            upsert_product_memory_choices(
                int(company_id), payload, template_id=tid
            )
    return fetch_memory_index_from_table(int(company_id), template_id=tid)


def build_memory_index_for_company(
    company_id: Optional[int],
    *,
    template_id: Optional[int] = None,
    limit: int = DEFAULT_CONVERSION_LIMIT,
) -> ProductMemoryIndex:
    """Carga memoria desde la tabla. Si está vacía, seed desde conversiones."""
    if company_id is None:
        return {}
    try:
        index = fetch_memory_index_from_table(
            int(company_id), template_id=template_id
        )
        if index:
            return index
        return _seed_table_from_conversions(
            int(company_id), template_id=template_id, limit=limit
        )
    except Exception as e:
        logger.warning("product_label_memory: no se pudo leer historial: %s", e)
        # Último recurso: índice en memoria desde conversiones, sin persistir.
        try:
            raw = fetch_recent_conversion_row_lists(
                int(company_id), template_id=template_id, limit=limit
            )
            row_lists: List[List[Dict[str, Any]]] = []
            for payload in raw:
                if isinstance(payload, dict):
                    rows = payload.get("rows")
                    if isinstance(rows, list):
                        row_lists.append(rows)
                elif isinstance(payload, list):
                    row_lists.append(payload)
            return build_product_memory_index(row_lists)
        except Exception as e2:
            logger.warning("product_label_memory: fallback conversiones falló: %s", e2)
            return {}
