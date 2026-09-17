"""Resolver rutas y URL de archivos originales de FacturIA (foto/PDF del proceso).

Los bytes viven en storage de FacturIA; en MySQL solo hay paths en json_data
(``archivo_original`` / ``factura.file_name``).
"""

from __future__ import annotations

import json
import mimetypes
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from facturia_matching.facturia.erp_import_webhook import resolve_facturia_base_url
from facturia_matching.infra.env import env_strip

# Env: plantilla con {base}, {path}, {path_encoded}, {process_id}, {process_number},
# {company_id}, {comprobante_idx}. Vacío = proxy deshabilitado.
_FILE_URL_TEMPLATE_ENV = "FACTURIA_FILE_URL_TEMPLATE"


def pick_archivo_raw(fac_wrap_json: Dict[str, Any]) -> str:
    """Extrae la ruta cruda desde el wrap ``facturas[i].json``."""
    if not isinstance(fac_wrap_json, dict):
        return ""
    raw = fac_wrap_json.get("archivo_original")
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    fac = fac_wrap_json.get("factura")
    if isinstance(fac, dict):
        fn = fac.get("file_name")
        if fn is not None and str(fn).strip():
            return str(fn).strip()
    return ""


def normalize_archivo_path(
    raw: str,
    *,
    company_id: Optional[Any] = None,
    process_number: Optional[Any] = None,
) -> str:
    """Normaliza path relativo; si es solo basename, antepone conversion/{cid}/{pn}/."""
    path = str(raw or "").strip().lstrip("/")
    if not path:
        return ""
    # Evitar path traversal
    if ".." in path.split("/"):
        return ""
    if "/" in path:
        return path
    cid = ""
    if company_id is not None and str(company_id).strip() != "":
        cid = str(company_id).strip()
    pn = ""
    if process_number is not None and str(process_number).strip() != "":
        pn = str(process_number).strip()
    if cid and pn:
        return f"conversion/{cid}/{pn}/{path}"
    return path


def archivo_paths_by_comprobante(
    json_data: Any,
    *,
    company_id: Optional[Any] = None,
    process_number: Optional[Any] = None,
) -> Dict[int, str]:
    """Mapa comprobante_idx (0-based) → path normalizado."""
    obj = json_data
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except Exception:
            return {}
    if not isinstance(obj, dict):
        return {}

    out: Dict[int, str] = {}
    idx = -1
    for fac_wrap in obj.get("facturas") or []:
        j = fac_wrap.get("json") if isinstance(fac_wrap, dict) else None
        if not isinstance(j, dict):
            continue
        idx += 1
        raw = pick_archivo_raw(j)
        path = normalize_archivo_path(
            raw, company_id=company_id, process_number=process_number
        )
        if path:
            out[idx] = path
    return out


def resolve_file_url_template() -> str:
    return env_strip(_FILE_URL_TEMPLATE_ENV)


def build_facturia_file_url(
    *,
    path: str,
    process_id: Optional[Any] = None,
    process_number: Optional[Any] = None,
    company_id: Optional[Any] = None,
    comprobante_idx: int = 0,
    process_schema: Optional[str] = None,
) -> Optional[str]:
    """Arma la URL de FacturIA desde FACTURIA_FILE_URL_TEMPLATE. None si no hay template."""
    template = resolve_file_url_template()
    if not template:
        return None
    base = resolve_facturia_base_url(process_schema)
    path_clean = str(path or "").lstrip("/")
    path_encoded = quote(path_clean, safe="/")
    return template.format(
        base=base.rstrip("/"),
        path=path_clean,
        path_encoded=path_encoded,
        process_id="" if process_id is None else str(process_id),
        process_number="" if process_number is None else str(process_number),
        company_id="" if company_id is None else str(company_id),
        comprobante_idx=str(int(comprobante_idx)),
    )


def guess_content_type(path: str) -> str:
    ctype, _ = mimetypes.guess_type(path)
    if ctype:
        return ctype
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    return "application/octet-stream"


def attach_facturia_archivo(
    rows: List[Dict[str, Any]],
    process_number: str,
    empresa: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Inyecta ``__fac_archivo`` en la 1ª fila de cada comprobante desde json_data."""
    if not rows:
        return rows

    from facturia_matching.persistence.back_check import get_process

    process_row = get_process(process_number, empresa=empresa)
    if not process_row or not process_row.get("json_data"):
        return rows

    paths = archivo_paths_by_comprobante(
        process_row["json_data"],
        company_id=process_row.get("company_id"),
        process_number=process_row.get("process_number") or process_number,
    )
    if not paths:
        return rows

    seen: set = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        idx = row.get("__comprobante_idx", 0)
        try:
            idx_i = int(idx)
        except (TypeError, ValueError):
            idx_i = 0
        if idx_i in seen:
            continue
        seen.add(idx_i)
        if str(row.get("__fac_archivo") or "").strip():
            continue
        path = paths.get(idx_i)
        if path:
            row["__fac_archivo"] = path
    return rows
