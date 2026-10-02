"""Resolver rutas y archivos originales de FacturIA (foto/PDF del proceso).

Los bytes viven en GCS ``gs://facturias-sudata`` (o HTTP vía template opcional).
En MySQL solo hay paths en json_data (``archivo_original`` / ``factura.file_name``).

Estructura del bucket:
- prod:    ``conversion/{company_id}/{process_number}/{file}``
- staging: ``conversion-staging/{company_id}/{process_number}/{file}``

Los paths en json_data suelen usar el prefijo lógico ``conversion/…``; en staging
se reescriben a ``conversion-staging/…``. Si el basename no matchea, también se
prueba espacio ↔ ``_`` (FacturIA a veces guarda uno y el blob usa el otro).
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from facturia_matching.facturia.erp_import_webhook import resolve_facturia_base_url
from facturia_matching.infra.config import PROCESS_SCHEMA, resolve_process_schema
from facturia_matching.infra.env import env_strip

logger = logging.getLogger(__name__)

# Env: plantilla HTTP opcional (fallback). Placeholders: {base}, {path}, {path_encoded}, …
_FILE_URL_TEMPLATE_ENV = "FACTURIA_FILE_URL_TEMPLATE"
_GCS_BUCKET_ENV = "FACTURIA_GCS_BUCKET"
_DEFAULT_GCS_BUCKET = "facturias-sudata"


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


def resolve_gcs_bucket() -> str:
    return env_strip(_GCS_BUCKET_ENV) or _DEFAULT_GCS_BUCKET


def is_staging_process_schema(process_schema: Optional[str] = None) -> bool:
    schema = resolve_process_schema(process_schema or PROCESS_SCHEMA)
    return "staging" in (schema or "").lower()


def _basename_space_underscore_variants(basename: str) -> List[str]:
    """Variantes de basename por espacio ↔ ``_`` (FacturIA a veces usa uno u otro).

    Ej.: ``PATRICIO_ALEANDRI.pdf`` ↔ ``PATRICIO ALEANDRI.pdf``.
    """
    name = str(basename or "")
    if not name:
        return []
    out: List[str] = [name]
    if "_" in name:
        out.append(name.replace("_", " "))
    if " " in name:
        out.append(name.replace(" ", "_"))
    seen: set = set()
    deduped: List[str] = []
    for n in out:
        if n and n not in seen:
            seen.add(n)
            deduped.append(n)
    return deduped


def to_gcs_blob_candidates(
    logical_path: str,
    *,
    process_schema: Optional[str] = None,
) -> List[str]:
    """Candidatos de object name en el bucket (staging primero si aplica).

    Además del path exacto, prueba basename con espacio↔underscore (mismatches
    frecuentes entre ``json_data`` y el objeto real en GCS).
    """
    path = str(logical_path or "").strip().lstrip("/")
    if not path or ".." in path.split("/"):
        return []

    staging = is_staging_process_schema(process_schema)
    rest = path
    for root in ("conversion-staging/", "conversion/"):
        if rest.startswith(root):
            rest = rest[len(root) :]
            break

    primary_root = "conversion-staging" if staging else "conversion"
    secondary_root = "conversion" if staging else "conversion-staging"

    # Prefijos a probar (prod/staging) + path crudo si aporta algo distinto.
    prefix_bases = [f"{primary_root}/{rest}", f"{secondary_root}/{rest}"]
    if path not in prefix_bases:
        prefix_bases.append(path)

    # Expandir cada base con variantes del basename (espacio ↔ _).
    candidates: List[str] = []
    for base in prefix_bases:
        if "/" in base:
            dirname, basename = base.rsplit("/", 1)
            for bn in _basename_space_underscore_variants(basename):
                candidates.append(f"{dirname}/{bn}")
        else:
            candidates.extend(_basename_space_underscore_variants(base))

    seen: set = set()
    out: List[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def build_facturia_file_url(
    *,
    path: str,
    process_id: Optional[Any] = None,
    process_number: Optional[Any] = None,
    company_id: Optional[Any] = None,
    comprobante_idx: int = 0,
    process_schema: Optional[str] = None,
) -> Optional[str]:
    """Arma la URL HTTP de FacturIA desde FACTURIA_FILE_URL_TEMPLATE. None si no hay template."""
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


def _gcs_client():
    """Cliente GCS vía ADC (Cloud Run compute SA / gcloud auth).

    No usa ``GOOGLE_SERVICE_ACCOUNT_JSON`` (esa SA es del padrón Sheets y suele
    no tener acceso al bucket ``facturias-sudata``).
    """
    from google.cloud import storage

    return storage.Client()


def fetch_archivo_bytes_from_gcs(
    logical_path: str,
    *,
    process_schema: Optional[str] = None,
    bucket_name: Optional[str] = None,
) -> Tuple[bytes, str, str]:
    """
    Descarga el archivo desde GCS.

    Returns (content_bytes, content_type, blob_name).
    Raises FileNotFoundError si no existe; RuntimeError en otros fallos.
    """
    bucket_name = (bucket_name or resolve_gcs_bucket()).strip()
    candidates = to_gcs_blob_candidates(logical_path, process_schema=process_schema)
    if not candidates:
        raise FileNotFoundError("Ruta de archivo inválida.")

    try:
        client = _gcs_client()
        bucket = client.bucket(bucket_name)
    except Exception as e:
        raise RuntimeError(f"No se pudo conectar a GCS ({bucket_name}): {e}") from e

    last_err: Optional[BaseException] = None
    for blob_name in candidates:
        try:
            blob = bucket.blob(blob_name)
            if not blob.exists():
                continue
            data = blob.download_as_bytes()
            ctype = blob.content_type or guess_content_type(blob_name)
            return data, ctype, blob_name
        except FileNotFoundError:
            continue
        except Exception as e:
            last_err = e
            logger.warning("GCS read failed gs://%s/%s: %s", bucket_name, blob_name, e)
            continue

    if last_err is not None:
        raise RuntimeError(f"Error leyendo gs://{bucket_name}/…: {last_err}") from last_err
    raise FileNotFoundError(
        f"Archivo no encontrado en gs://{bucket_name}/ "
        f"(probados: {', '.join(candidates)})"
    )


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
