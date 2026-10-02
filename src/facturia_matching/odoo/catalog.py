"""
Catálogos Odoo para dropdowns de la UI (con caché en memoria).
"""

import contextvars
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz, process as rf_process

from facturia_matching.infra.config import ODOO_CATALOG_CACHE_TTL
from facturia_matching.odoo.api import (
    get_odoo_document_types,
    get_odoo_uid_from_config,
    is_odoo_config_ready,
    odoo_available_fields,
    odoo_search_read,
    probe_odoo_db_exists,
)
from facturia_matching.odoo.document_types_i18n import prepare_document_types_for_ui
from facturia_matching.odoo.env import current_odoo_profile, get_odoo_main_config, supports_rubro_field

logger = logging.getLogger(__name__)

DOC_TYPE_LABELS = ("FACTURAS A", "FACTURAS B", "FACTURAS C", "OC-X")

_cache_by_profile: Dict[str, Dict[str, Any]] = {}
# Single-flight: bootstrap ∥ proceso no deben cold-fetch el mismo perfil a la vez.
_fetch_locks_guard = threading.Lock()
_fetch_locks_by_profile: Dict[str, threading.Lock] = {}
# Stale-while-revalidate: un refresh en background por perfil a la vez.
_bg_refresh_guard = threading.Lock()
_bg_refresh_inflight: Dict[str, bool] = {}


def _catalog_fetch_lock(profile: str) -> threading.Lock:
    with _fetch_locks_guard:
        lock = _fetch_locks_by_profile.get(profile)
        if lock is None:
            lock = threading.Lock()
            _fetch_locks_by_profile[profile] = lock
        return lock


def _schedule_catalog_background_refresh(profile: str, config: Dict[str, Any]) -> None:
    """Tras TTL: devolver cache stale y refrescar sin bloquear el request."""
    with _bg_refresh_guard:
        if _bg_refresh_inflight.get(profile):
            return
        _bg_refresh_inflight[profile] = True

    ctx = contextvars.copy_context()

    def _worker() -> None:
        try:
            with _catalog_fetch_lock(profile):
                try:
                    raw = _fetch_catalog_raw(config, profile)
                except Exception as e:
                    logger.warning(
                        "Refresh background catálogo Odoo (%s) falló: %s", profile, e
                    )
                    return
                catalog = _build_catalog_from_raw(raw)
                cache = _cache_by_profile.setdefault(profile, {"ts": 0.0, "data": None})
                cache["ts"] = time.time()
                cache["data"] = catalog
                logger.info("Catálogo Odoo refresheado en background (profile=%s)", profile)
        finally:
            with _bg_refresh_guard:
                _bg_refresh_inflight[profile] = False

    threading.Thread(
        target=lambda: ctx.run(_worker),
        name=f"odoo-catalog-refresh-{profile}",
        daemon=True,
    ).start()


def _normalize_label(s: Any) -> str:
    return " ".join(str(s or "").strip().split()).upper()


def build_name_to_id_map(items: List[Dict[str, Any]], name_key: str = "name") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for it in items:
        iid = it.get("id")
        name = it.get(name_key) or it.get("name")
        if iid is None or not name:
            continue
        key = _normalize_label(name)
        if key and key not in out:
            out[key] = _catalog_id_value(iid)
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


def _catalog_id_value(raw: Any) -> Any:
    """Id de catálogo: entero Odoo o string (p. ej. rubro del padrón sin modelo x_rubros)."""
    if isinstance(raw, int):
        return raw
    s = str(raw or "").strip()
    if s.isdigit():
        return int(s)
    return s


def _padron_rubro_options() -> List[Dict[str, Any]]:
    """Rubros del padrón Postgres cuando el tenant no tiene modelo x_rubros (p. ej. Aliare sin addon)."""
    try:
        from facturia_matching.padron.postgres import get_padron_cached

        padron = get_padron_cached() or []
        names = sorted(
            {_normalize_label(r.get("rubro")) for r in padron if _normalize_label(r.get("rubro"))}
        )
        return [{"id": name, "name": name} for name in names]
    except Exception:
        return []


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
            "CREDIT NOTE",
            "DEBIT NOTE",
            "DEBIT MEMO",
            "TIQUE",
            "TICKET",
            "MIPYME",
            "SMB",
            "FCE",
            "CREDITO ELECTRONICA",
            "CRÉDITO ELECTRÓNICA",
            "ELECTRONIC CREDIT",
            "ELECTRONIC DEBIT",
        )
    ):
        return 0

    en_label = f"INVOICES {letter}"
    en_singular = f"INVOICE {letter}"
    if name_u == label or name_u == en_label:
        return 100
    if name_u == factura_singular or name_u == en_singular:
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
        id_by_name[nm] = _catalog_id_value(p["id"])

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
        id_by_name[nm] = _catalog_id_value(it["id"])

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


def _partner_catalog_domain(profile: str) -> List[Any]:
    """Aliare: todos los contactos; otros perfiles: solo proveedores (supplier_rank > 0)."""
    if profile == "aliare":
        return []
    return [("supplier_rank", ">", 0)]


_PARTNER_FETCH_PAGE = 5000
_PARTNER_FETCH_MAX = 100_000


def _search_partners_paginated(
    config: Dict[str, Any],
    domain: List[Any],
    *,
    page_size: int = _PARTNER_FETCH_PAGE,
    max_rows: int = _PARTNER_FETCH_MAX,
) -> List[Dict[str, Any]]:
    """
    Trae res.partner en páginas por id (no offset).

    Varios Odoo/proxies topean ~20k con offset; Central Ticket tenía exactamente
    20k contactos en el combobox y proveedores nuevos no aparecían.
    """
    out: List[Dict[str, Any]] = []
    last_id = 0
    while len(out) < max_rows:
        page_domain = list(domain or []) + [("id", ">", last_id)]
        batch = odoo_search_read(
            "res.partner",
            page_domain,
            ["id", "name", "vat"],
            limit=page_size,
            order="id",
            config=config,
        )
        if not batch:
            break
        out.extend(batch)
        last_id = max(int(r["id"]) for r in batch if r.get("id") is not None)
        if len(batch) < page_size:
            break
    if len(out) >= max_rows:
        logger.warning(
            "Catálogo partners truncado en %s filas (domain=%s)", max_rows, domain
        )
    else:
        logger.info("Catálogo partners: %s filas (domain=%s)", len(out), domain)
    return out


def _merge_partners_by_id(*groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id: Dict[Any, Dict[str, Any]] = {}
    for group in groups:
        for row in group or []:
            pid = row.get("id")
            if pid is None:
                continue
            by_id[pid] = row
    return list(by_id.values())


def _fetch_partners_for_catalog(config: Dict[str, Any], profile: str) -> List[Dict[str, Any]]:
    domain = _partner_catalog_domain(profile)
    partners = _search_partners_paginated(config, domain)
    if not partners and domain:
        partners = _search_partners_paginated(config, [])
    # Aliare: domain vacío = todos los contactos. El pass extra de suppliers solo
    # aporta si el listado general se truncó (tope) o hay reglas de acceso raras.
    if profile == "aliare" and len(partners) >= _PARTNER_FETCH_MAX:
        suppliers = _search_partners_paginated(config, [("supplier_rank", ">", 0)])
        partners = _merge_partners_by_id(partners, suppliers)
    return partners or []


def search_partners_by_query(
    query: str,
    *,
    limit: int = 50,
    profile: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Búsqueda live en Odoo (name/VAT) para el combobox Proveedor.

    Complementa el catálogo precargado cuando el tenant tiene muchos contactos
    o el partner no entró en el listado inicial.
    """
    q = " ".join(str(query or "").strip().split())
    if len(q) < 2:
        return []

    profile = profile or current_odoo_profile()
    config = get_odoo_main_config(profile)
    if not is_odoo_config_ready(config) or get_odoo_uid_from_config(config) is None:
        return []

    tokens = [t for t in q.split() if t]
    digits = "".join(ch for ch in q if ch.isdigit())

    clauses: List[Any] = []
    if tokens:
        if len(tokens) == 1:
            name_dom: Any = [("name", "ilike", tokens[0])]
        else:
            # ['&', '&', ('name','ilike',a), ('name','ilike',b), ('name','ilike',c)]
            name_dom = ["&"] * (len(tokens) - 1) + [("name", "ilike", t) for t in tokens]
        clauses.append(name_dom)
    if len(digits) >= 3:
        clauses.append([("vat", "ilike", digits)])

    if not clauses:
        return []
    if len(clauses) == 1:
        domain = clauses[0]
    else:
        # OR between name-block and vat-block
        domain = ["|"] + clauses[0] + clauses[1]

    rows = odoo_search_read(
        "res.partner",
        domain,
        ["id", "name", "vat"],
        limit=max(1, min(int(limit), 100)),
        order="name",
        config=config,
    )
    out: List[Dict[str, Any]] = []
    seen = set()
    for r in rows or []:
        pid = r.get("id")
        name = (r.get("name") or "").strip()
        if pid is None or not name:
            continue
        key = int(pid)
        if key in seen:
            continue
        seen.add(key)
        item: Dict[str, Any] = {"id": key, "name": name}
        if r.get("vat"):
            item["vat"] = str(r.get("vat")).strip()
        out.append(item)
    return out


def _fetch_rubros_for_catalog(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    rubros: List[Dict[str, Any]] = []
    if not supports_rubro_field():
        return rubros
    for model, domain, flds in (
        ("x_rubros", [("x_active", "=", True)], ["id", "x_name"]),
        ("x_rubros", [], ["id", "x_name"]),
        ("x.rubros", [], ["id", "x_name"]),
    ):
        try:
            rows = odoo_search_read(model, domain, flds, limit=500, order="x_name", config=config)
            if rows:
                return [
                    {"id": r["id"], "name": r.get("x_name") or r.get("name")}
                    for r in rows
                    if r.get("id")
                ]
        except Exception:
            continue
    try:
        rows = odoo_search_read("x_rubros", [], ["id", "x_name"], limit=500, config=config)
        rubros = [{"id": r["id"], "name": r.get("x_name")} for r in rows if r.get("id")]
    except Exception:
        pass
    if not rubros:
        rubros = _padron_rubro_options()
        if rubros:
            logger.info(
                "Rubros: usando padrón Postgres (%d); instalá facturia_x_rubros en Odoo para IDs reales.",
                len(rubros),
            )
    return rubros


def _fetch_catalog_raw(config: Dict[str, Any], profile: str) -> Dict[str, List[Dict[str, Any]]]:
    # Paralelizar RPCs independientes. Un ContextVar Context no se puede
    # ctx.run() en paralelo desde varios threads (RuntimeError: already entered);
    # copiar el contexto *por* submit.
    def _submit(pool: ThreadPoolExecutor, fn, *args):
        return pool.submit(contextvars.copy_context().run, fn, *args)

    def _journals() -> List[Dict[str, Any]]:
        return odoo_search_read(
            "account.journal",
            [("active", "=", True)],
            ["id", "name"],
            limit=500,
            order="name",
            config=config,
        )

    def _accounts() -> List[Dict[str, Any]]:
        return odoo_search_read(
            "account.account",
            [],
            ["id", "name", "code"],
            limit=5000,
            order="name",
            config=config,
        )

    def _products() -> List[Dict[str, Any]]:
        return odoo_search_read(
            "product.product",
            [("active", "=", True)],
            odoo_available_fields(
                "product.product",
                ["id", "name", "default_code", "uom_id", "uom_po_id"],
                config,
            ),
            limit=20000,
            order="name",
            config=config,
        )

    def _doc_types() -> List[Dict[str, Any]]:
        return prepare_document_types_for_ui(get_odoo_document_types(config))

    with ThreadPoolExecutor(max_workers=6) as pool:
        fut_journals = _submit(pool, _journals)
        fut_partners = _submit(pool, _fetch_partners_for_catalog, config, profile)
        fut_accounts = _submit(pool, _accounts)
        fut_products = _submit(pool, _products)
        fut_docs = _submit(pool, _doc_types)
        # Rubros: retries de modelo; en paralelo con el resto pero un solo worker.
        fut_rubros = _submit(pool, _fetch_rubros_for_catalog, config)

        journals = fut_journals.result()
        partners = fut_partners.result()
        accounts = fut_accounts.result()
        products = fut_products.result()
        doc_types = fut_docs.result()
        rubros = fut_rubros.result()

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
            norm_id = _catalog_id_value(iid)
            key = (str(norm_id), name)
            if key in seen:
                continue
            seen.add(key)
            row: Dict[str, Any] = {"id": norm_id, "name": name}
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
            uom = r.get("uom_id") or []
            uom_po = r.get("uom_po_id") or []
            if isinstance(uom, (list, tuple)) and uom:
                row["uom_id"] = int(uom[0])
            if isinstance(uom_po, (list, tuple)) and uom_po:
                row["uom_po_id"] = int(uom_po[0])
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


def _build_catalog_from_raw(raw: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    proveedores_cuit_map: Dict[str, str] = {}
    for p in raw.get("proveedores") or []:
        pid = str(p["id"])
        vat = (p.get("vat") or "").strip()
        if vat:
            proveedores_cuit_map[pid] = vat

    doc_types = raw.get("document_types") or []
    doc_type_label_map = build_doc_type_label_map(doc_types)
    partner_cuit_to_id = build_partner_cuit_to_id(raw.get("proveedores") or [])

    return {
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


def get_catalog(force: bool = False, profile: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], bool]:
    """
    Retorna (catalog, from_odoo).
    catalog incluye listas + mapas name->id + proveedores_cuit_map por partner id.

    Sin force: usa cache en memoria (TTL). Si el cache existe pero expiró,
    lo devuelve de inmediato y refresca en background (stale-while-revalidate).
    """
    profile = profile or current_odoo_profile()
    config = get_odoo_main_config(profile)
    if not is_odoo_config_ready(config):
        return None, False

    if get_odoo_uid_from_config(config) is None:
        logger.warning(
            "Odoo configurado pero no hay uid (ODOO_USER_ID numérico o ODOO_USER + ODOO_PASSWORD)"
        )
        return None, False

    db_exists, _, _ = probe_odoo_db_exists(config)
    if db_exists is False:
        logger.warning(
            "Odoo db %r no existe en %s; catálogo desde Postgres",
            config.get("db"),
            config.get("base_url"),
        )
        return None, False

    cache = _cache_by_profile.setdefault(profile, {"ts": 0.0, "data": None})
    now = time.time()
    cached = cache.get("data")
    age = now - float(cache.get("ts") or 0)
    if not force and cached is not None:
        if age < ODOO_CATALOG_CACHE_TTL:
            return cached, True
        # Stale: servir ya y refrescar sin bloquear bootstrap / proceso.
        _schedule_catalog_background_refresh(profile, config)
        return cached, True

    # Single-flight por perfil: el segundo caller espera y reusa el cache.
    with _catalog_fetch_lock(profile):
        now = time.time()
        cached = cache.get("data")
        age = now - float(cache.get("ts") or 0)
        if not force and cached is not None:
            # Fresco o stale recién poblado por otro thread: no bloquear de nuevo.
            if age >= ODOO_CATALOG_CACHE_TTL:
                _schedule_catalog_background_refresh(profile, config)
            return cached, True

        try:
            raw = _fetch_catalog_raw(config, profile)
        except Exception as e:
            logger.warning("No se pudo cargar catálogo Odoo: %s", e)
            # Si el force falló pero hay cache previo, no dejar el matching sin Odoo.
            if cached is not None:
                logger.warning(
                    "Usando catálogo Odoo en cache tras error de fetch (profile=%s)",
                    profile,
                )
                return cached, True
            return None, False

        catalog = _build_catalog_from_raw(raw)
        cache["ts"] = time.time()
        cache["data"] = catalog
        return catalog, True


def invalidate_catalog_cache() -> None:
    for entry in _cache_by_profile.values():
        entry["ts"] = 0.0
        entry["data"] = None
    with _bg_refresh_guard:
        _bg_refresh_inflight.clear()
