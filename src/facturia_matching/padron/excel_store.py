"""Simple JSON-file store for Excel-replacement invoice records (MVP)."""

import json
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from facturia_matching.infra.paths import PROJECT_ROOT

_STORE_PATH = PROJECT_ROOT / "data" / "facturas_excel.json"
_lock = threading.Lock()


def _ensure_dir() -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load() -> List[Dict[str, Any]]:
    if not _STORE_PATH.exists():
        return []
    with open(_STORE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(records: List[Dict[str, Any]]) -> None:
    _ensure_dir()
    with open(_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def list_records(
    company_id: Optional[int] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    with _lock:
        records = _load()
    if company_id is not None:
        records = [r for r in records if r.get("company_id") == company_id]
    return records[-limit:]


def get_record(record_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        for r in _load():
            if r.get("id") == record_id:
                return r
    return None


def add_record(data: Dict[str, Any]) -> Dict[str, Any]:
    record = {
        "id": str(uuid4()),
        "created_at": datetime.now().isoformat(),
        **data,
    }
    with _lock:
        records = _load()
        records.append(record)
        _save(records)
    return record


def update_record(record_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with _lock:
        records = _load()
        for r in records:
            if r.get("id") == record_id:
                r.update(data)
                r["updated_at"] = datetime.now().isoformat()
                _save(records)
                return r
    return None


def delete_record(record_id: str) -> bool:
    with _lock:
        records = _load()
        new = [r for r in records if r.get("id") != record_id]
        if len(new) == len(records):
            return False
        _save(new)
    return True


def add_many(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    now = datetime.now().isoformat()
    new_records = [
        {"id": str(uuid4()), "created_at": now, **d} for d in items
    ]
    with _lock:
        records = _load()
        records.extend(new_records)
        _save(records)
    return new_records
