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
from facturia_matching.process import build_output_rows
from facturia_matching.process_conversions import (
    ProcessConversionError,
    delete_conversion,
    infer_otro_impuesto_indices,
    load_process_rows,
    resolve_process_row,
    save_conversion,
)
from facturia_matching.purchase_matching import apply_oc_selection, rematch_comprobante_purchase

router = APIRouter()


def _build_proceso_response(
    process_number: str,
    empresa: Optional[str],
    filas: list,
    etiqueta_options: list,
    purchase_summary: dict,
    source: str,
    conversion_meta: Optional[dict] = None,
) -> dict:
    if not filas:
        return {
            "ok": True,
            "process_number": process_number,
            "empresa": empresa,
            "rows": [],
            "source": source,
            "message": "Sin filas para ese proceso.",
        }
    out_rows = build_output_rows(filas)
    resp = {
        "ok": True,
        "process_number": process_number,
        "empresa": empresa,
        "rows": out_rows,
        "source": source,
        "etiqueta_options": etiqueta_options,
        "product_options": etiqueta_options,
        "purchase_matching": purchase_summary,
        "debug": {
            "filas": len(out_rows),
        },
    }
    if conversion_meta:
        if conversion_meta.get("id") is not None:
            resp["conversion_id"] = conversion_meta["id"]
        if conversion_meta.get("saved_at"):
            resp["saved_at"] = conversion_meta["saved_at"]
        if conversion_meta.get("extra_tax_indices"):
            resp["extra_tax_indices"] = conversion_meta["extra_tax_indices"]
        if conversion_meta.get("odoo_profile"):
            resp["odoo_profile"] = conversion_meta["odoo_profile"]
        if conversion_meta.get("template_id") is not None:
            resp["conversion_template_id"] = conversion_meta["template_id"]
    from facturia_matching.odoo_env import current_odoo_profile

    resp["odoo_profile"] = resp.get("odoo_profile") or current_odoo_profile()
    return resp


def _handle_process_load_errors(fn):
    try:
        return fn()
    except MySQLUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ProcessTableError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except ProcessConversionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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
    from facturia_matching.odoo_env import is_odoo_aliare_profile

    meta = build_metadata_payload()
    opts = get_options(padron=False)
    return {
        "metadata": meta,
        "options": opts,
        "odoo_profile": "aliare" if is_odoo_aliare_profile() else "default",
    }


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
    from facturia_matching.odoo_env import _aliare_secret, is_odoo_aliare_profile

    config = get_odoo_test_config()
    if not is_odoo_config_ready(config):
        if is_odoo_aliare_profile():
            err = (
                "Faltan variables Odoo Aliare (ODOO_BASE_URL_ALIARE, ODOO_DB_ALIARE, "
                "ODOO_USER_ALIARE u ODOO_USER_ID_ALIARE con email, y ODOO_API_KEY_ALIARE u ODOO_PASSWORD_ALIARE)."
            )
        else:
            err = (
                "Faltan ODOO_*_TEST en .env "
                "(ODOO_API_TEST, ODOO_DB_TEST, y ODOO_PASSWORD_TEST u ODOO_API_KEY_TEST/ODOO_API_KEY, "
                "más ODOO_USER_ID_TEST u ODOO_USER_TEST)."
            )
        return {"ok": False, "error": err}
    if is_odoo_aliare_profile():
        _, credential_source = _aliare_secret()
    else:
        from facturia_matching.odoo_api import _resolve_odoo_test_secret

        _, credential_source = _resolve_odoo_test_secret()
    result = verify_odoo_config_connection(config)
    result["credential_source"] = credential_source
    result["profile"] = "aliare" if is_odoo_aliare_profile() else "default"
    return result


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


@router.get("/api/padron/odoo")
def get_padron_odoo(limit: int = Query(50, ge=1, le=500)):
    """Padrón desde últimas facturas Odoo (perfil aliare: odoo antes que Postgres)."""
    from facturia_matching.config import PADRON_SOURCE
    from facturia_matching.odoo_env import is_odoo_aliare_profile
    from facturia_matching.padron_odoo import build_padron_rows_from_odoo

    rows = build_padron_rows_from_odoo(limit=limit)
    return {
        "source": PADRON_SOURCE or ("odoo,postgres" if is_odoo_aliare_profile() else "postgres"),
        "count": len(rows),
        "rows": rows[:limit],
    }


@router.get("/api/proceso/{process_number}")
def get_proceso(
    process_number: str,
    empresa: Optional[str] = None,
    regenerate: bool = Query(False, description="Si true, ignora conversión guardada y regenera desde json_data."),
):
    def _load():
        filas, etiqueta_options, purchase_summary, source, conversion_meta = load_process_rows(
            process_number,
            empresa=empresa,
            regenerate=regenerate,
        )
        return _build_proceso_response(
            process_number,
            empresa,
            filas,
            etiqueta_options,
            purchase_summary,
            source,
            conversion_meta,
        )

    return _handle_process_load_errors(_load)


@router.post("/api/proceso/{process_number}/select-oc")
def post_proceso_select_oc(process_number: str, payload: Dict[str, Any]):
    comprobante_idx = payload.get("comprobante_idx")
    order_id = payload.get("order_id")
    empresa = payload.get("empresa")
    if comprobante_idx is None:
        raise HTTPException(status_code=400, detail="comprobante_idx es requerido")
    if order_id is None or not str(order_id).strip().isdigit():
        raise HTTPException(status_code=400, detail="order_id debe ser un entero")

    def _select():
        from facturia_matching.process import parse_process_json
        from facturia_matching.process_conversions import get_saved_conversion

        process_row = resolve_process_row(process_number, empresa=empresa)
        saved = get_saved_conversion(int(process_row["id"])) if process_row.get("id") else None

        if saved and saved.get("rows"):
            from facturia_matching.saved_row_remap import remap_saved_rows_to_catalog

            filas = remap_saved_rows_to_catalog(saved["rows"])
            conversion_meta = {
                "id": saved.get("id"),
                "extra_tax_indices": saved.get("extra_tax_indices") or [],
            }
        else:
            filas, _, _ = parse_process_json(process_number, empresa=empresa)
            conversion_meta = {}

        try:
            comp_idx = int(comprobante_idx)
        except (TypeError, ValueError) as e:
            raise ProcessConversionError("comprobante_idx inválido") from e

        purchase_summary = apply_oc_selection(filas, comp_idx, int(order_id))
        result = save_conversion(
            process_row["id"],
            process_row["company_id"],
            process_row.get("user_id"),
            filas,
        )
        conversion_meta["id"] = result.get("id")
        conversion_meta["saved_at"] = result.get("saved_at")

        etiqueta_opts: list = []
        for row in filas:
            desc = row.get("invoice_line_ids/name") or row.get("Nombre de producto") or ""
            if desc and str(desc).strip():
                etiqueta_opts.append(str(desc).strip())
        etiqueta_opts = sorted({p for p in etiqueta_opts if p})

        return _build_proceso_response(
            process_number,
            empresa,
            filas,
            etiqueta_opts,
            purchase_summary,
            "saved",
            conversion_meta,
        )

    return _handle_process_load_errors(_select)


@router.post("/api/proceso/{process_number}/rematch-purchase")
def post_proceso_rematch_purchase(process_number: str, payload: Dict[str, Any]):
    rows = payload.get("rows")
    comprobante_idx = payload.get("comprobante_idx")
    empresa = payload.get("empresa")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="payload.rows debe ser una lista")
    if comprobante_idx is None:
        raise HTTPException(status_code=400, detail="comprobante_idx es requerido")

    def _rematch():
        process_row = resolve_process_row(process_number, empresa=empresa)
        try:
            comp_idx = int(comprobante_idx)
        except (TypeError, ValueError) as e:
            raise ProcessConversionError("comprobante_idx inválido") from e

        purchase_summary = rematch_comprobante_purchase(rows, comp_idx)
        result = save_conversion(
            process_row["id"],
            process_row["company_id"],
            process_row.get("user_id"),
            rows,
        )
        conversion_meta = {
            "id": result.get("id"),
            "saved_at": result.get("saved_at"),
            "extra_tax_indices": infer_otro_impuesto_indices(rows),
        }

        etiqueta_opts: list = []
        for row in rows:
            desc = row.get("invoice_line_ids/name") or row.get("Nombre de producto") or ""
            if desc and str(desc).strip():
                etiqueta_opts.append(str(desc).strip())
        etiqueta_opts = sorted({p for p in etiqueta_opts if p})

        return _build_proceso_response(
            process_number,
            empresa,
            rows,
            etiqueta_opts,
            purchase_summary,
            "saved",
            conversion_meta,
        )

    return _handle_process_load_errors(_rematch)


@router.put("/api/proceso/{process_number}/conversion")
def put_proceso_conversion(process_number: str, payload: Dict[str, Any]):
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="payload.rows debe ser una lista")
    empresa = payload.get("empresa")

    def _save():
        process_row = resolve_process_row(process_number, empresa=empresa)
        result = save_conversion(
            process_row["id"],
            process_row["company_id"],
            process_row.get("user_id"),
            rows,
        )
        return {
            "ok": True,
            "process_number": process_number,
            "empresa": empresa,
            "source": "saved",
            "conversion_id": result.get("id"),
            "saved_at": result.get("saved_at"),
        }

    return _handle_process_load_errors(_save)


@router.post("/api/proceso/{process_number}/revert")
def post_proceso_revert(process_number: str, payload: Optional[Dict[str, Any]] = None):
    payload = payload or {}
    empresa = payload.get("empresa")

    def _revert():
        process_row = resolve_process_row(process_number, empresa=empresa)
        delete_conversion(process_row["id"])
        filas, etiqueta_options, purchase_summary, source, conversion_meta = load_process_rows(
            process_number,
            empresa=empresa,
            regenerate=True,
        )
        return _build_proceso_response(
            process_number,
            empresa,
            filas,
            etiqueta_options,
            purchase_summary,
            source,
            conversion_meta,
        )

    return _handle_process_load_errors(_revert)


@router.post("/api/csv")
def post_csv(payload: Dict[str, Any]):
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="payload.rows debe ser una lista")
    return build_csv_response(rows)
