"""FastAPI route handlers."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from facturia_matching.back_check import MySQLUnavailableError, ProcessTableError
from facturia_matching.config import DB_SCHEMA, DB_TABLE_NAME, ODOO_CONFIG
from facturia_matching.csv_export import build_csv_response
from facturia_matching.odoo_api import (
    _jsonrpc_url,
    get_odoo_test_config,
    get_odoo_uid,
    is_odoo_config_ready,
    is_odoo_configured,
    odoo_xmlrpc_version,
    verify_odoo_config_connection,
)
from facturia_matching.odoo_import import import_rows_to_odoo_test
from facturia_matching.options import build_metadata_payload, get_options
from facturia_matching.padron import detect_padron_fields, get_table_columns
from facturia_matching.paths import HTML_DIR
from facturia_matching.process import build_output_rows, parse_process_json

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def root():
    index_path = HTML_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h3>Falta html/index.html</h3>", status_code=500)
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@router.get("/api/metadata")
def get_metadata():
    return build_metadata_payload()


@router.get("/api/bootstrap")
def get_bootstrap():
    meta = build_metadata_payload()
    opts = get_options(padron=False)
    return {"metadata": meta, "options": opts}


@router.get("/api/options")
def api_options(
    padron: bool = Query(False, description="Si true, carga opciones grandes desde DB (puede tardar)."),
):
    return get_options(padron=padron)


@router.get("/api/odoo/health")
def odoo_health():
    if not is_odoo_configured():
        return {"ok": False, "error": "ODOO_* no configurado en .env"}
    uid = get_odoo_uid()
    version = odoo_xmlrpc_version()
    return {
        "ok": uid is not None,
        "uid": uid,
        "uid_source": "ODOO_USER_ID" if ODOO_CONFIG.get("uid") is not None else "ODOO_USER",
        "db": ODOO_CONFIG.get("db"),
        "base_url": ODOO_CONFIG.get("base_url"),
        "jsonrpc_url": _jsonrpc_url(),
        "version": version,
    }


@router.get("/api/odoo/health/test")
def odoo_health_test():
    config = get_odoo_test_config()
    if not is_odoo_config_ready(config):
        return {
            "ok": False,
            "error": "Faltan ODOO_*_TEST en .env (ODOO_API_TEST/ODOO_DB_TEST/ODOO_PASSWORD_TEST y ODOO_USER_ID_TEST u ODOO_USER_TEST).",
        }
    return verify_odoo_config_connection(config)


@router.post("/api/odoo/import/test")
def odoo_import_test(payload: Dict[str, Any]):
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="payload.rows debe ser una lista")
    skip_duplicates = payload.get("skip_duplicates", True)
    update_taxes_if_exists = payload.get("update_taxes_if_exists", True)
    return import_rows_to_odoo_test(
        rows,
        skip_duplicates=bool(skip_duplicates),
        update_taxes_if_exists=bool(update_taxes_if_exists),
    )


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


@router.get("/api/proceso/{process_number}")
def get_proceso(process_number: str, empresa: Optional[str] = None):
    try:
        filas, etiqueta_options, purchase_summary = parse_process_json(process_number, empresa=empresa)
    except MySQLUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ProcessTableError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    if not filas:
        return {
            "ok": True,
            "process_number": process_number,
            "empresa": empresa,
            "rows": [],
            "message": "Sin filas para ese proceso.",
        }
    out_rows = build_output_rows(filas)

    return {
        "ok": True,
        "process_number": process_number,
        "empresa": empresa,
        "rows": out_rows,
        "etiqueta_options": etiqueta_options,
        "product_options": etiqueta_options,
        "purchase_matching": purchase_summary,
        "debug": {
            "filas": len(out_rows),
        },
    }


@router.post("/api/csv")
def post_csv(payload: Dict[str, Any]):
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="payload.rows debe ser una lista")
    return build_csv_response(rows)
