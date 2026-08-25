"""Rutas de UI bootstrap, metadata, padrón y CSV."""

import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from facturia_matching.api.profile import _resolve_request_odoo_profile, _with_odoo_profile
from facturia_matching.core.options import build_metadata_payload, get_options
from facturia_matching.export.csv_export import build_csv_response
from facturia_matching.infra.config import DB_SCHEMA, DB_TABLE_NAME, PROCESS_SCHEMA
from facturia_matching.infra.paths import CSS_DIR, HTML_DIR, JS_DIR
from facturia_matching.odoo.empresa_profile import (
    empresa_odoo_display_labels,
    empresa_odoo_profile_map,
)
from facturia_matching.odoo.env import current_odoo_profile, uses_odoo_padron_first
from facturia_matching.padron.postgres import detect_padron_fields, get_table_columns

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def root():
    index_path = HTML_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h3>Falta html/index.html</h3>", status_code=500)
    html = index_path.read_text(encoding="utf-8")
    # Bust cache de CSS/JS entrypoint con mtime más reciente de assets tocados por UI.
    mtimes = []
    for path in (
        CSS_DIR / "styles.css",
        JS_DIR / "main.js",
        JS_DIR / "ocPicker" / "render.js",
        JS_DIR / "comprobanteView" / "render.js",
    ):
        if path.is_file():
            mtimes.append(int(path.stat().st_mtime))
    if mtimes:
        v = max(mtimes)
        html = html.replace('href="/css/styles.css"', f'href="/css/styles.css?v={v}"')
        html = html.replace('src="/js/main.js"', f'src="/js/main.js?v={v}"')
    return HTMLResponse(html)


@router.get("/api/metadata")
def get_metadata():
    return build_metadata_payload()


@router.get("/api/bootstrap")
def get_bootstrap(
    empresa: Optional[str] = None,
    perfil: Optional[str] = Query(None),
    odoo_profile_q: Optional[str] = Query(None, alias="odoo_profile_test"),
    odoo_cloud: Optional[str] = Query(None),
):
    odoo_profile = _resolve_request_odoo_profile(
        perfil, odoo_profile_q, odoo_cloud, empresa=empresa
    )

    def _boot():
        t0 = time.perf_counter()
        meta = build_metadata_payload()
        t_meta = time.perf_counter()
        opts = get_options(padron=False)
        t_opts = time.perf_counter()
        payload = {
            "metadata": meta,
            "options": opts,
            "odoo_profile": current_odoo_profile(),
            "process_schema": PROCESS_SCHEMA,
            "empresa_odoo_profiles": empresa_odoo_profile_map(),
            "empresa_odoo_labels": empresa_odoo_display_labels(),
        }
        logger.debug(
            "timing /api/bootstrap profile=%s meta=%.0fms options=%.0fms total=%.0fms",
            current_odoo_profile(),
            (t_meta - t0) * 1000,
            (t_opts - t_meta) * 1000,
            (time.perf_counter() - t0) * 1000,
        )
        return payload

    return _with_odoo_profile(odoo_profile, _boot, empresa=empresa)


@router.get("/api/options")
def api_options(
    padron: bool = Query(False, description="Si true, carga opciones grandes desde DB (puede tardar)."),
    empresa: Optional[str] = None,
    perfil: Optional[str] = Query(None),
    odoo_profile_q: Optional[str] = Query(None, alias="odoo_profile_test"),
    odoo_cloud: Optional[str] = Query(None),
):
    odoo_profile = _resolve_request_odoo_profile(
        perfil, odoo_profile_q, odoo_cloud, empresa=empresa
    )
    return _with_odoo_profile(odoo_profile, lambda: get_options(padron=padron), empresa=empresa)


@router.get("/api/padron/schema")
def get_padron_schema():
    cols = get_table_columns()
    detected = detect_padron_fields(cols)
    return {
        "schema": DB_SCHEMA,
        "table": DB_TABLE_NAME,
        "columns": cols,
        "detected_fields": detected,
        "has_invoice_line_ids_name_column": bool(detected.get("invoice_line_ids_name")),
        "has_etiqueta_column": bool(detected.get("etiqueta")),
    }


@router.get("/api/padron/odoo")
def get_padron_odoo(
    limit: int = Query(50, ge=1, le=500),
    perfil: Optional[str] = Query(None),
    odoo_profile_q: Optional[str] = Query(None, alias="odoo_profile_test"),
    odoo_cloud: Optional[str] = Query(None),
):
    odoo_profile = _resolve_request_odoo_profile(perfil, odoo_profile_q, odoo_cloud)
    """Padrón desde últimas facturas Odoo (perfil aliare/sudata: odoo antes que Postgres)."""

    def _padron():
        from facturia_matching.infra.config import PADRON_SOURCE
        from facturia_matching.padron.odoo import build_padron_rows_from_odoo

        rows = build_padron_rows_from_odoo(limit=limit)
        return {
            "source": PADRON_SOURCE or ("odoo,postgres" if uses_odoo_padron_first() else "postgres"),
            "count": len(rows),
            "rows": rows[:limit],
            "odoo_profile": current_odoo_profile(),
        }

    return _with_odoo_profile(odoo_profile, _padron)


@router.post("/api/csv")
def post_csv(payload: Dict[str, Any]):
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="payload.rows debe ser una lista")
    return build_csv_response(rows)
