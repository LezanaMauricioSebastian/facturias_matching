"""Load structured Excel/Sheets padron from config (URL / private SA + optional uploads)."""

import time
from typing import Any, Dict, List, Optional

from facturia_matching.padron import padron_config_store as cfg_store
from facturia_matching.padron.google_sheets import (
    friendly_sheet_access_error,
    resolve_sheet_source,
)
from facturia_matching.padron.sheet_loader import (
    extract_category_map,
    extract_category_map_from_rows,
    extract_column_values,
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


def load_padron(company_id: int = 0, force: bool = True) -> Dict[str, Any]:
    """Load padron lists. ``force=True`` (default) re-reads Sheet; pass False to reuse TTL cache."""
    cfg = cfg_store.get_config(company_id)
    ttl = int(cfg.get("refresh_minutes") or 15) * 60
    cache_key = str(company_id)
    if not force and cache_key in _data_cache:
        entry = _data_cache[cache_key]
        if time.time() - float(entry.get("_ts") or 0) < ttl:
            return entry

    mode, source, gid = resolve_sheet_source(cfg)
    sheet_rows: List[Dict[str, str]] = []
    cat_map: Dict[str, str] = {}
    sheet_error: Optional[str] = None

    if mode == "private" and source:
        try:
            sheet_rows = fetch_sheet(
                spreadsheet_id=source, gid=gid, ttl=ttl, force=force
            )
        except Exception as e:
            sheet_error = friendly_sheet_access_error(e, spreadsheet_id=str(source))
            sheet_rows = []
        if not sheet_error:
            try:
                # force=False: reusa el CSV recién cacheado por fetch_sheet (evita 2° hit → 429).
                cat_map = extract_category_map(
                    spreadsheet_id=source, gid=gid, force=False
                )
            except Exception:
                cat_map = {}
    elif mode == "public" and source:
        try:
            sheet_rows = fetch_sheet(url=source, ttl=ttl, force=force)
        except Exception as e:
            sheet_error = f"No se pudo leer la URL publicada del Sheet: {e}"
            sheet_rows = []
        if not sheet_error:
            try:
                cat_map = extract_category_map(url=source, force=False)
            except Exception:
                cat_map = {}
    elif mode == "private_unconfigured":
        sheet_error = (
            "Hay spreadsheet_id pero falta GOOGLE_SERVICE_ACCOUNT_JSON en el server."
        )

    mapping = cfg.get("mapping") or {}
    m_prov = mapping.get("proveedores") or {}
    m_prod = mapping.get("productos") or {}
    m_fp = mapping.get("formas_pago") or {}
    m_conc = mapping.get("conceptos") or {}
    m_mes = mapping.get("meses") or {}
    m_suc = mapping.get("sucursales") or {}

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

    # Mes / Sucursal: valores únicos de columnas Config (mismo sheet_rows).
    col_mes = (m_mes.get("nombre") or "Mes").strip()
    col_suc = (m_suc.get("nombre") or "Sucursal").strip()
    meses = extract_column_values(sheet_rows or [], col_mes) if col_mes else []
    sucursales = extract_column_values(sheet_rows or [], col_suc) if col_suc else []

    mapped_cat = extract_category_map_from_rows(
        conc_rows,
        m_conc.get("nombre") or "",
        m_conc.get("categoria") or "",
    )
    if mapped_cat:
        cat_map = mapped_cat

    # Categorías desde hoja Gastos (única fuente real; fallback Pepe).
    categorias_gasto: List[str] = []
    sid = (cfg.get("spreadsheet_id") or "").strip()
    if not sid and mode == "private" and source:
        sid = str(source).strip()
    gastos_gid = (cfg.get("gastos_sheet_gid") or "").strip()
    if sid and not sheet_error:
        try:
            from facturia_matching.padron.gastos_history import (
                load_gastos_history,
                unique_categorias,
            )

            recs = load_gastos_history(
                spreadsheet_id=sid, gid=gastos_gid or "541219037", force=False
            )
            categorias_gasto = unique_categorias(recs or [])
        except Exception:
            categorias_gasto = []
    if not categorias_gasto:
        categorias_gasto = [
            "Gastos Fijos",
            "Gastos Var",
            "CMV",
            "Financieros",
            "Impuestos",
            "Retiro Socios",
        ]

    data = {
        "proveedores": proveedores,
        "productos": productos,
        "formas_pago": [r["nombre"] for r in formas_pago],
        "conceptos": [r["nombre"] for r in conceptos],
        "meses": meses,
        "sucursales": sucursales,
        "categorias_gasto": categorias_gasto,
        "categoria_map": cat_map,
        "config": cfg,
        "sheet_source_mode": mode or "none",
        "sheet_error": sheet_error,
        "_ts": time.time(),
    }
    # Don't cache failed private reads for the full TTL — retry sooner.
    if sheet_error:
        data["_ts"] = time.time() - max(ttl - 60, 0)
    _data_cache[cache_key] = data
    return data


def invalidate_data_cache(company_id: Optional[int] = None) -> None:
    if company_id is None:
        _data_cache.clear()
    else:
        _data_cache.pop(str(company_id), None)
