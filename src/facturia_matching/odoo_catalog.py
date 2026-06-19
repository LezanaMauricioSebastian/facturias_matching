"""
Catálogos Odoo para dropdowns de la UI (con caché en memoria).
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz, process as rf_process

from facturia_matching.config import ODOO_CATALOG_CACHE_TTL
from facturia_matching.odoo_api import get_odoo_document_types, get_odoo_uid, is_odoo_configured, odoo_search_read

logger = logging.getLogger(__name__)

DOC_TYPE_LABELS = ("FACTURAS A", "FACTURAS B", "FACTURAS C", "OC-X")

_cache: Dict[str, Any] = {"ts": 0.0, "data": None}


def _normalize_label(s: Any) -> str:
    return " ".join(str(s or "").strip().split()).upper()


def build_name_to_id_map(items: List[Dict[str, Any]], name_key: str = "name") -> Dict[str, int]:
    out: Dict[str, int] = {}
    for it in items:
        iid = it.get("id")
        name = it.get(name_key) or it.get("name")
        if iid is None or not name:
            continue
        key = _normalize_label(name)
        if key and key not in out:
            out[key] = int(iid)
    return out


def resolve_id_by_name(
    name: str,
    name_map: Dict[str, int],
    *,
    fallback_name: Optional[str] = None,
) -> str:
    """Devuelve id como string para CSV/UI, o vacío."""
    key = _normalize_label(name)
    if key and key in name_map:
        return str(name_map[key])
    if fallback_name:
        fb = _normalize_label(fallback_name)
        if fb in name_map:
            return str(name_map[fb])
    return ""


def _digits_only(s: str) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _score_doc_type_candidate(name_u: str, code_u: str, letter: str) -> int:
    """
    Prioriza FACTURAS A/B/C clásicas (no FCE MiPyMEs, notas de crédito, tiques).
    Códigos AFIP habituales en Odoo: A=1, B=6, C=11.
    """
    label = f"FACTURAS {letter}"
    factura_singular = f"FACTURA {letter}"
    afip_code = {"A": "1", "B": "6", "C": "11"}.get(letter, "")

    if not name_u and not code_u:
        return 0

    # Excluir tipos que no son factura de compra estándar
    if any(
        tok in name_u
        for tok in (
            "NOTA DE CREDITO",
            "NOTA DE DEBITO",
            "NOTA DE CRÉDITO",
            "NOTA DE DÉBITO",
            "TIQUE",
            "MIPYME",
            "FCE",
            "CREDITO ELECTRONICA",
            "CRÉDITO ELECTRÓNICA",
        )
    ):
        return 0

    if name_u == label:
        return 100
    if name_u == factura_singular:
        return 95
    if afip_code and code_u == afip_code:
        return 90
    if label in name_u:
        return 80
    if factura_singular in name_u:
        return 75
    if name_u.endswith(f" {letter}") and "FACTURA" in name_u:
        return 40
    return 0


def build_doc_type_label_map(doc_types: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Mapea FACTURAS A/B/C y OC-X al id Odoo correcto.
    Evita tomar 'FACTURA DE CREDITO ELECTRONICA MiPyMEs (FCE) A' cuando existe 'FACTURAS A'.
    """
    out: Dict[str, int] = {}
    oc_x_id: Optional[int] = None
    best_score: Dict[str, int] = {}

    for d in doc_types or []:
        iid = d.get("id")
        if iid is None:
            continue
        iid = int(iid)
        name_u = _normalize_label(d.get("name"))
        code_u = _normalize_label(d.get("code"))
        if code_u in ("OC-X", "99") or name_u == "OC-X":
            oc_x_id = iid

        for letter in ("A", "B", "C"):
            label = f"FACTURAS {letter}"
            sc = _score_doc_type_candidate(name_u, code_u, letter)
            if sc > best_score.get(label, 0):
                best_score[label] = sc
                out[label] = iid

    for letter in ("A", "B", "C"):
        label = f"FACTURAS {letter}"
        if best_score.get(label, 0) <= 0 and label in out:
            del out[label]

    if oc_x_id is not None:
        out["OC-X"] = oc_x_id
    elif "FACTURAS C" in out:
        out.setdefault("OC-X", out["FACTURAS C"])

    return out


def build_partner_cuit_to_id(proveedores: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for p in proveedores or []:
        pid = p.get("id")
        vat = _digits_only(p.get("vat"))
        if pid is not None and vat and vat not in out:
            out[vat] = int(pid)
    return out


def resolve_partner_id(
    nombre: str,
    cuit: str,
    proveedores: List[Dict[str, Any]],
    partner_cuit_to_id: Dict[str, int],
    *,
    min_score: float = 72.0,
) -> Tuple[str, float]:
    """Resuelve partner_id en Odoo por CUIT y/o fuzzy sobre nombre."""
    cuit_n = _digits_only(cuit)
    if cuit_n and cuit_n in partner_cuit_to_id:
        return str(partner_cuit_to_id[cuit_n]), 100.0

    nombre_n = _normalize_label(nombre)
    if not nombre_n or not proveedores:
        return "", 0.0

    choices: List[str] = []
    id_by_name: Dict[str, int] = {}
    for p in proveedores:
        nm = _normalize_label(p.get("name"))
        if not nm:
            continue
        choices.append(nm)
        id_by_name[nm] = int(p["id"])

    best = rf_process.extractOne(nombre_n, choices, scorer=fuzz.WRatio)
    if not best:
        return "", 0.0
    best_name, score, _idx = best[0], float(best[1]), int(best[2])
    if score < min_score:
        return "", score
    return str(id_by_name.get(best_name, "")), score


def resolve_id_fuzzy(
    name: str,
    items: List[Dict[str, Any]],
    *,
    fallback_name: Optional[str] = None,
    min_score: float = 80.0,
) -> str:
    """Fuzzy name → id cuando el match exacto del padrón no coincide con Odoo."""
    for candidate in (name, fallback_name):
        if not candidate:
            continue
        exact = resolve_id_by_name(candidate, build_name_to_id_map(items))
        if exact:
            return exact

    nombre_n = _normalize_label(name or fallback_name or "")
    if not nombre_n or not items:
        return ""

    choices: List[str] = []
    id_by_name: Dict[str, int] = {}
    for it in items:
        nm = _normalize_label(it.get("name"))
        if not nm:
            continue
        choices.append(nm)
        id_by_name[nm] = int(it["id"])

    best = rf_process.extractOne(nombre_n, choices, scorer=fuzz.WRatio)
    if not best or float(best[1]) < min_score:
        return ""
    return str(id_by_name.get(best[0], ""))


_ACCOUNT_CODE_RE = re.compile(r"^([\d]+(?:\.[\d]+)*)\s*(.*)$")


def _split_cuenta_label(raw: str) -> Tuple[str, str]:
    """Padrón suele traer '5.1.1.01.030 Compra de mercadería' → (code, name)."""
    s = " ".join(str(raw or "").strip().split())
    if not s:
        return "", ""
    m = _ACCOUNT_CODE_RE.match(s)
    if m:
        code = (m.group(1) or "").strip()
        name = (m.group(2) or "").strip()
        return code, name
    return "", s


def build_account_maps(accounts: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """Índices por código, nombre y 'código nombre' (formato padrón)."""
    by_code: Dict[str, int] = {}
    by_name: Dict[str, int] = {}
    by_full: Dict[str, int] = {}
    for acc in accounts or []:
        iid = acc.get("id")
        if iid is None:
            continue
        iid = int(iid)
        name = " ".join(str(acc.get("name") or "").split())
        code = " ".join(str(acc.get("code") or "").split())
        if name:
            by_name[_normalize_label(name)] = iid
        if code:
            by_code[_normalize_label(code)] = iid
        if code and name:
            by_full[_normalize_label(f"{code} {name}")] = iid
    return {"by_code": by_code, "by_name": by_name, "by_full": by_full}


def resolve_account_id(
    cuenta_raw: str,
    accounts: List[Dict[str, Any]],
    account_maps: Optional[Dict[str, Dict[str, int]]] = None,
    *,
    min_score: float = 65.0,
) -> str:
    """
    Resuelve invoice_line_ids/account_id.
    Padrón: 'código + nombre'. Odoo: campos code y name por separado.
    """
    raw = " ".join(str(cuenta_raw or "").strip().split())
    if not raw or not accounts:
        return ""

    maps = account_maps or build_account_maps(accounts)
    by_code = maps.get("by_code") or {}
    by_name = maps.get("by_name") or {}
    by_full = maps.get("by_full") or {}

    key_full = _normalize_label(raw)
    if key_full in by_full:
        return str(by_full[key_full])

    code, name = _split_cuenta_label(raw)
    if code:
        ck = _normalize_label(code)
        code_id = by_code.get(ck)
        name_id = None
        if name:
            nk = _normalize_label(name)
            name_id = by_name.get(nk)
            if code_id and name_id and code_id != name_id:
                return str(name_id)
        if code_id:
            return str(code_id)
    if name:
        nk = _normalize_label(name)
        if nk in by_name:
            return str(by_name[nk])
        if code:
            combo = _normalize_label(f"{code} {name}")
            if combo in by_full:
                return str(by_full[combo])

    # Fuzzy solo sobre la parte nombre (sin código contable)
    fuzzy_target = name or raw
    choices: List[str] = []
    id_by_name: Dict[str, int] = {}
    display_choices: List[str] = []
    id_by_display: Dict[str, int] = {}
    for acc in accounts:
        iid = int(acc["id"])
        nm = _normalize_label(acc.get("name"))
        cd = " ".join(str(acc.get("code") or "").split())
        if nm:
            choices.append(nm)
            id_by_name[nm] = iid
        if cd and nm:
            disp = _normalize_label(f"{cd} {acc.get('name')}")
            display_choices.append(disp)
            id_by_display[disp] = iid

    target = _normalize_label(fuzzy_target)
    if target and choices:
        best = rf_process.extractOne(target, choices, scorer=fuzz.WRatio)
        if best and float(best[1]) >= min_score:
            return str(id_by_name.get(best[0], ""))

    if key_full and display_choices:
        best = rf_process.extractOne(key_full, display_choices, scorer=fuzz.WRatio)
        if best and float(best[1]) >= min_score:
            return str(id_by_display.get(best[0], ""))

    return resolve_id_fuzzy(raw, accounts, min_score=min_score)


def resolve_doc_type_id(label: str, doc_type_label_map: Dict[str, int]) -> str:
    key = _normalize_label(label)
    if key in doc_type_label_map:
        return str(doc_type_label_map[key])
    if "OC-X" in doc_type_label_map:
        return str(doc_type_label_map["OC-X"])
    return ""


def _fetch_catalog_raw() -> Dict[str, List[Dict[str, Any]]]:
    journals = odoo_search_read(
        "account.journal",
        [("active", "=", True)],
        ["id", "name"],
        limit=500,
        order="name",
    )
    partners = odoo_search_read(
        "res.partner",
        [("supplier_rank", ">", 0)],
        ["id", "name", "vat"],
        limit=20000,
        order="name",
    )
    if not partners:
        partners = odoo_search_read(
            "res.partner",
            [],
            ["id", "name", "vat"],
            limit=20000,
            order="name",
        )
    accounts = odoo_search_read(
        "account.account",
        [],
        ["id", "name", "code"],
        limit=5000,
        order="name",
    )
    rubros: List[Dict[str, Any]] = []
    for model, domain, flds in (
        ("x_rubros", [("x_active", "=", True)], ["id", "x_name"]),
        ("x_rubros", [], ["id", "x_name"]),
        ("x.rubros", [], ["id", "x_name"]),
    ):
        try:
            rows = odoo_search_read(model, domain, flds, limit=500, order="x_name")
            if rows:
                rubros = [{"id": r["id"], "name": r.get("x_name") or r.get("name")} for r in rows if r.get("id")]
                break
        except Exception:
            continue
    if not rubros:
        rows = odoo_search_read("x_rubros", [], ["id", "x_name"], limit=500)
        rubros = [{"id": r["id"], "name": r.get("x_name")} for r in rows if r.get("id")]

    doc_types = get_odoo_document_types()
    products = odoo_search_read(
        "product.product",
        [("active", "=", True)],
        ["id", "name", "default_code"],
        limit=20000,
        order="name",
    )

    def _clean(items: List[Dict], extra: Optional[str] = None) -> List[Dict[str, Any]]:
        out = []
        seen = set()
        for r in items:
            iid = r.get("id")
            if iid is None:
                continue
            name = (r.get("name") or r.get(extra or "") or "").strip()
            if not name:
                continue
            key = (int(iid), name)
            if key in seen:
                continue
            seen.add(key)
            row: Dict[str, Any] = {"id": int(iid), "name": name}
            if r.get("code"):
                row["code"] = str(r.get("code")).strip()
            if r.get("vat"):
                row["vat"] = str(r.get("vat")).strip()
            out.append(row)
        return sorted(out, key=lambda x: x["name"].upper())

    def _clean_products(items: List[Dict]) -> List[Dict[str, Any]]:
        out = []
        seen = set()
        for r in items:
            iid = r.get("id")
            if iid is None:
                continue
            name = (r.get("name") or "").strip()
            if not name:
                continue
            code = (r.get("default_code") or "").strip()
            key = (int(iid), name, code)
            if key in seen:
                continue
            seen.add(key)
            row: Dict[str, Any] = {"id": int(iid), "name": name}
            if code:
                row["code"] = code
            out.append(row)
        return sorted(out, key=lambda x: (x.get("code") or x["name"]).upper())

    return {
        "journals": _clean(journals),
        "document_types": _clean(doc_types),
        "proveedores": _clean(partners, "name"),
        "cuentas": _clean(accounts),
        "rubros": _clean(rubros),
        "productos": _clean_products(products),
    }


def get_catalog(force: bool = False) -> Tuple[Optional[Dict[str, Any]], bool]:
    """
    Retorna (catalog, from_odoo).
    catalog incluye listas + mapas name->id + proveedores_cuit_map por partner id.
    """
    if not is_odoo_configured():
        return None, False

    if get_odoo_uid() is None:
        logger.warning(
            "Odoo configurado pero no hay uid (ODOO_USER_ID numérico o ODOO_USER + ODOO_PASSWORD)"
        )
        return None, False

    now = time.time()
    if not force and _cache.get("data") and (now - float(_cache.get("ts") or 0)) < ODOO_CATALOG_CACHE_TTL:
        return _cache["data"], True

    try:
        raw = _fetch_catalog_raw()
    except Exception as e:
        logger.warning("No se pudo cargar catálogo Odoo: %s", e)
        return None, False

    proveedores_cuit_map: Dict[str, str] = {}
    for p in raw.get("proveedores") or []:
        pid = str(p["id"])
        vat = (p.get("vat") or "").strip()
        if vat:
            proveedores_cuit_map[pid] = vat

    doc_types = raw.get("document_types") or []
    doc_type_label_map = build_doc_type_label_map(doc_types)
    partner_cuit_to_id = build_partner_cuit_to_id(raw.get("proveedores") or [])

    catalog = {
        **raw,
        "maps": {
            "journals": build_name_to_id_map(raw.get("journals") or []),
            "document_types": build_name_to_id_map(doc_types),
            "document_type_labels": doc_type_label_map,
            "proveedores": build_name_to_id_map(raw.get("proveedores") or []),
            "cuentas": build_name_to_id_map(raw.get("cuentas") or []),
            "accounts": build_account_maps(raw.get("cuentas") or []),
            "rubros": build_name_to_id_map(raw.get("rubros") or []),
            "productos": build_name_to_id_map(raw.get("productos") or []),
        },
        "partner_cuit_to_id": partner_cuit_to_id,
        "proveedores_cuit_map": proveedores_cuit_map,
        "facturas_c_type_ids": [
            str(doc_type_label_map["FACTURAS C"])
            for _ in [0]
            if "FACTURAS C" in doc_type_label_map
        ],
    }
    _cache["ts"] = now
    _cache["data"] = catalog
    return catalog, True


def invalidate_catalog_cache() -> None:
    _cache["ts"] = 0.0
    _cache["data"] = None
