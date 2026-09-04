"""Rutas de proceso, conversión, OC y UM."""

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from facturia_matching.api.proceso_response import (
    _build_proceso_response,
    _handle_process_load_errors,
)
from facturia_matching.api.profile import (
    _payload_odoo_profile,
    _resolve_request_odoo_profile,
    _with_odoo_profile,
)
from facturia_matching.odoo.env import current_odoo_profile
from facturia_matching.odoo.purchase_matching import (
    apply_oc_selection,
    apply_product_uom_to_row,
    list_uoms_for_product,
    rematch_comprobante_purchase,
    search_oc_candidates_for_comprobante,
)
from facturia_matching.persistence.process_conversions import (
    ProcessConversionError,
    delete_conversion,
    infer_otro_impuesto_indices,
    load_process_rows,
    resolve_process_row,
    save_conversion,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _etiqueta_options_from_rows(rows: List[Dict[str, Any]]) -> List[str]:
    etiqueta_opts: List[str] = []
    for row in rows or []:
        desc = row.get("invoice_line_ids/name") or row.get("Nombre de producto") or ""
        if desc and str(desc).strip():
            etiqueta_opts.append(str(desc).strip())
    return sorted({p for p in etiqueta_opts if p})


def _save_rows_and_respond(
    process_number: str,
    empresa: Optional[str],
    rows: List[Dict[str, Any]],
    purchase_summary: dict,
    process_row: Optional[Dict[str, Any]] = None,
    *,
    source: str = "saved",
) -> dict:
    """Persiste filas y arma la respuesta estándar de /api/proceso/*."""
    if process_row is None:
        process_row = resolve_process_row(process_number, empresa=empresa)
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
    return _build_proceso_response(
        process_number,
        empresa,
        rows,
        _etiqueta_options_from_rows(rows),
        purchase_summary,
        source,
        conversion_meta,
    )


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
        logger.debug(
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


@router.get("/api/proceso/{process_number}/facturia-raw")
def get_proceso_facturia_raw(
    process_number: str,
    empresa: Optional[str] = None,
):
    """Solo en UI dev/staging: json_data crudo que mandó FacturIA (sin conversión)."""
    from facturia_matching.infra.config import PROCESS_SCHEMA, is_dev_ui
    from facturia_matching.persistence.back_check import get_process
    import json as _json

    if not is_dev_ui():
        raise HTTPException(status_code=404, detail="Not Found")

    def _load():
        process_row = get_process(process_number, empresa=empresa)
        if not process_row:
            raise HTTPException(
                status_code=404, detail=f"No se encontró el proceso {process_number}."
            )
        raw = process_row.get("json_data")
        if raw is None:
            raise HTTPException(status_code=404, detail="El proceso no tiene json_data.")
        try:
            if isinstance(raw, (dict, list)):
                payload = raw
            else:
                payload = _json.loads(raw)
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"json_data inválido: {e}"
            ) from e
        return {
            "ok": True,
            "process_number": process_number,
            "empresa": empresa,
            "process_schema": PROCESS_SCHEMA,
            "json_data": payload,
        }

    return _handle_process_load_errors(_load)


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
        else:
            filas, _, _ = parse_process_json(process_number, empresa=empresa)

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
        return _save_rows_and_respond(
            process_number, empresa, filas, purchase_summary, process_row
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
        return _save_rows_and_respond(
            process_number, empresa, rows, purchase_summary, process_row
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
        return _save_rows_and_respond(
            process_number, empresa, rows, purchase_summary, process_row
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
            except (TypeError, ValueError) as e:
                raise ProcessConversionError("payload.uom_id inválido") from e
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
