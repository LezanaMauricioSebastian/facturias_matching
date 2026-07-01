"""Carga escenarios compartidos para tests de IVA (Python y JS)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

_FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures" / "tax_scenarios.json"


def load_tax_scenarios() -> List[Dict[str, Any]]:
    data = json.loads(_FIXTURES_PATH.read_text(encoding="utf-8"))
    return list(data.get("scenarios") or [])


def scenario_by_id(scenario_id: str) -> Dict[str, Any]:
    for s in load_tax_scenarios():
        if s.get("id") == scenario_id:
            return s
    raise KeyError(scenario_id)
