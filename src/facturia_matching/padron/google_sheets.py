"""Authenticated Google Sheets fetch via service account (private share)."""

from __future__ import annotations

import json
import logging
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import urllib.error
import urllib.request

from facturia_matching.infra.config import GOOGLE_SERVICE_ACCOUNT_JSON

logger = logging.getLogger(__name__)

_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
)

_EDIT_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
_GID_RE = re.compile(r"[?&#]gid=(\d+)")

# Backoff on export 429 (docs.google.com rate limit is aggressive).
_EXPORT_RETRY_DELAYS_SEC = (0.8, 2.0, 4.0)

def service_account_configured() -> bool:
    raw = (GOOGLE_SERVICE_ACCOUNT_JSON or "").strip()
    return bool(raw)


def extract_spreadsheet_id(url_or_id: str) -> Optional[str]:
    """Extract spreadsheet id from edit URL or return bare id. Ignores /d/e/ publish ids."""
    s = (url_or_id or "").strip()
    if not s:
        return None
    if s.startswith("http") and "/d/e/" in s:
        return None
    m = _EDIT_ID_RE.search(s)
    if m:
        sid = m.group(1)
        if sid == "e":
            return None
        return sid
    if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", s) and not s.startswith("2PACX"):
        return s
    return None


def extract_gid(url: str) -> Optional[str]:
    m = _GID_RE.search(url or "")
    return m.group(1) if m else None


def friendly_sheet_access_error(exc: BaseException, spreadsheet_id: str = "") -> str:
    """User-facing message when private Sheet fetch fails (share / not found / etc.)."""
    msg = str(exc)
    email = service_account_email() or "la service account de FacturIA"
    sid_bit = f" (id={spreadsheet_id})" if spreadsheet_id else ""
    low = msg.lower()
    if "403" in msg or "permission" in low or "forbidden" in low or "access" in low and "denied" in low:
        return (
            f"El Sheet existe pero no está compartido como Lector a {email}. "
            f"En Google Sheets → Compartir, agregá ese mail.{sid_bit}"
        )
    if "404" in msg or "not found" in low:
        return f"No se encontró el Sheet{sid_bit}. Revisá el link / spreadsheet id."
    if "401" in msg or "unauthorized" in low:
        return (
            f"La service account no pudo autenticarse. "
            f"Revisá GOOGLE_SERVICE_ACCOUNT_JSON en el server.{sid_bit}"
        )
    if "429" in msg or "too many requests" in low or ("rate" in low and "limit" in low):
        return (
            "Google limitó las lecturas del Sheet (HTTP 429). "
            f"Esperá ~1 minuto y reintentá; si hay padrón en caché se reutiliza.{sid_bit}"
        )
    return f"No se pudo leer el Sheet{sid_bit}: {msg}"


def _load_sa_info() -> Dict[str, Any]:
    raw = (GOOGLE_SERVICE_ACCOUNT_JSON or "").strip()
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON no configurado")
    if raw.startswith("{"):
        return json.loads(raw)
    path = Path(raw).expanduser()
    if not path.is_file():
        raise RuntimeError(f"GOOGLE_SERVICE_ACCOUNT_JSON path no existe: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _credentials():
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request

    info = _load_sa_info()
    creds = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
    creds.refresh(Request())
    return creds


def service_account_email() -> Optional[str]:
    if not service_account_configured():
        return None
    try:
        return str(_load_sa_info().get("client_email") or "") or None
    except Exception:
        return None


def _bearer_token() -> str:
    creds = _credentials()
    if not creds.valid:
        from google.auth.transport.requests import Request

        creds.refresh(Request())
    if not creds.token:
        raise RuntimeError("No se pudo obtener token de service account")
    return str(creds.token)


def _sheets_api_get(path: str, timeout: int = 30) -> Dict[str, Any]:
    """Authenticated GET against Sheets API v4. ``path`` starts after /v4/."""
    token = _bearer_token()
    url = f"https://sheets.googleapis.com/v4/{path.lstrip('/')}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "FacturIA/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Sheets API HTTP {e.code}: {body}") from e


def fetch_spreadsheet_csv_text(
    spreadsheet_id: str,
    gid: Optional[str] = None,
    timeout: int = 30,
) -> str:
    """Export spreadsheet (or tab) as CSV using service-account Bearer token.

    Retries on HTTP 429 with short backoff (export endpoint is rate-limited).
    """
    sid = (spreadsheet_id or "").strip()
    if not sid:
        raise ValueError("spreadsheet_id vacío")
    url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv"
    if gid:
        url += f"&gid={gid}"

    attempts = (0.0,) + _EXPORT_RETRY_DELAYS_SEC
    last_err: Optional[BaseException] = None
    for attempt, delay in enumerate(attempts):
        if delay:
            time.sleep(delay)
        token = _bearer_token()
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "FacturIA/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8-sig")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            last_err = RuntimeError(
                f"Google Sheets export HTTP {e.code} para {sid}: {body}"
            )
            if e.code == 429 and attempt < len(attempts) - 1:
                logger.warning(
                    "Sheets export 429 sid=%s gid=%s attempt=%s; retry in %.1fs",
                    sid,
                    gid or "",
                    attempt + 1,
                    attempts[attempt + 1],
                )
                continue
            raise last_err from e
    assert last_err is not None
    raise last_err


def list_spreadsheet_sheets(
    spreadsheet_id: str,
    timeout: int = 30,
) -> Dict[str, Any]:
    """List tabs of a spreadsheet shared with the service account.

    Returns ``{spreadsheet_id, title, sheets: [{title, sheet_id, gid, index}]}``.
    ``sheet_id`` / ``gid`` are the same Google tab id (string gid for URLs).
    """
    sid = (spreadsheet_id or "").strip()
    if not sid:
        raise ValueError("spreadsheet_id vacío")
    if not service_account_configured():
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON no configurado")

    data = _sheets_api_get(
        f"spreadsheets/{sid}?fields=properties.title,sheets.properties(sheetId,title,index)",
        timeout=timeout,
    )
    sheets_out: List[Dict[str, Any]] = []
    for sh in data.get("sheets") or []:
        props = sh.get("properties") or {}
        sheet_id = props.get("sheetId")
        if sheet_id is None:
            continue
        sheets_out.append(
            {
                "title": str(props.get("title") or ""),
                "sheet_id": int(sheet_id),
                "gid": str(sheet_id),
                "index": int(props.get("index") or 0),
            }
        )
    sheets_out.sort(key=lambda s: s["index"])
    return {
        "spreadsheet_id": sid,
        "title": str((data.get("properties") or {}).get("title") or ""),
        "sheets": sheets_out,
    }


def _a1_sheet_range(sheet_title: str, cell_range: str = "1:1") -> str:
    """Build A1 range with quoted sheet title when needed."""
    title = sheet_title or ""
    if re.search(r"[^\w.]", title) or not title:
        safe = title.replace("'", "''")
        return f"'{safe}'!{cell_range}"
    return f"{title}!{cell_range}"


def _resolve_sheet_tab(
    spreadsheet_id: str,
    *,
    sheet_title: Optional[str] = None,
    sheet_gid: Optional[str] = None,
    timeout: int = 30,
) -> Tuple[str, str]:
    """Return ``(title, gid)`` for a tab; defaults to first sheet."""
    sid = (spreadsheet_id or "").strip()
    title = (sheet_title or "").strip()
    gid = (sheet_gid or "").strip() or None

    if not title:
        meta = list_spreadsheet_sheets(sid, timeout=timeout)
        sheets = meta["sheets"]
        if not sheets:
            raise ValueError("El spreadsheet no tiene hojas")
        if gid:
            match = next((s for s in sheets if s["gid"] == gid), None)
            if not match:
                raise ValueError(f"No hay hoja con gid={gid}")
            return match["title"], match["gid"]
        first = sheets[0]
        return first["title"], first["gid"]

    if gid:
        return title, gid

    try:
        meta = list_spreadsheet_sheets(sid, timeout=timeout)
        match = next((s for s in meta["sheets"] if s["title"] == title), None)
        if match:
            return title, match["gid"]
    except Exception:
        pass
    return title, ""


def fetch_first_row(
    spreadsheet_id: str,
    *,
    sheet_title: Optional[str] = None,
    sheet_gid: Optional[str] = None,
    skip_empty: bool = True,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Return values of row 1 (headers) for a tab (by title or gid).

    Resolves ``sheet_gid`` → title via ``list_spreadsheet_sheets`` when needed.
    """
    sid = (spreadsheet_id or "").strip()
    if not sid:
        raise ValueError("spreadsheet_id vacío")
    if not service_account_configured():
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON no configurado")

    title, resolved_gid = _resolve_sheet_tab(
        sid, sheet_title=sheet_title, sheet_gid=sheet_gid, timeout=timeout
    )

    from urllib.parse import quote

    a1 = _a1_sheet_range(title, "1:1")
    path = f"spreadsheets/{sid}/values/{quote(a1, safe='')}?majorDimension=ROWS"
    data = _sheets_api_get(path, timeout=timeout)
    rows = data.get("values") or []
    raw_vals: List[Any] = rows[0] if rows else []
    values: List[str] = []
    for v in raw_vals:
        s = str(v).strip() if v is not None else ""
        if skip_empty and not s:
            continue
        values.append(s)

    return {
        "spreadsheet_id": sid,
        "sheet_title": title,
        "sheet_gid": resolved_gid or "",
        "values": values,
        "count": len(values),
    }


# Back-compat alias (endpoint used to return column A; now first row).
fetch_first_column = fetch_first_row


def resolve_sheet_source(cfg: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str]]:
    """Return (mode, spreadsheet_id|url, gid).

    mode: 'private' | 'public' | ''
    """
    sid = (cfg.get("spreadsheet_id") or "").strip()
    gid = (cfg.get("sheet_gid") or "").strip() or None
    url = (cfg.get("sheet_url") or "").strip()
    if not sid and url:
        sid = extract_spreadsheet_id(url) or ""
        if not gid:
            gid = extract_gid(url)
    if sid and service_account_configured():
        return "private", sid, gid
    if url:
        return "public", url, gid
    if sid:
        return "private_unconfigured", sid, gid
    return "", None, None
