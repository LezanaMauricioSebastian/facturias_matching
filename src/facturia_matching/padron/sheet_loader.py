"""Fetch and parse CSV/XLSX from URL, bytes, or disk (public Sheets + uploads + private SA)."""

import csv
import io
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import urllib.request

_cache: Dict[str, Dict[str, Any]] = {}

DEFAULT_TTL_SECONDS = 900  # 15 min


def _normalize_sheet_url(url: str) -> str:
    """Ensure the URL ends with pub?output=csv (handle edit URLs too)."""
    url = url.strip()
    if "pub?output=csv" in url or "pub?gid=" in url:
        return url
    if "/edit" in url:
        import re

        m = re.search(r"/spreadsheets/d/([^/]+)", url)
        gid_m = re.search(r"gid=(\d+)", url)
        if m and m.group(1) != "e":
            # Edit URLs with real spreadsheet id cannot be converted to /d/e/ publish URLs.
            # Caller should use spreadsheet_id + service account for private sheets.
            return url
        if m:
            sheet_id = m.group(1)
            base = f"https://docs.google.com/spreadsheets/d/e/{sheet_id}/pub?output=csv"
            if gid_m:
                base += f"&gid={gid_m.group(1)}"
            return base
    return url


def _cache_key_private(spreadsheet_id: str, gid: Optional[str]) -> str:
    return f"private:{spreadsheet_id}:gid={gid or ''}"


def parse_csv_text(raw: str) -> List[Dict[str, str]]:
    reader = csv.DictReader(io.StringIO(raw))
    return [{k: (v or "") for k, v in (row or {}).items()} for row in reader]


def parse_csv_bytes(data: bytes) -> List[Dict[str, str]]:
    return parse_csv_text(data.decode("utf-8-sig"))


def parse_xlsx_bytes(data: bytes) -> List[Dict[str, str]]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    header_row = next(rows_iter, None)
    if not header_row:
        return []
    headers: List[str] = []
    seen: Dict[str, int] = {}
    for i, h in enumerate(header_row):
        name = str(h).strip() if h is not None else ""
        if not name:
            name = f"_col_{i}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        headers.append(name)
    out: List[Dict[str, str]] = []
    for raw in rows_iter:
        if raw is None:
            continue
        row = {}
        empty = True
        for i, key in enumerate(headers):
            val = raw[i] if i < len(raw) and raw[i] is not None else ""
            s = str(val).strip()
            if s:
                empty = False
            row[key] = s
        if not empty:
            out.append(row)
    return out


def parse_file_bytes(data: bytes, filename: str = "") -> List[Dict[str, str]]:
    """Parse CSV or XLSX from uploaded bytes."""
    name = (filename or "").lower()
    if name.endswith(".xlsx") or name.endswith(".xlsm"):
        return parse_xlsx_bytes(data)
    if name.endswith(".xls"):
        raise ValueError("Formato .xls no soportado; usá .xlsx o .csv")
    if data[:2] == b"PK":
        return parse_xlsx_bytes(data)
    return parse_csv_bytes(data)


def parse_file_path(path: Union[str, Path]) -> List[Dict[str, str]]:
    p = Path(path)
    return parse_file_bytes(p.read_bytes(), p.name)


def fetch_csv(url: str, timeout: int = 15) -> List[Dict[str, str]]:
    """Download CSV from URL and return list of row dicts."""
    req = urllib.request.Request(url, headers={"User-Agent": "FacturIA/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8-sig")
    return parse_csv_text(raw)


def fetch_csv_raw(url: str, timeout: int = 15) -> List[List[str]]:
    """Download CSV and return raw rows (list of lists) including header."""
    req = urllib.request.Request(url, headers={"User-Agent": "FacturIA/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8-sig")
    return list(csv.reader(io.StringIO(raw)))


def fetch_sheet(
    url: str = "",
    ttl: int = DEFAULT_TTL_SECONDS,
    force: bool = False,
    spreadsheet_id: Optional[str] = None,
    gid: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Fetch with in-memory cache. Prefer private spreadsheet_id when configured."""
    sid = (spreadsheet_id or "").strip()
    if sid:
        from facturia_matching.padron.google_sheets import (
            fetch_spreadsheet_csv_text,
            service_account_configured,
        )

        if not service_account_configured():
            raise RuntimeError(
                "spreadsheet_id configurado pero falta GOOGLE_SERVICE_ACCOUNT_JSON"
            )
        key = _cache_key_private(sid, gid)
        now = time.time()
        cached = _cache.get(key)
        if cached and not force and (now - cached["ts"]) < ttl:
            return cached["rows"]
        raw = fetch_spreadsheet_csv_text(sid, gid=gid)
        rows = parse_csv_text(raw)
        _cache[key] = {"rows": rows, "ts": now}
        return rows

    if not (url or "").strip():
        return []
    norm_url = _normalize_sheet_url(url)
    now = time.time()
    cached = _cache.get(norm_url)
    if cached and not force and (now - cached["ts"]) < ttl:
        return cached["rows"]
    rows = fetch_csv(norm_url)
    _cache[norm_url] = {"rows": rows, "ts": now}
    return rows


def fetch_sheet_raw_rows(
    url: str = "",
    spreadsheet_id: Optional[str] = None,
    gid: Optional[str] = None,
    timeout: int = 15,
) -> List[List[str]]:
    """Download CSV as list-of-lists (incl. header) from private or public source."""
    sid = (spreadsheet_id or "").strip()
    if sid:
        from facturia_matching.padron.google_sheets import fetch_spreadsheet_csv_text

        raw = fetch_spreadsheet_csv_text(sid, gid=gid, timeout=timeout)
        return list(csv.reader(io.StringIO(raw)))
    if not (url or "").strip():
        return []
    return fetch_csv_raw(_normalize_sheet_url(url), timeout=timeout)


def extract_column_values(rows: List[Dict[str, str]], column: str) -> List[str]:
    """Extract unique non-empty values from a column."""
    seen: set = set()
    out: List[str] = []
    for r in rows:
        v = (r.get(column) or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def get_columns(rows: List[Dict[str, str]]) -> List[str]:
    """Return column names from parsed rows."""
    if not rows:
        return []
    return list(rows[0].keys())


def preview_rows(rows: List[Dict[str, str]], max_rows: int = 10) -> Dict[str, Any]:
    cols = get_columns(rows)
    return {
        "columns": cols,
        "row_count": len(rows),
        "sample": rows[:max_rows],
    }


def preview(
    url: str = "",
    max_rows: int = 10,
    spreadsheet_id: Optional[str] = None,
    gid: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch sheet and return columns + first N rows for UI preview."""
    rows = fetch_sheet(
        url=url, force=True, spreadsheet_id=spreadsheet_id, gid=gid
    )
    return preview_rows(rows, max_rows=max_rows)


def extract_category_map(
    url: str = "",
    timeout: int = 15,
    spreadsheet_id: Optional[str] = None,
    gid: Optional[str] = None,
) -> Dict[str, str]:
    """Build a Concepto → Categoría de Gasto lookup from unnamed columns 8 & 9.

    The sheet has unnamed columns after the main data that form a
    two-column lookup: col-index 8 = concepto, col-index 9 = categoría.
    """
    raw_rows = fetch_sheet_raw_rows(
        url=url, spreadsheet_id=spreadsheet_id, gid=gid, timeout=timeout
    )
    mapping: Dict[str, str] = {}
    for row in raw_rows[1:]:  # skip header
        if len(row) < 10:
            continue
        concepto = (row[8] or "").strip()
        categoria = (row[9] or "").strip()
        if concepto and categoria and concepto not in mapping:
            mapping[concepto] = categoria
    return mapping


def extract_category_map_from_rows(
    rows: List[Dict[str, str]],
    col_concepto: str,
    col_categoria: str,
) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    if not col_concepto or not col_categoria:
        return mapping
    for r in rows:
        c = (r.get(col_concepto) or "").strip()
        cat = (r.get(col_categoria) or "").strip()
        if c and cat and c not in mapping:
            mapping[c] = cat
    return mapping


def rows_to_proveedores(
    rows: List[Dict[str, str]],
    col_razon: str,
    col_fantasia: str = "",
    col_cuit: str = "",
) -> List[Dict[str, str]]:
    """Unique proveedor records from mapped columns."""
    out: List[Dict[str, str]] = []
    seen: set = set()
    for r in rows:
        razon = (r.get(col_razon) or "").strip() if col_razon else ""
        fantasia = (r.get(col_fantasia) or "").strip() if col_fantasia else ""
        cuit = (r.get(col_cuit) or "").strip() if col_cuit else ""
        if not razon and not fantasia and not cuit:
            continue
        key = (razon.lower(), fantasia.lower(), "".join(ch for ch in cuit if ch.isdigit()))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "razon_social": razon,
                "nombre_fantasia": fantasia,
                "cuit": cuit,
            }
        )
    return out


def rows_to_named(
    rows: List[Dict[str, str]],
    col_nombre: str,
) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen: set = set()
    for r in rows:
        name = (r.get(col_nombre) or "").strip() if col_nombre else ""
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append({"nombre": name})
    return out


def rows_to_productos(
    rows: List[Dict[str, str]],
    col_nombre: str,
    col_um: str = "",
) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen: set = set()
    for r in rows:
        name = (r.get(col_nombre) or "").strip() if col_nombre else ""
        um = (r.get(col_um) or "").strip() if col_um else ""
        if not name:
            continue
        key = (name.lower(), um.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"nombre": name, "unidad_medida": um})
    return out


def reset_cache() -> None:
    _cache.clear()
