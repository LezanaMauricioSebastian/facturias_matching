"""Load structured Excel/Sheets padron from config (URL + optional uploads)."""

import time
from typing import Any, Dict, List, Optional

from facturia_matching.padron import padron_config_store as cfg_store
from facturia_matching.padron.sheet_loader import (
    extract_category_map,
    extract_category_map_from_rows,
    fetch_sheet,
    parse_file_path,
    rows_to_named,
    rows_to_productos,
    rows_to_proveedores,
)

_data_cache: Dict[str, Dict[str, Any]] = {}


def _rows_for_kind(cfg: Dict[str, Any], kind: str, sheet_rows: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    company_id = int(cfg.get("company_id") or 0)
    path = cfg_store.uploaded_path(company_id, kind)
    if path is not None:
        return parse_file_path(path)
    return sheet_rows or []


def load_padron(company_id: int = 0, force: bool = False) -> Dict[str, Any]:
    cfg = cfg_store.get_config(company_id)
    ttl = int(cfg.get("refresh_minutes") or 15) * 60
    cache_key = str(company_id)
    if not force and cache_key in _data_cache:
        entry = _data_cache[cache_key]
        if time.time() - float(entry.get("_ts") or 0) < ttl:
            return entry

    url = (cfg.get("sheet_url") or "").strip()
    sheet_rows: List[Dict[str, str]] = []
    cat_map: Dict[str, str] = {}
    if url:
        try:
            sheet_rows = fetch_sheet(url, ttl=ttl, force=force)
        except Exception:
            sheet_rows = []
        try:
            cat_map = extract_category_map(url)
        except Exception:
            cat_map = {}

    mapping = cfg.get("mapping") or {}
    m_prov = mapping.get("proveedores") or {}
    m_prod = mapping.get("productos") or {}
    m_fp = mapping.get("formas_pago") or {}
    m_conc = mapping.get("conceptos") or {}

    prov_rows = _rows_for_kind(cfg, "proveedores", sheet_rows)
    prod_rows = _rows_for_kind(cfg, "productos", sheet_rows)
    fp_rows = _rows_for_kind(cfg, "formas_pago", sheet_rows)
    conc_rows = _rows_for_kind(cfg, "conceptos", sheet_rows)

    proveedores = rows_to_proveedores(
        prov_rows,
        col_razon=m_prov.get("razon_social") or "",
        col_fantasia=m_prov.get("nombre_fantasia") or "",
        col_cuit=m_prov.get("cuit") or "",
    )
    productos = rows_to_productos(
        prod_rows,
        col_nombre=m_prod.get("nombre") or "",
        col_um=m_prod.get("unidad_medida") or "",
    )
    formas_pago = rows_to_named(fp_rows, m_fp.get("nombre") or "")
    conceptos = rows_to_named(conc_rows, m_conc.get("nombre") or "")

    mapped_cat = extract_category_map_from_rows(
        conc_rows,
        m_conc.get("nombre") or "",
        m_conc.get("categoria") or "",
    )
    if mapped_cat:
        cat_map = mapped_cat

    data = {
        "proveedores": proveedores,
        "productos": productos,
        "formas_pago": [r["nombre"] for r in formas_pago],
        "conceptos": [r["nombre"] for r in conceptos],
        "categoria_map": cat_map,
        "config": cfg,
        "_ts": time.time(),
    }
    _data_cache[cache_key] = data
    return data


def invalidate_data_cache(company_id: Optional[int] = None) -> None:
    if company_id is None:
        _data_cache.clear()
    else:
        _data_cache.pop(str(company_id), None)
