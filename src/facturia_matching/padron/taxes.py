"""
Padrón de impuestos desde view_padron_facturia_actualizado (ids_impuestos / impuesto).
El padrón histórico principal (rubro, diario, cuenta) sigue en DB_TABLE_NAME (vista vieja).
"""
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from psycopg2.extras import RealDictCursor
from psycopg2.sql import Identifier, SQL
from rapidfuzz import fuzz, process as rf_process

from facturia_matching.infra.config import (
    DB_SCHEMA,
    DB_TABLE_NAME_TAXES,
    get_table_columns as cfg_get_table_columns,
    pg_connect,
)

# account.tax purchase — ids históricos Dinner (solo fallback sin Odoo)
IVA_TAX_IDS = frozenset({53, 55, 57, 61, 63})
# Fallback estático si no hay Odoo (dev offline). En runtime se arma desde account.tax.
IVA_TAX_ID_TO_PCT: Dict[int, str] = {
    63: "21",
    61: "10,5",
    65: "27",
    53: "IVA No Corresponde",
    55: "IVA No Gravado",
    57: "IVA Exento",
}
_LEGACY_DINNER_IVA_BY_RATE: Dict[float, int] = {
    21.0: 63,
    10.5: 61,
    27.0: 65,
}
_LEGACY_DINNER_SPECIAL_IVA: Dict[str, int] = {
    "IVA No Corresponde": 53,
    "IVA No Gravado": 55,
    "IVA Exento": 57,
}
_SPECIAL_IVA_LABELS: Dict[str, str] = {
    "IVA NO CORRESPONDE": "IVA No Corresponde",
    "IVA NO GRAVADO": "IVA No Gravado",
    "IVA EXENTO": "IVA Exento",
}
_CANONICAL_SPECIAL_IVA_LABELS = frozenset(_SPECIAL_IVA_LABELS.values())
_ATTACHABLE_ZERO_IVA_LABELS = frozenset({"IVA Exento", "IVA No Gravado"})
_SPECIAL_IVA_NAME_KEYS: Dict[str, Tuple[str, ...]] = {
    "IVA NO CORRESPONDE": ("IVA NO CORRESP", "IVA NO CORRESPONDE"),
    "IVA NO GRAVADO": ("IVA NO GRAV", "IVA NO GRAVADO"),
    "IVA EXENTO": ("IVA EXEN", "IVA EXENTO"),
}

_TAX_PADRON_CACHE: Optional[List[Dict[str, Any]]] = None
_TAX_PADRON_BY_CUIT: Optional[Dict[str, List[int]]] = None
_TAX_NAME_BY_ID: Optional[Dict[int, str]] = None
_TAX_ID_BY_NAME: Optional[Dict[str, int]] = None
_PURCHASE_IVA_TAXES_CACHE: Optional[List[Dict[str, Any]]] = None
_IVA_TAX_IDS_CACHE: Optional[frozenset] = None
_PADRON_SOURCE_IVA_SEMANTICS_CACHE: Optional[Dict[int, str]] = None
_PADRON_SOURCE_TAX_NAMES_CACHE: Optional[Dict[int, str]] = None


def _normalize(s: Any) -> str:
    if s is None:
        return ""
    return " ".join(str(s).strip().split())


def _digits_only(s: str) -> str:
    return "".join(ch for ch in _normalize(s) if ch.isdigit())


def _pg_conn():
    return pg_connect()


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


def clear_odoo_tax_catalog_cache() -> None:
    """Invalida catálogo IVA/nombres Odoo (cambia por perfil tenant)."""
    global _TAX_NAME_BY_ID, _TAX_ID_BY_NAME, _PURCHASE_IVA_TAXES_CACHE, _IVA_TAX_IDS_CACHE
    global _PADRON_SOURCE_IVA_SEMANTICS_CACHE, _PADRON_SOURCE_TAX_NAMES_CACHE
    _TAX_NAME_BY_ID = None
    _TAX_ID_BY_NAME = None
    _PURCHASE_IVA_TAXES_CACHE = None
    _IVA_TAX_IDS_CACHE = None
    _PADRON_SOURCE_IVA_SEMANTICS_CACHE = None
    _PADRON_SOURCE_TAX_NAMES_CACHE = None


def clear_tax_padron_cache() -> None:
    global _TAX_PADRON_CACHE, _TAX_PADRON_BY_CUIT
    _TAX_PADRON_CACHE = None
    _TAX_PADRON_BY_CUIT = None
    clear_odoo_tax_catalog_cache()


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


def _ascii_upper(s: str) -> str:
    repl = str.maketrans("ÁÉÍÓÚÜÑ", "AEIOUUN")
    return s.upper().translate(repl)


# Jurisdicción en etiqueta UI → sufijo en account.tax Odoo (ej. "P. IIBB CABA").
_IIBB_JURISDICTION_TO_ODOO_SUFFIX: Dict[str, str] = {
    "CABA": "CABA",
    "ARBA": "BA",
    "CATAMARCA": "CTS",
    "CORDOBA": "CBA",
    "CORRIENTES": "C",
    "ENTRE RIOS": "ER",
    "JUJUY": "J",
    "MENDOZA": "MZA",
    "LA RIOJA": "LR",
    "SALTA": "S",
    "SAN JUAN": "SJ",
    "SAN LUIS": "SL",
    "SANTA FE": "SF",
    "SANTIAGO DEL ESTERO": "SE",
    "TUCUMAN": "T",
    "CHACO": "CHO",
    "CHUBUT": "CHT",
    "FORMOSA": "F",
    "MISIONES": "MS",
    "NEUQUEN": "N",
    "LA PAMPA": "LP",
    "RIO NEGRO": "RN",
    "SANTA CRUZ": "SC",
    "TIERRA DEL FUEGO": "TAIS",
}


def _extract_iibb_jurisdiction(label_key: str) -> Optional[str]:
    """Extrae jurisdicción de etiquetas UI o abreviadas (ej. IIBB CABA sufrida)."""
    key = _ascii_upper(label_key)
    patterns = (
        r"^PERCEPCION IIBB (.+?) (?:SUFRIDA|APLICADA)$",
        r"^IIBB (.+?) (?:SUFRIDA|APLICADA)$",
        r"^IIBB (.+)$",
    )
    for pattern in patterns:
        m = re.match(pattern, key)
        if m:
            juris = _ascii_upper(_normalize(m.group(1)))
            if juris:
                return juris
    return None


def _resolve_iibb_label_to_id(label: str, by_name: Dict[str, int]) -> Optional[int]:
    key = _label_key(label)
    if "IIBB" not in key:
        return None
    juris = _extract_iibb_jurisdiction(key)
    if not juris:
        return None
    suffix = _IIBB_JURISDICTION_TO_ODOO_SUFFIX.get(juris)
    if not suffix:
        return None
    odoo_key = _label_key(f"P. IIBB {suffix}")
    if odoo_key in by_name:
        return by_name[odoo_key]
    iibb_suffix = f"IIBB {suffix}"
    for tax_key, tid in by_name.items():
        if "IIBB" in tax_key and tax_key.endswith(iibb_suffix):
            return tid
    return None


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


# Etiquetas UI → nombres abreviados en Odoo (ej. Aliare: Perc Gananc, Perc IVA).
_UI_TAX_NAME_ALIASES: Dict[str, Tuple[str, ...]] = {
    "PERCEPCION GANANCIAS SUFRIDA": ("PERC GANANC", "PERCEPCION GANANCIAS"),
    "PERCEPCION GANANCIAS APLICADA": ("PERC GANANC", "PERCEPCION GANANCIAS"),
    "PERCEPCION IVA SUFRIDA": ("PERC IVA", "PERCEPCION IVA"),
    "PERCEPCION IVA APLICADA": ("PERC IVA", "PERCEPCION IVA"),
    "IVA ADICIONAL 20%": ("IVA ADIC 20%", "IVA ADICIONAL 20%"),
}


def _alias_tax_id_for_label(key: str, by_name: Dict[str, int]) -> Optional[int]:
    ascii_key = _ascii_upper(key)
    for alias in _UI_TAX_NAME_ALIASES.get(ascii_key, ()):
        alias_key = _label_key(alias)
        if alias_key in by_name:
            return by_name[alias_key]
        ascii_alias = _ascii_upper(alias_key)
        for tax_key, tid in by_name.items():
            if _ascii_upper(tax_key) == ascii_alias:
                return tid
    return None


def resolve_tax_label_to_id(label: str, *, min_score: float = 96.0) -> Optional[int]:
    """
    Resuelve etiqueta UI (ej. Percepción IIBB CABA Sufrida) a account.tax id.
    Percepciones IIBB: match por jurisdicción contra nombres Odoo (ej. P. IIBB CABA).
    Otras percepciones: alias a nombres cortos de Odoo (Perc Gananc / Perc IVA) y fuzzy.
    """
    key = _label_key(label)
    if not key:
        return None
    by_name = get_tax_id_by_name()
    if key in by_name:
        return by_name[key]

    aliased = _alias_tax_id_for_label(key, by_name)
    if aliased is not None:
        return aliased

    if "IIBB" in key:
        return _resolve_iibb_label_to_id(label, by_name)

    if "PERCEPCI" in key:
        iibb_tid = _resolve_iibb_label_to_id(label, by_name)
        if iibb_tid is not None:
            return iibb_tid

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


def _is_purchase_iva_tax_name(name: str) -> bool:
    key = _ascii_upper(_normalize(name))
    if not key:
        return False
    if key in _SPECIAL_IVA_NAME_KEYS:
        return True
    for aliases in _SPECIAL_IVA_NAME_KEYS.values():
        if key in aliases:
            return True
    return key.startswith("IVA ")


def _iva_pct_to_float(iva_pct: str) -> Optional[float]:
    s = _normalize(iva_pct)
    if not s or s in _CANONICAL_SPECIAL_IVA_LABELS:
        return None
    digits = "".join(ch for ch in s if ch.isdigit() or ch in ".,")
    digits = digits.replace(",", ".").strip()
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def _format_iva_pct_from_amount(amount: float) -> str:
    rounded = round(amount, 4)
    if abs(rounded - round(rounded)) < 1e-9:
        return str(int(round(rounded)))
    text = f"{rounded:g}"
    return text.replace(".", ",")


def _rate_matches_iva_tax_name(name: str, rate: float) -> bool:
    key = _ascii_upper(_normalize(name))
    if not key.startswith("IVA "):
        return False
    compact = re.sub(r"[^0-9.,]", "", key).replace(",", ".")
    if not compact:
        return False
    try:
        name_rate = float(compact)
    except ValueError:
        return False
    return abs(name_rate - rate) < 1e-6


def _padron_tax_source_profile() -> str:
    """Perfil Odoo del que vienen los tax id del padrón Postgres (default: Dinner)."""
    from facturia_matching.infra.env import env_strip

    p = env_strip("PADRON_TAX_SOURCE_PROFILE", "default").lower()
    if p in ("aliare", "default", "sudata"):
        return p
    return "default"


def _canonical_iva_label_from_tax(tax: Dict[str, Any]) -> Optional[str]:
    """Etiqueta iva_pct canónica (21, 10,5, IVA Exento, …) desde un account.tax Odoo."""
    amount = tax.get("amount")
    try:
        amount_f = float(amount) if amount is not None else 0.0
    except (TypeError, ValueError):
        amount_f = 0.0
    if amount_f > 0:
        return _format_iva_pct_from_amount(amount_f)

    key = _ascii_upper(_normalize(tax.get("name") or ""))
    if not key:
        return None
    for canon_key, human in _SPECIAL_IVA_LABELS.items():
        aliases = _SPECIAL_IVA_NAME_KEYS.get(canon_key, (canon_key,))
        if key == canon_key or key in aliases or any(alias in key for alias in aliases):
            return human
    return None


def _parse_odoo_purchase_iva_rows(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for r in raw or []:
        if not r.get("id"):
            continue
        name = _normalize(r.get("name"))
        if not _is_purchase_iva_tax_name(name):
            continue
        amount = r.get("amount")
        try:
            amount_f = float(amount) if amount is not None else 0.0
        except (TypeError, ValueError):
            amount_f = 0.0
        rows.append({"id": int(r["id"]), "name": name, "amount": amount_f})
    return rows


def _fetch_purchase_iva_taxes_for_profile(profile: str) -> List[Dict[str, Any]]:
    """IVA de compra de un perfil Odoo (sin depender del contexto del request)."""
    try:
        from facturia_matching.odoo.api import (
            get_odoo_uid_from_config,
            is_odoo_config_ready,
            odoo_search_read,
        )
        from facturia_matching.odoo.env import build_odoo_main_config

        cfg = build_odoo_main_config(profile)
        if not is_odoo_config_ready(cfg) or not get_odoo_uid_from_config(cfg):
            return []
        raw = odoo_search_read(
            "account.tax",
            [("type_tax_use", "=", "purchase")],
            ["id", "name", "amount"],
            limit=500,
            config=cfg,
        )
        return _parse_odoo_purchase_iva_rows(raw)
    except Exception:
        return []


def _build_iva_semantics_from_taxes(taxes: List[Dict[str, Any]]) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for tax in taxes:
        label = _canonical_iva_label_from_tax(tax)
        if label and tax.get("id") is not None:
            out[int(tax["id"])] = label
    return out


def _padron_source_iva_semantics_by_id() -> Dict[int, str]:
    """
    tax_id del padrón Postgres → etiqueta iva_pct semántica.
    Se construye desde Odoo del perfil fuente (PADRON_TAX_SOURCE_PROFILE).
    """
    global _PADRON_SOURCE_IVA_SEMANTICS_CACHE
    if _PADRON_SOURCE_IVA_SEMANTICS_CACHE is not None:
        return _PADRON_SOURCE_IVA_SEMANTICS_CACHE

    taxes = _fetch_purchase_iva_taxes_for_profile(_padron_tax_source_profile())
    out = _build_iva_semantics_from_taxes(taxes)
    if not out:
        out = dict(IVA_TAX_ID_TO_PCT)
    _PADRON_SOURCE_IVA_SEMANTICS_CACHE = out
    return out


def _padron_source_tax_name_by_id() -> Dict[int, str]:
    """Nombres account.tax del perfil fuente del padrón (IVA + percepciones, etc.)."""
    global _PADRON_SOURCE_TAX_NAMES_CACHE
    if _PADRON_SOURCE_TAX_NAMES_CACHE is not None:
        return _PADRON_SOURCE_TAX_NAMES_CACHE

    out: Dict[int, str] = {}
    try:
        from facturia_matching.odoo.api import (
            get_odoo_uid_from_config,
            is_odoo_config_ready,
            odoo_search_read,
        )
        from facturia_matching.odoo.env import build_odoo_main_config

        cfg = build_odoo_main_config(_padron_tax_source_profile())
        if is_odoo_config_ready(cfg) and get_odoo_uid_from_config(cfg):
            rows = odoo_search_read(
                "account.tax",
                [("type_tax_use", "=", "purchase")],
                ["id", "name"],
                limit=500,
                config=cfg,
            )
            for r in rows or []:
                if r.get("id"):
                    out[int(r["id"])] = _normalize(r.get("name"))
    except Exception:
        pass

    _PADRON_SOURCE_TAX_NAMES_CACHE = out
    return out


def get_purchase_iva_taxes() -> List[Dict[str, Any]]:
    """Impuestos IVA de compra del tenant Odoo activo (id, name, amount)."""
    global _PURCHASE_IVA_TAXES_CACHE
    if _PURCHASE_IVA_TAXES_CACHE is not None:
        return _PURCHASE_IVA_TAXES_CACHE
    rows: List[Dict[str, Any]] = []
    try:
        from facturia_matching.odoo.api import get_odoo_uid, is_odoo_configured, odoo_search_read

        if is_odoo_configured() and get_odoo_uid():
            raw = odoo_search_read(
                "account.tax",
                [("type_tax_use", "=", "purchase")],
                ["id", "name", "amount"],
                limit=500,
            )
            rows = _parse_odoo_purchase_iva_rows(raw)
    except Exception:
        rows = []
    _PURCHASE_IVA_TAXES_CACHE = rows
    return rows


def get_iva_tax_ids() -> frozenset:
    """IDs IVA del tenant Odoo activo; fallback a ids históricos Dinner."""
    global _IVA_TAX_IDS_CACHE
    if _IVA_TAX_IDS_CACHE is not None:
        return _IVA_TAX_IDS_CACHE
    taxes = get_purchase_iva_taxes()
    if taxes:
        _IVA_TAX_IDS_CACHE = frozenset(t["id"] for t in taxes)
    else:
        _IVA_TAX_IDS_CACHE = IVA_TAX_IDS
    return _IVA_TAX_IDS_CACHE


def is_iva_tax_id(tax_id: int) -> bool:
    return int(tax_id) in get_iva_tax_ids()


def _legacy_dinner_tax_id_for_rate(rate: float) -> Optional[int]:
    for known_rate, tid in _LEGACY_DINNER_IVA_BY_RATE.items():
        if abs(known_rate - rate) < 1e-6:
            return tid
    return None


def _legacy_dinner_tax_id_for_special(label: str) -> Optional[int]:
    return _LEGACY_DINNER_SPECIAL_IVA.get(_normalize(label))


def _resolve_special_iva_tax_id(label: str) -> Optional[int]:
    key = _ascii_upper(_normalize(label))
    if not key:
        return None
    taxes = get_purchase_iva_taxes()
    if taxes:
        aliases = _SPECIAL_IVA_NAME_KEYS.get(key, (key,))
        for tax in taxes:
            tax_key = _ascii_upper(tax.get("name") or "")
            if tax_key in aliases or any(alias in tax_key for alias in aliases):
                return int(tax["id"])
    return _legacy_dinner_tax_id_for_special(label)


def iva_pct_requires_line_tax(iva_pct: Any) -> bool:
    """True si la fila debe llevar account.tax IVA en Odoo (incl. Exento / No Gravado)."""
    from facturia_matching.core.comprobante_tax import iva_pct_to_rate

    label = _normalize(iva_pct)
    if label in _ATTACHABLE_ZERO_IVA_LABELS:
        return True
    return iva_pct_to_rate(label) > 0


def resolve_iva_tax_id_for_pct(iva_pct: str) -> Optional[int]:
    """
    Resuelve iva_pct (21, 10,5, IVA Exento, …) al account.tax id del tenant Odoo activo.
    """
    label = _normalize(iva_pct)
    if not label:
        return None
    if label in _CANONICAL_SPECIAL_IVA_LABELS:
        return _resolve_special_iva_tax_id(label)

    rate = _iva_pct_to_float(label)
    if rate is None:
        return _resolve_special_iva_tax_id(label)

    taxes = get_purchase_iva_taxes()
    if taxes:
        for tax in taxes:
            amount = tax.get("amount")
            if amount is not None and float(amount) > 0 and abs(float(amount) - rate) < 1e-6:
                return int(tax["id"])
        for tax in taxes:
            if _rate_matches_iva_tax_name(tax.get("name") or "", rate):
                return int(tax["id"])

    return _legacy_dinner_tax_id_for_rate(rate)


def _remap_legacy_padron_iva_tax_id(tax_id: int) -> Optional[int]:
    """Remapea ids IVA del padrón Postgres al tenant Odoo activo vía semántica (alícuota/nombre)."""
    from facturia_matching.odoo.env import current_odoo_profile

    semantics = _padron_source_iva_semantics_by_id().get(int(tax_id))
    if semantics:
        remapped = resolve_iva_tax_id_for_pct(semantics)
        if remapped is not None:
            return remapped
    if current_odoo_profile() != "default":
        return None
    if is_iva_tax_id(tax_id):
        return int(tax_id)
    return None


def get_tax_name_by_id() -> Dict[int, str]:
    global _TAX_NAME_BY_ID
    if _TAX_NAME_BY_ID is not None:
        return _TAX_NAME_BY_ID
    iva_taxes = get_purchase_iva_taxes()
    if iva_taxes:
        _TAX_NAME_BY_ID = {int(t["id"]): t["name"] for t in iva_taxes}
        try:
            from facturia_matching.odoo.api import get_odoo_uid, is_odoo_configured, odoo_search_read

            if is_odoo_configured() and get_odoo_uid():
                rows = odoo_search_read(
                    "account.tax",
                    [("type_tax_use", "=", "purchase")],
                    ["id", "name"],
                    limit=500,
                )
                for r in rows or []:
                    if r.get("id"):
                        _TAX_NAME_BY_ID[int(r["id"])] = _normalize(r.get("name"))
        except Exception:
            pass
        return _TAX_NAME_BY_ID or {}
    try:
        from facturia_matching.odoo.api import get_odoo_uid, is_odoo_configured, odoo_search_read

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
    iva_set = get_iva_tax_ids()
    iva = [i for i in tax_ids if i in iva_set]
    other = [i for i in tax_ids if i not in iva_set]
    return iva, other


def primary_iva_tax_id(iva_ids: List[int]) -> Optional[int]:
    """Primer impuesto IVA del padrón (para invoice_line_ids/tax_id/.id)."""
    if not iva_ids:
        return None
    preferred_21 = resolve_iva_tax_id_for_pct("21")
    if preferred_21 is not None and preferred_21 in iva_ids:
        return preferred_21
    remapped = [_remap_legacy_padron_iva_tax_id(tid) for tid in iva_ids]
    remapped_valid = [t for t in remapped if t is not None]
    if remapped_valid:
        return remapped_valid[0]
    return iva_ids[0]


def iva_pct_from_tax_id(tax_id: int) -> str:
    for tax in get_purchase_iva_taxes():
        if int(tax["id"]) != int(tax_id):
            continue
        amount = tax.get("amount")
        if amount is not None and float(amount) > 0:
            return _format_iva_pct_from_amount(float(amount))
        name_key = _ascii_upper(tax.get("name") or "")
        for label, aliases in _SPECIAL_IVA_NAME_KEYS.items():
            if name_key in aliases or name_key == label:
                return _SPECIAL_IVA_LABELS.get(label, "")
    return _padron_source_iva_semantics_by_id().get(int(tax_id), "")


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

    if other_ids:
        row["_padron_other_tax_ids"] = [str(i) for i in other_ids]


def tax_id_for_csv_export(row: Dict[str, Any]) -> str:
    """
    ID para invoice_line_ids/tax_id/.id: iva_pct (FacturIA) > padrón remapeado > vacío.
    """
    if not isinstance(row, dict):
        return ""

    iva_pct = _normalize(row.get("iva_pct"))
    if iva_pct:
        resolved = resolve_iva_tax_id_for_pct(iva_pct)
        if resolved is not None:
            return str(resolved)

    primary = _normalize(row.get("_padron_tax_id_primary"))
    if primary and primary.isdigit():
        remapped = _remap_legacy_padron_iva_tax_id(int(primary))
        if remapped is not None:
            return str(remapped)
        return primary

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

    # 1) IDs no-IVA del padrón → nombre en perfil fuente → id en tenant activo
    iva_set = get_iva_tax_ids()
    active_names = get_tax_name_by_id()
    source_names = _padron_source_tax_name_by_id()
    for tid in _parse_row_padron_tax_ids(row):
        if tid in iva_set:
            continue
        if tid in active_names:
            _add(tid)
            continue
        label = source_names.get(tid) or active_names.get(tid) or ""
        remapped = resolve_tax_label_to_id(label) if label else None
        if remapped is not None:
            _add(remapped)

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

    additional = build_csv_additional_taxes(row)
    for t in additional:
        if t.isdigit() and t not in seen:
            seen.add(t)
            ids.append(t)

    return ",".join(ids)
