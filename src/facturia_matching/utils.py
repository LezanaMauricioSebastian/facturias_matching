"""Shared string and date normalization helpers."""

import re
from datetime import date
from typing import Any, Dict, List

_DATE_DD_MM = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$")
_DATE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")


def normalize(s: Any) -> str:
    if s is None:
        return ""
    return " ".join(str(s).strip().split())


def pick(row: Dict[str, Any], candidates: List[str]) -> str:
    lower_map = {k.lower(): k for k in row.keys()}
    for cand in candidates:
        key = lower_map.get(cand.lower())
        if key is not None:
            v = row.get(key)
            if v is None:
                continue
            vs = normalize(v)
            if vs.lower() != "nan":
                return vs
    return ""


def normalize_date_ddmmyyyy(raw: Any) -> str:
    """Formato canónico de fechas en la UI: dd/mm/yyyy."""
    s = normalize(raw)
    if not s:
        return ""
    m = _DATE_DD_MM.match(s)
    if m:
        dd, mm, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = _DATE_ISO.match(s)
        if not m:
            return s
        yyyy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        d = date(yyyy, mm, dd)
    except ValueError:
        return s
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def doc_type_label(raw_tipo: str) -> str:
    """Normaliza tipo de comprobante a etiqueta (FACTURAS A / B / C u OC-X)."""
    tipo = normalize(raw_tipo).upper()
    if not tipo:
        return "OC-X"

    tipo = tipo.replace("FACTURAS", "FACTURA").strip()

    if tipo in {"A", "B", "C"}:
        tipo = f"FACTURA {tipo}"
    if tipo and not tipo.startswith("FACTURA"):
        tipo = f"FACTURA {tipo}"

    if tipo in {"FACTURA A", "FACTURA B", "FACTURA C"}:
        return tipo.replace("FACTURA", "FACTURAS", 1)
    return "OC-X"
