"""
Padrón de impuestos desde view_padron_facturia_actualizado (ids_impuestos / impuesto).
El padrón histórico principal (rubro, diario, cuenta) sigue en DB_TABLE_NAME (vista vieja).
"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from psycopg2 import connect
from psycopg2.extras import RealDictCursor
from psycopg2.sql import Identifier, SQL
from rapidfuzz import fuzz, process as rf_process

from facturia_matching.config import (
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_SCHEMA,
    DB_TABLE_NAME_TAXES,
    DB_USER,
    get_table_columns as cfg_get_table_columns,
)

# account.tax purchase — ids vistos en ids_impuestos del padrón
IVA_TAX_IDS = frozenset({53, 55, 57, 61, 63})
IVA_TAX_ID_TO_PCT: Dict[int, str] = {
    63: "21",
    61: "10,5",
    53: "IVA No Corresponde",
    55: "IVA No Gravado",
    57: "IVA Exento",
}

_TAX_PADRON_CACHE: Optional[List[Dict[str, Any]]] = None
_TAX_PADRON_BY_CUIT: Optional[Dict[str, List[int]]] = None
_TAX_NAME_BY_ID: Optional[Dict[int, str]] = None
_TAX_ID_BY_NAME: Optional[Dict[str, int]] = None


def _normalize(s: Any) -> str:
    if s is None:
        return ""
    return " ".join(str(s).strip().split())


def _digits_only(s: str) -> str:
    return "".join(ch for ch in _normalize(s) if ch.isdigit())


def _pg_conn():
    return connect(
        host=DB_HOST,
        port=int(DB_PORT),
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
    )


def _tax_table_ident() -> SQL:
    return SQL("{}.{}").format(Identifier(DB_SCHEMA), Identifier(DB_TABLE_NAME_TAXES))


def parse_ids_impuestos(raw: Any) -> List[int]:
    """Parsea '[63]', '[63, 70]' o lista a ids enteros."""
    if raw is None:
        return []
    if isinstance(raw, list):
        out = []
        for x in raw:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                pass
        return out
    s = str(raw).strip()
    if not s:
        return []
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return [int(x) for x in parsed if str(x).strip().isdigit() or isinstance(x, int)]
    except json.JSONDecodeError:
        pass
    return [int(x) for x in re.findall(r"\d+", s)]


def _tax_padron_rows(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    if limit is None:
        limit = int(os.getenv("PADRON_TAX_LIMIT", "50000"))
    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            q = SQL(
                """
                SELECT
                  nombre_contacto AS name,
                  numero_documento AS doc,
                  ids_impuestos,
                  impuesto
                FROM {t}
                WHERE nombre_contacto IS NOT NULL AND trim(nombre_contacto) <> ''
                LIMIT {lim}
                """
            ).format(t=_tax_table_ident(), lim=SQL(str(int(limit))))
            cur.execute(q)
            rows = []
            for r in cur.fetchall():
                tax_ids = parse_ids_impuestos(r.get("ids_impuestos"))
                imp = r.get("impuesto")
                if imp is not None and str(imp).strip().isdigit() and int(imp) not in tax_ids:
                    tax_ids = [int(imp)] + tax_ids
                rows.append(
                    {
                        "name": _normalize(r.get("name")),
                        "doc": _normalize(r.get("doc")),
                        "tax_ids": tax_ids,
                    }
                )
            return rows


def get_tax_padron_cached() -> List[Dict[str, Any]]:
    global _TAX_PADRON_CACHE, _TAX_PADRON_BY_CUIT
    if _TAX_PADRON_CACHE is None:
        try:
            _TAX_PADRON_CACHE = _tax_padron_rows()
        except Exception:
            _TAX_PADRON_CACHE = []
        _TAX_PADRON_BY_CUIT = None
    return _TAX_PADRON_CACHE


def get_tax_padron_by_cuit() -> Dict[str, List[int]]:
    """Índice CUIT → tax_ids (O(1) vs scan lineal del padrón)."""
    global _TAX_PADRON_BY_CUIT
    if _TAX_PADRON_BY_CUIT is None:
        by_cuit: Dict[str, List[int]] = {}
        for r in get_tax_padron_cached():
            doc = _digits_only(r.get("doc") or "")
            if doc and r.get("tax_ids"):
                by_cuit[doc] = list(r["tax_ids"])
        _TAX_PADRON_BY_CUIT = by_cuit
    return _TAX_PADRON_BY_CUIT


def clear_tax_padron_cache() -> None:
    global _TAX_PADRON_CACHE, _TAX_PADRON_BY_CUIT, _TAX_NAME_BY_ID, _TAX_ID_BY_NAME
    _TAX_PADRON_CACHE = None
    _TAX_PADRON_BY_CUIT = None
    _TAX_NAME_BY_ID = None
    _TAX_ID_BY_NAME = None


def padron_tax_match_key(nombre: str, cuit: str) -> str:
    cuit_n = _digits_only(cuit)
    if cuit_n:
        return f"cuit:{cuit_n}"
    return f"name:{_normalize(nombre).upper()}"


class PadronTaxMatchCache:
    """Cache por request: un match de impuestos por proveedor/comprobante."""

    def __init__(self) -> None:
        self._matches: Dict[str, Tuple[List[int], float]] = {}

    def get(self, nombre: str, cuit: str) -> Tuple[List[int], float]:
        key = padron_tax_match_key(nombre, cuit)
        if key not in self._matches:
            self._matches[key] = match_padron_taxes(nombre, cuit)
        return self._matches[key]


def _label_key(name: str) -> str:
    return _normalize(name).upper()


def get_tax_id_by_name() -> Dict[str, int]:
    global _TAX_ID_BY_NAME
    if _TAX_ID_BY_NAME is not None:
        return _TAX_ID_BY_NAME
    out: Dict[str, int] = {}
    for tid, nm in get_tax_name_by_id().items():
        key = _label_key(nm)
        if key and key not in out:
            out[key] = int(tid)
    _TAX_ID_BY_NAME = out
    return out


def resolve_tax_label_to_id(label: str, *, min_score: float = 96.0) -> Optional[int]:
    """
    Resuelve etiqueta UI (ej. Percepción IIBB CABA Sufrida) a account.tax id.
    Percepciones IIBB: solo coincidencia exacta (evita mapear La Rioja → ARBA por fuzzy).
    Otros impuestos: fuzzy estricto si no hay match exacto.
    """
    key = _label_key(label)
    if not key:
        return None
    by_name = get_tax_id_by_name()
    if key in by_name:
        return by_name[key]

    if "IIBB" in key or "PERCEPCI" in key:
        return None

    choices = list(by_name.keys())
    if not choices:
        return None
    best = rf_process.extractOne(key, choices, scorer=fuzz.WRatio)
    if not best or float(best[1]) < min_score:
        return None
    return by_name.get(best[0])


def _otros_impuesto_keys_from_row(row: Dict[str, Any]) -> List[str]:
    keys: List[str] = []
    for k in sorted(row.keys()):
        if not isinstance(k, str):
            continue
        if k == "otros_impuestos" or (k.startswith("otros_impuestos_") and not k.endswith("_monto")):
            keys.append(k)
    return keys


def _parse_row_padron_tax_ids(row: Dict[str, Any]) -> List[int]:
    raw = row.get("_padron_tax_ids") or []
    out: List[int] = []
    for x in raw:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            pass
    return out


def match_padron_taxes(nombre: str, cuit: str) -> Tuple[List[int], float]:
    """Devuelve (tax_ids, score). Score 100 si match por CUIT."""
    nombre_n = _normalize(nombre)
    cuit_n = _digits_only(cuit)

    if cuit_n:
        tax_ids = get_tax_padron_by_cuit().get(cuit_n)
        if tax_ids:
            return (list(tax_ids), 100.0)

    padron = get_tax_padron_cached()
    names = [(_normalize(r.get("name")), r) for r in padron if r.get("tax_ids")]
    choices = [n for n, _ in names]
    if not nombre_n or not choices:
        return ([], 0.0)

    best = rf_process.extractOne(nombre_n, choices, scorer=fuzz.WRatio)
    if not best or best[1] < 72.0:
        return ([], float(best[1]) if best else 0.0)
    idx = int(best[2])
    return (list(names[idx][1]["tax_ids"]), float(best[1]))


def get_tax_name_by_id() -> Dict[int, str]:
    global _TAX_NAME_BY_ID
    if _TAX_NAME_BY_ID is not None:
        return _TAX_NAME_BY_ID
    try:
        from odoo_api import get_odoo_uid, is_odoo_configured, odoo_search_read

        if not is_odoo_configured() or not get_odoo_uid():
            _TAX_NAME_BY_ID = {}
            return _TAX_NAME_BY_ID
        rows = odoo_search_read(
            "account.tax",
            [("type_tax_use", "=", "purchase")],
            ["id", "name"],
            limit=500,
        )
        _TAX_NAME_BY_ID = {int(r["id"]): _normalize(r.get("name")) for r in rows if r.get("id")}
    except Exception:
        _TAX_NAME_BY_ID = {}
    return _TAX_NAME_BY_ID or {}


def split_iva_and_other_tax_ids(tax_ids: List[int]) -> Tuple[List[int], List[int]]:
    iva = [i for i in tax_ids if i in IVA_TAX_IDS]
    other = [i for i in tax_ids if i not in IVA_TAX_IDS]
    return iva, other


def primary_iva_tax_id(iva_ids: List[int]) -> Optional[int]:
    """Primer impuesto IVA del padrón (para invoice_line_ids/tax_id/.id)."""
    if not iva_ids:
        return None
    # Preferir 21% si está en la lista
    if 63 in iva_ids:
        return 63
    return iva_ids[0]


def iva_pct_from_tax_id(tax_id: int) -> str:
    return IVA_TAX_ID_TO_PCT.get(tax_id, "")


def apply_padron_taxes_to_row(
    row: Dict[str, Any],
    nombre: str,
    cuit: str,
    *,
    tax_match: Optional[Tuple[List[int], float]] = None,
    name_by_id: Optional[Dict[int, str]] = None,
    overwrite_iva: bool = False,
    overwrite_otros: bool = False,
) -> None:
    """
    Enriquece fila con impuestos del padrón nuevo si hay match.
    Guarda _padron_tax_ids y _padron_tax_id_primary para export CSV.
    """
    if tax_match is None:
        tax_ids, score = match_padron_taxes(nombre, cuit)
    else:
        tax_ids, score = tax_match
    if not tax_ids:
        return

    row["_padron_tax_match_score"] = score
    row["_padron_tax_ids"] = [str(i) for i in tax_ids]

    iva_ids, other_ids = split_iva_and_other_tax_ids(tax_ids)
    primary_iva = primary_iva_tax_id(iva_ids)
    if primary_iva is not None:
        row["_padron_tax_id_primary"] = str(primary_iva)

    if name_by_id is None:
        name_by_id = get_tax_name_by_id()

    iva_pct = _normalize(row.get("iva_pct"))
    if primary_iva is not None and (overwrite_iva or not iva_pct):
        suggested = iva_pct_from_tax_id(primary_iva)
        if suggested:
            row["iva_pct"] = suggested

    otros = _normalize(row.get("otros_impuestos"))
    if other_ids and (overwrite_otros or not otros):
        first_other = name_by_id.get(other_ids[0]) or ""
        if first_other:
            row["otros_impuestos"] = first_other

    # Impuestos adicionales (más de uno) — segundo otro en columna dinámica si existe helper
    if len(other_ids) > 1:
        for n, tid in enumerate(other_ids[1:], start=2):
            key = f"otros_impuestos_{n}"
            nm = name_by_id.get(tid) or ""
            if nm and not _normalize(row.get(key)):
                row[key] = nm

    if other_ids:
        row["_padron_other_tax_ids"] = [str(i) for i in other_ids]


def tax_id_for_csv_export(row: Dict[str, Any]) -> str:
    """
    ID para invoice_line_ids/tax_id/.id: padrón nuevo > inferencia por iva_pct > vacío.
    """
    if not isinstance(row, dict):
        return ""
    primary = _normalize(row.get("_padron_tax_id_primary"))
    if primary:
        return primary

    iva_pct = _normalize(row.get("iva_pct"))
    iva_digits = "".join(ch for ch in iva_pct if ch.isdigit() or ch in ".,")
    iva_digits = iva_digits.replace(",", ".").strip()
    try:
        if iva_digits and abs(float(iva_digits) - 21.0) < 1e-9:
            return "63"
        if iva_digits and abs(float(iva_digits) - 10.5) < 1e-9:
            return "61"
    except ValueError:
        pass
    if iva_pct in ("IVA No Corresponde", "IVA No Gravado", "IVA Exento"):
        inv = {"IVA No Corresponde": "53", "IVA No Gravado": "55", "IVA Exento": "57"}
        return inv.get(iva_pct, "")
    return ""


def build_csv_additional_taxes(row: Dict[str, Any]) -> List[str]:
    """
    Impuestos adicionales para columnas invoice_line_ids/tax_ids del CSV.
    Prioriza IDs numéricos de Odoo (IIBB, percepciones); si no hay id, usa el nombre.
    """
    if not isinstance(row, dict):
        return []

    primary_s = tax_id_for_csv_export(row)
    try:
        primary_int = int(primary_s) if primary_s else None
    except ValueError:
        primary_int = None

    seen_ids: set = set()
    seen_labels: set = set()
    out: List[str] = []

    def _add(tid: Optional[int], label: str = "") -> None:
        if tid is not None:
            if tid == primary_int or tid in seen_ids:
                return
            seen_ids.add(tid)
            out.append(str(tid))
            return
        lab = _normalize(label)
        lab_k = lab.upper()
        if not lab or lab_k in seen_labels:
            return
        seen_labels.add(lab_k)
        out.append(lab)

    # 1) IDs no-IVA del padrón (más confiable para IIBB)
    for tid in _parse_row_padron_tax_ids(row):
        if tid in IVA_TAX_IDS:
            continue
        _add(tid)

    # 2) otros_impuestos de la fila / FacturIA → id Odoo si existe
    for k in _otros_impuesto_keys_from_row(row):
        label = _normalize(row.get(k))
        if not label:
            continue
        tid = resolve_tax_label_to_id(label)
        _add(tid, label)

    return out


def build_csv_tax_ids_dot_id(row: Dict[str, Any]) -> str:
    """
    IDs de impuestos para Odoo en una sola celda (invoice_line_ids/tax_ids/.id).
    Ejemplo: "63,1" = IVA 21% + percepción IIBB CABA.
    Solo incluye IDs numéricos; etiquetas sin id en catálogo se omiten aquí.
    """
    if not isinstance(row, dict):
        return ""
    ids: List[str] = []
    seen: set = set()

    primary = tax_id_for_csv_export(row)
    if primary and primary.isdigit():
        seen.add(primary)
        ids.append(primary)

    for t in build_csv_additional_taxes(row):
        if t.isdigit() and t not in seen:
            seen.add(t)
            ids.append(t)

    return ",".join(ids)
