"""Helpers compartidos para respuestas de /api/proceso/*."""

from typing import Optional

from fastapi import HTTPException

from facturia_matching.core.process import ProcessParseError, build_output_rows
from facturia_matching.odoo.env import current_odoo_profile
from facturia_matching.persistence.back_check import MySQLUnavailableError, ProcessTableError
from facturia_matching.persistence.process_conversions import ProcessConversionError


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
    except ProcessParseError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except ProcessConversionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
