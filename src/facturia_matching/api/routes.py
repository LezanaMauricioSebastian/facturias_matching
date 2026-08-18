"""FastAPI route handlers."""

import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

from facturia_matching.infra.config import DB_SCHEMA, DB_TABLE_NAME, PROCESS_SCHEMA
from facturia_matching.odoo.empresa_profile import (
    empresa_odoo_display_labels,
    empresa_odoo_profile_map,
    resolve_odoo_profile_from_empresa,
)
from facturia_matching.odoo.api import get_active_odoo_config
from facturia_matching.odoo.request_context import odoo_profile_context
from facturia_matching.odoo.env import (
    current_odoo_profile,
    is_odoo_aliare_profile,
    is_odoo_cloud_flag,
    is_odoo_sudata_profile,
    uses_odoo_padron_first,
)
from facturia_matching.export.csv_export import build_csv_response
from facturia_matching.odoo.api import (
    _jsonrpc_url,
    get_odoo_import_config,
    is_odoo_config_ready,
    odoo_xmlrpc_version,
    verify_odoo_config_connection,
)

# No exponer uid Odoo en respuestas HTTP de health (dato interno de sesión XML-RPC).
_HEALTH_PRIVATE_KEYS = ("uid", "auth_uid", "uid_source")


def _public_health_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Copia de un dict de health sin campos de identidad Odoo."""
    return {k: v for k, v in data.items() if k not in _HEALTH_PRIVATE_KEYS}
from facturia_matching.odoo.import_ import import_rows_to_odoo
from facturia_matching.core.options import build_metadata_payload, get_options
from facturia_matching.padron.postgres import detect_padron_fields, get_table_columns
from facturia_matching.infra.paths import CSS_DIR, HTML_DIR, JS_DIR
from facturia_matching.core.process import build_output_rows
from facturia_matching.persistence.back_check import MySQLUnavailableError, ProcessTableError
from facturia_matching.persistence.process_conversions import (
    ProcessConversionError,
    delete_conversion,
    infer_otro_impuesto_indices,
    load_process_rows,
    resolve_process_row,
    save_conversion,
)
from facturia_matching.odoo.purchase_matching import (
    apply_oc_selection,
    apply_product_uom_to_row,
    list_uoms_for_product,
    rematch_comprobante_purchase,
    search_oc_candidates_for_comprobante,
)

router = APIRouter()


def _coalesce_odoo_profile(
    perfil: Optional[str],
    odoo_profile_q: Optional[str],
) -> Optional[str]:
    return odoo_profile_q or perfil


def _resolve_request_odoo_profile(
    perfil: Optional[str] = None,
    odoo_profile_q: Optional[str] = None,
    odoo_cloud: Optional[Any] = None,
    payload: Optional[Dict[str, Any]] = None,
    empresa: Optional[Any] = None,
) -> Optional[str]:
    """odoo_cloud=1 → sudata; perfil explícito gana sobre ?empresa=N (PROCESS_SCHEMA)."""
    if payload:
        if is_odoo_cloud_flag(payload.get("odoo_cloud")):
            return "sudata"
        body_profile = payload.get("odoo_profile_test") or payload.get("perfil")
        if body_profile is not None and str(body_profile).strip() != "":
            return str(body_profile).strip()
        if empresa is None:
            empresa = payload.get("empresa")
    if is_odoo_cloud_flag(odoo_cloud):
        return "sudata"
    explicit = _coalesce_odoo_profile(perfil, odoo_profile_q)
    if explicit is not None and str(explicit).strip() != "":
        return str(explicit).strip()
    mapped = resolve_odoo_profile_from_empresa(empresa)
    if mapped:
        return mapped
    return None


def _with_odoo_profile(
    odoo_profile: Optional[str],
    fn,
    empresa: Optional[Any] = None,
):
    emp = str(empresa).strip() if empresa is not None and str(empresa).strip() != "" else None
    with odoo_profile_context(odoo_profile, empresa=emp):
        return fn()


def _payload_odoo_profile(payload: Optional[Dict[str, Any]]) -> Optional[str]:
    return _resolve_request_odoo_profile(payload=payload)


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
        logger.warning(
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


@router.get("/api/odoo/health")
def odoo_health(
    empresa: Optional[str] = Query(None),
    perfil: Optional[str] = Query(None),
    odoo_profile_q: Optional[str] = Query(None, alias="odoo_profile_test"),
    odoo_cloud: Optional[str] = Query(None),
):
    odoo_profile = _resolve_request_odoo_profile(
        perfil, odoo_profile_q, odoo_cloud, empresa=empresa
    )
    def _health():
        cfg = get_active_odoo_config()
        if not is_odoo_config_ready(cfg):
            return {
                "ok": False,
                "error": "Odoo no configurado (ni company_erp_credentials ni ODOO_* en .env)",
                "credential_source": cfg.get("credential_source") or "none",
                "odoo_profile": current_odoo_profile(),
            }
        verified = verify_odoo_config_connection(cfg)
        if not verified.get("ok"):
            return _public_health_payload(
                {
                    **verified,
                    "jsonrpc_url": _jsonrpc_url(),
                    "odoo_profile": current_odoo_profile(),
                    "credential_source": cfg.get("credential_source"),
                }
            )
        return {
            "ok": True,
            "db": cfg.get("db"),
            "base_url": cfg.get("base_url"),
            "jsonrpc_url": _jsonrpc_url(),
            "odoo_profile": current_odoo_profile(),
            "credential_source": cfg.get("credential_source"),
            "version": verified.get("version") or odoo_xmlrpc_version(),
        }

    return _with_odoo_profile(odoo_profile, _health, empresa=empresa)


@router.get("/api/odoo/health/import")
def odoo_health_import(
    empresa: Optional[str] = Query(None),
    perfil: Optional[str] = Query(None),
    odoo_profile_q: Optional[str] = Query(None, alias="odoo_profile_test"),
    odoo_cloud: Optional[str] = Query(None),
):
    odoo_profile = _resolve_request_odoo_profile(
        perfil, odoo_profile_q, odoo_cloud, empresa=empresa
    )
    def _health_import():
        from facturia_matching.odoo.env import _aliare_secret, _sudata_secret

        config = get_odoo_import_config()
        if not is_odoo_config_ready(config):
            if is_odoo_sudata_profile():
                err = (
                    "Faltan variables Odoo Sudata (ODOO_BASE_URL_SUDATA o URL_SUDATA, "
                    "ODOO_USER_SUDATA o USERNAME_SUDATA, y ODOO_API_KEY_SUDATA u ODOO_PASSWORD_SUDATA; "
                    "ODOO_DB_SUDATA o DB_SUDATA opcional) "
                    "o credenciales en company_erp_credentials para la empresa."
                )
            elif is_odoo_aliare_profile():
                err = (
                    "Faltan variables Odoo Aliare (ODOO_BASE_URL_ALIARE, "
                    "ODOO_USER_ALIARE u ODOO_USER_ID_ALIARE con email, y ODOO_API_KEY_ALIARE u ODOO_PASSWORD_ALIARE; "
                    "ODOO_DB_ALIARE opcional si hay una sola base o coincide con el host) "
                    "o credenciales en company_erp_credentials para la empresa."
                )
            else:
                err = (
                    "Faltan variables Odoo Dinner (ODOO_BASE_URL, "
                    "ODOO_USER_ID u ODOO_USER, y ODOO_PASSWORD u ODOO_API_KEY; "
                    "ODOO_DB opcional si hay una sola base) "
                    "o credenciales en company_erp_credentials para la empresa."
                )
            return {"ok": False, "error": err}
        credential_source = config.get("credential_source") or "env"
        if credential_source == "env":
            if is_odoo_sudata_profile():
                _, credential_source = _sudata_secret()
            elif is_odoo_aliare_profile():
                _, credential_source = _aliare_secret()
            else:
                from facturia_matching.infra.env import env_strip

                if env_strip("ODOO_API_KEY"):
                    credential_source = "ODOO_API_KEY"
                elif env_strip("ODOO_PASSWORD"):
                    credential_source = "ODOO_PASSWORD"
                else:
                    credential_source = "none"
        result = verify_odoo_config_connection(config)
        result["credential_source"] = credential_source
        result["profile"] = current_odoo_profile()
        if config.get("company_id") is not None:
            result["company_id"] = config.get("company_id")
        return _public_health_payload(result)

    return _with_odoo_profile(odoo_profile, _health_import, empresa=empresa)


@router.get("/api/odoo/health/credenciales_db")
def odoo_health_credenciales_db(
    empresa: Optional[str] = Query(
        None,
        description="Si se omite, prueba todas las credenciales activas del PROCESS_SCHEMA.",
    ),
):
    """
    Health solo contra `company_erp_credentials` (+ configs). No usa .env.
    Errores: respuesta mínima `{"ok": false, "error": "..."}`.
    """
    from facturia_matching.infra.config import PROCESS_SCHEMA
    from facturia_matching.odoo.env import _config_from_credential_map
    from facturia_matching.persistence.company_erp_credentials import (
        list_active_company_odoo_credentials,
    )

    def _err(msg: str) -> Dict[str, Any]:
        return {"ok": False, "error": msg}

    def _missing_fields(cfg: Dict[str, Any], kv: Dict[str, str]) -> list:
        missing = []
        if not (cfg.get("base_url") or kv.get("ODOO_BASE_URL")):
            missing.append("ODOO_BASE_URL")
        if not (kv.get("ODOO_PASSWORD") or kv.get("ODOO_API_KEY")):
            missing.append("ODOO_PASSWORD|ODOO_API_KEY")
        if not (cfg.get("login") or cfg.get("uid") is not None):
            missing.append("ODOO_USER_ID|ODOO_USER")
        if not cfg.get("db"):
            missing.append("ODOO_DB (no se pudo deducir)")
        return missing

    rows = list_active_company_odoo_credentials(company_id=empresa)
    if not rows:
        scope = f" para empresa={empresa}" if empresa else ""
        return _err(
            f"No hay credenciales activas en company_erp_credentials{scope} "
            f"(schema={PROCESS_SCHEMA})."
        )

    results: list = []
    errors: list = []
    for row in rows:
        company_id = row.get("company_id")
        label = row.get("company_name") or f"company_id={company_id}"
        kv = row.get("config") or {}
        cfg = _config_from_credential_map(kv, company_id=company_id)
        if not is_odoo_config_ready(cfg):
            missing = _missing_fields(cfg, kv)
            msg = (
                f"{label}: falta {', '.join(missing)}"
                if missing
                else f"{label}: credencial incompleta en tablas"
            )
            errors.append(msg)
            continue
        verified = verify_odoo_config_connection(cfg)
        if not verified.get("ok"):
            detail = verified.get("error") or verified.get("hint") or "conexión fallida"
            errors.append(f"{label}: {detail}")
            continue
        results.append(
            {
                "ok": True,
                "company_id": company_id,
                "company_name": row.get("company_name"),
            }
        )

    if errors:
        return _err("; ".join(errors))

    if len(results) == 1:
        return results[0]
    return {"ok": True, "count": len(results), "results": results}


@router.post("/api/odoo/health/credenciales")
def odoo_health_credenciales(payload: Dict[str, Any]):
    """
    Valida credenciales Odoo del body **antes de guardar** en MySQL.
    No lee `company_erp_credentials` ni `.env`.

    Body: keys `ODOO_*` (planas o en `config`), mismas que `company_erp_credential_configs`.
    Errores: `{"ok": false, "error": "..."}`.
    """
    from facturia_matching.odoo.env import _config_from_credential_map
    from facturia_matching.persistence.company_erp_credentials import ODOO_CONFIG_KEYS

    def _err(msg: str) -> Dict[str, Any]:
        return {"ok": False, "error": msg}

    if not isinstance(payload, dict):
        return _err("Body JSON inválido.")

    raw = payload.get("config") if isinstance(payload.get("config"), dict) else payload
    kv: Dict[str, str] = {}
    for key in ODOO_CONFIG_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if s:
            kv[key] = s

    if not kv:
        return _err(
            "Faltan credenciales en el body "
            "(ODOO_BASE_URL, ODOO_USER_ID|ODOO_USER, ODOO_PASSWORD|ODOO_API_KEY; ODOO_DB opcional)."
        )

    company_id = payload.get("company_id") or payload.get("empresa") or raw.get("company_id")
    cfg = _config_from_credential_map(kv, company_id=company_id if company_id is not None else 0)

    missing = []
    if not (cfg.get("base_url") or kv.get("ODOO_BASE_URL")):
        missing.append("ODOO_BASE_URL")
    if not (kv.get("ODOO_PASSWORD") or kv.get("ODOO_API_KEY")):
        missing.append("ODOO_PASSWORD|ODOO_API_KEY")
    if not (cfg.get("login") or cfg.get("uid") is not None):
        missing.append("ODOO_USER_ID|ODOO_USER")
    if not cfg.get("db"):
        missing.append("ODOO_DB (no se pudo deducir)")
    if missing:
        return _err(f"Falta {', '.join(missing)}")

    if not is_odoo_config_ready(cfg):
        return _err("Credencial incompleta.")

    verified = verify_odoo_config_connection(cfg)
    if not verified.get("ok"):
        detail = verified.get("error") or verified.get("hint") or "conexión fallida"
        return _err(detail)

    out: Dict[str, Any] = {"ok": True}
    if company_id is not None and str(company_id).strip() != "":
        out["company_id"] = (
            int(company_id) if str(company_id).strip().isdigit() else company_id
        )
    if verified.get("db"):
        out["db"] = verified.get("db")
    return out


@router.post("/api/odoo/import")
def odoo_import(
    payload: Dict[str, Any],
    perfil: Optional[str] = Query(None),
    odoo_profile_q: Optional[str] = Query(None, alias="odoo_profile_test"),
    odoo_cloud: Optional[str] = Query(None),
):
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="payload.rows debe ser una lista")
    skip_duplicates = payload.get("skip_duplicates", True)
    update_taxes_if_exists = payload.get("update_taxes_if_exists", True)
    empresa = payload.get("empresa")
    odoo_profile = _resolve_request_odoo_profile(perfil, odoo_profile_q, odoo_cloud, payload)

    def _import():
        return import_rows_to_odoo(
            rows,
            skip_duplicates=bool(skip_duplicates),
            update_taxes_if_exists=bool(update_taxes_if_exists),
        )

    return _with_odoo_profile(odoo_profile, _import, empresa=empresa)


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


@router.get("/api/proceso/{process_number}")
def get_proceso(
    process_number: str,
    empresa: Optional[str] = None,
    perfil: Optional[str] = Query(None),
    odoo_profile_q: Optional[str] = Query(None, alias="odoo_profile_test"),
    odoo_cloud: Optional[str] = Query(None),
    regenerate: bool = Query(False, description="Si true, ignora conversión guardada y regenera desde json_data."),
):
    odoo_profile = _resolve_request_odoo_profile(
        perfil, odoo_profile_q, odoo_cloud, empresa=empresa
    )
    def _load():
        t0 = time.perf_counter()
        filas, etiqueta_options, purchase_summary, source, conversion_meta = load_process_rows(
            process_number,
            empresa=empresa,
            regenerate=regenerate,
        )
        t_load = time.perf_counter()
        resp = _build_proceso_response(
            process_number,
            empresa,
            filas,
            etiqueta_options,
            purchase_summary,
            source,
            conversion_meta,
        )
        logger.warning(
            "timing /api/proceso/%s profile=%s empresa=%s source=%s rows=%s "
            "load=%.0fms build=%.0fms total=%.0fms",
            process_number,
            current_odoo_profile(),
            empresa or "-",
            source,
            len(filas or []),
            (t_load - t0) * 1000,
            (time.perf_counter() - t_load) * 1000,
            (time.perf_counter() - t0) * 1000,
        )
        return resp

    return _handle_process_load_errors(
        lambda: _with_odoo_profile(odoo_profile, _load, empresa=empresa)
    )


@router.post("/api/proceso/{process_number}/select-oc")
def post_proceso_select_oc(process_number: str, payload: Dict[str, Any]):
    comprobante_idx = payload.get("comprobante_idx")
    order_id = payload.get("order_id")
    empresa = payload.get("empresa")
    odoo_profile = _payload_odoo_profile(payload)
    if comprobante_idx is None:
        raise HTTPException(status_code=400, detail="comprobante_idx es requerido")
    if order_id is None:
        raise HTTPException(status_code=400, detail="order_id es requerido")
    order_raw = str(order_id).strip()
    if order_raw not in ("0", "none") and not order_raw.isdigit():
        raise HTTPException(status_code=400, detail="order_id debe ser un entero o 0 (Sin OC)")

    def _select():
        from facturia_matching.core.process import parse_process_json
        from facturia_matching.persistence.process_conversions import get_saved_conversion

        process_row = resolve_process_row(process_number, empresa=empresa)
        saved = get_saved_conversion(int(process_row["id"])) if process_row.get("id") else None

        if saved and saved.get("rows"):
            from facturia_matching.persistence.saved_row_remap import remap_saved_rows_to_catalog

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

        purchase_summary = apply_oc_selection(
            filas,
            comp_idx,
            int(order_raw),
            company_id=process_row.get("company_id"),
        )
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

    return _handle_process_load_errors(
        lambda: _with_odoo_profile(odoo_profile, _select, empresa=empresa)
    )


@router.post("/api/proceso/{process_number}/search-oc")
def post_proceso_search_oc(process_number: str, payload: Dict[str, Any]):
    rows = payload.get("rows")
    comprobante_idx = payload.get("comprobante_idx")
    empresa = payload.get("empresa")
    odoo_profile = _payload_odoo_profile(payload)
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="payload.rows debe ser una lista")
    if comprobante_idx is None:
        raise HTTPException(status_code=400, detail="comprobante_idx es requerido")

    def _search():
        process_row = resolve_process_row(process_number, empresa=empresa)
        try:
            comp_idx = int(comprobante_idx)
        except (TypeError, ValueError) as e:
            raise ProcessConversionError("comprobante_idx inválido") from e

        try:
            purchase_summary = search_oc_candidates_for_comprobante(rows, comp_idx)
        except ValueError as e:
            raise ProcessConversionError(str(e)) from e
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

    return _handle_process_load_errors(
        lambda: _with_odoo_profile(odoo_profile, _search, empresa=empresa)
    )


@router.post("/api/proceso/{process_number}/rematch-purchase")
def post_proceso_rematch_purchase(process_number: str, payload: Dict[str, Any]):
    rows = payload.get("rows")
    comprobante_idx = payload.get("comprobante_idx")
    empresa = payload.get("empresa")
    odoo_profile = _payload_odoo_profile(payload)
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

    return _handle_process_load_errors(
        lambda: _with_odoo_profile(odoo_profile, _rematch, empresa=empresa)
    )


@router.post("/api/proceso/{process_number}/rematch-uom")
def post_proceso_rematch_uom(process_number: str, payload: Dict[str, Any]):
    """Recalcula UM al elegir/borrar producto o al elegir UM a mano (uom_id opcional)."""
    row = payload.get("row")
    odoo_profile = _payload_odoo_profile(payload)
    if not isinstance(row, dict):
        raise HTTPException(status_code=400, detail="payload.row debe ser un objeto")

    def _rematch_uom():
        resolve_process_row(process_number, empresa=payload.get("empresa"))
        pid_raw = str(
            payload.get("product_id") or row.get("invoice_line_ids/product_id") or ""
        ).strip()
        product_id = int(pid_raw) if pid_raw.isdigit() else None
        if product_id is not None:
            row["invoice_line_ids/product_id"] = str(product_id)
        else:
            row["invoice_line_ids/product_id"] = ""
        uom_id = None
        raw_uom = payload.get("uom_id")
        if raw_uom is not None and str(raw_uom).strip() != "":
            try:
                uom_id = int(raw_uom)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="payload.uom_id inválido")
        uom_info = apply_product_uom_to_row(row, product_id, uom_id=uom_id)
        uoms = list_uoms_for_product(product_id) if product_id else []
        return {
            "ok": True,
            "row_index": payload.get("row_index"),
            "row": row,
            "uom": uom_info,
            "uoms": uoms,
        }

    return _handle_process_load_errors(
        lambda: _with_odoo_profile(
            odoo_profile, _rematch_uom, empresa=payload.get("empresa")
        )
    )


@router.get("/api/proceso/{process_number}/product-uoms")
def get_proceso_product_uoms(
    process_number: str,
    product_id: str = Query(...),
    empresa: Optional[str] = Query(None),
    perfil: Optional[str] = Query(None),
    odoo_profile_q: Optional[str] = Query(None, alias="odoo_profile_test"),
    odoo_cloud: Optional[str] = Query(None),
):
    """Lista UOMs de la categoría del producto (sin mutar la fila)."""
    odoo_profile = _resolve_request_odoo_profile(
        perfil, odoo_profile_q, odoo_cloud, empresa=empresa
    )
    pid_raw = str(product_id or "").strip()
    if not pid_raw.isdigit():
        raise HTTPException(status_code=400, detail="product_id inválido")
    pid = int(pid_raw)

    def _list():
        resolve_process_row(process_number, empresa=empresa)
        return {"ok": True, "product_id": str(pid), "uoms": list_uoms_for_product(pid)}

    return _handle_process_load_errors(
        lambda: _with_odoo_profile(odoo_profile, _list, empresa=empresa)
    )


@router.put("/api/proceso/{process_number}/conversion")
def put_proceso_conversion(
    process_number: str,
    payload: Dict[str, Any],
    perfil: Optional[str] = Query(None),
    odoo_profile_q: Optional[str] = Query(None, alias="odoo_profile_test"),
    odoo_cloud: Optional[str] = Query(None),
):
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="payload.rows debe ser una lista")
    empresa = payload.get("empresa")
    odoo_profile = _resolve_request_odoo_profile(perfil, odoo_profile_q, odoo_cloud, payload)

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

    return _handle_process_load_errors(
        lambda: _with_odoo_profile(odoo_profile, _save, empresa=empresa)
    )


@router.post("/api/proceso/{process_number}/revert")
def post_proceso_revert(process_number: str, payload: Optional[Dict[str, Any]] = None):
    payload = payload or {}
    empresa = payload.get("empresa")
    odoo_profile = _payload_odoo_profile(payload)

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

    return _handle_process_load_errors(
        lambda: _with_odoo_profile(odoo_profile, _revert, empresa=empresa)
    )


@router.post("/api/csv")
def post_csv(payload: Dict[str, Any]):
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="payload.rows debe ser una lista")
    return build_csv_response(rows)
