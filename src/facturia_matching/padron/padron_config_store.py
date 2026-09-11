"""JSON config + uploaded padron files under data/padrones/."""

import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from facturia_matching.infra.paths import PROJECT_ROOT

PADRON_KINDS = ("proveedores", "productos", "formas_pago", "conceptos")

_ROOT = PROJECT_ROOT / "data" / "padrones"
_CONFIG_PATH = _ROOT / "config.json"
_FILES_DIR = _ROOT / "files"
_lock = threading.Lock()

DEFAULT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1klqwF-8c-xnXvHB1GJ2f8x9vOoJi4-PB-HavIh1wULA/edit"
)

DEFAULT_MAPPING = {
    "proveedores": {
        "razon_social": "Proveedores",
        "nombre_fantasia": "",
        "cuit": "",
    },
    "productos": {"nombre": "", "unidad_medida": ""},
    "formas_pago": {"nombre": "Forma de Pago"},
    "conceptos": {"nombre": "Conceptos", "categoria": ""},
}


def default_config(company_id: int = 0) -> Dict[str, Any]:
    return {
        "company_id": company_id,
        "sheet_url": DEFAULT_SHEET_URL,
        "spreadsheet_id": "1klqwF-8c-xnXvHB1GJ2f8x9vOoJi4-PB-HavIh1wULA",
        "sheet_gid": "",
        "refresh_minutes": 2,
        "mapping": {k: dict(v) for k, v in DEFAULT_MAPPING.items()},
        "files": {},
    }


def _ensure_dirs() -> None:
    _ROOT.mkdir(parents=True, exist_ok=True)
    _FILES_DIR.mkdir(parents=True, exist_ok=True)


def _load_all() -> Dict[str, Any]:
    if not _CONFIG_PATH.exists():
        return {}
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_all(data: Dict[str, Any]) -> None:
    _ensure_dirs()
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_config(company_id: int = 0) -> Dict[str, Any]:
    key = str(company_id)
    with _lock:
        all_cfg = _load_all()
        cfg = all_cfg.get(key)
        if not cfg:
            return default_config(company_id)
        merged = default_config(company_id)
        merged.update(cfg)
        mapping = dict(DEFAULT_MAPPING)
        for kind, cols in (cfg.get("mapping") or {}).items():
            mapping[kind] = {**mapping.get(kind, {}), **(cols or {})}
        merged["mapping"] = mapping
        merged["files"] = cfg.get("files") or {}
        return merged


def save_config(company_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
    key = str(company_id)
    with _lock:
        all_cfg = _load_all()
        cfg = all_cfg.get(key) or default_config(company_id)
        if "sheet_url" in updates and updates["sheet_url"] is not None:
            cfg["sheet_url"] = updates["sheet_url"]
            from facturia_matching.padron.google_sheets import (
                extract_gid,
                extract_spreadsheet_id,
            )

            sid = extract_spreadsheet_id(str(updates["sheet_url"]))
            if sid and not (updates.get("spreadsheet_id") or cfg.get("spreadsheet_id")):
                cfg["spreadsheet_id"] = sid
            gid = extract_gid(str(updates["sheet_url"]))
            if gid and not (updates.get("sheet_gid") or cfg.get("sheet_gid")):
                cfg["sheet_gid"] = gid
        if "spreadsheet_id" in updates and updates["spreadsheet_id"] is not None:
            cfg["spreadsheet_id"] = str(updates["spreadsheet_id"]).strip()
        if "sheet_gid" in updates and updates["sheet_gid"] is not None:
            cfg["sheet_gid"] = str(updates["sheet_gid"]).strip()
        if "refresh_minutes" in updates and updates["refresh_minutes"] is not None:
            cfg["refresh_minutes"] = int(updates["refresh_minutes"])
        if updates.get("mapping"):
            mapping = cfg.get("mapping") or {k: dict(v) for k, v in DEFAULT_MAPPING.items()}
            for kind, cols in updates["mapping"].items():
                mapping[kind] = {**(mapping.get(kind) or {}), **(cols or {})}
            cfg["mapping"] = mapping
        if "files" in updates and updates["files"] is not None:
            cfg["files"] = updates["files"]
        cfg["company_id"] = company_id
        all_cfg[key] = cfg
        _save_all(all_cfg)
    return get_config(company_id)


def save_upload(company_id: int, kind: str, filename: str, data: bytes) -> str:
    if kind not in PADRON_KINDS:
        raise ValueError(f"kind must be one of {PADRON_KINDS}")
    ext = Path(filename).suffix.lower() or ".csv"
    if ext not in {".csv", ".xlsx", ".xlsm"}:
        ext = ".csv"
    rel = f"{company_id}/{kind}{ext}"
    dest = _FILES_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    cfg = get_config(company_id)
    files = dict(cfg.get("files") or {})
    files[kind] = {"path": rel, "filename": filename}
    save_config(company_id, {"files": files})
    return str(dest)


def uploaded_path(company_id: int, kind: str) -> Optional[Path]:
    cfg = get_config(company_id)
    meta = (cfg.get("files") or {}).get(kind)
    if not meta:
        return None
    p = _FILES_DIR / meta["path"]
    return p if p.exists() else None
