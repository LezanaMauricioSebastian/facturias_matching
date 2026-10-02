"""Esquema hardcodeado de la hoja Gastos de Pepe (cliente demo ?pepe=1).

Columnas alineadas al Sheet operativo (no a la pestaña Config del padrón).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

PEPE_GASTOS_COLUMNS: List[str] = [
    "Mes",
    "Sucursal",
    "Proveedor",
    "Concepto",
    "Fecha",
    "Monto",
    "Fecha de pago",
    "Mes de pago",
    "Forma de pago",
    "Categoría gasto",
    "Observación",
    "Estado de Deuda",
]

_MESES_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

_NUM_RE = re.compile(
    r"[-+]?\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?|"
    r"[-+]?\d+(?:,\d+)?|"
    r"[-+]?\d+(?:\.\d+)?"
)


# Mes en español minúsculas desde dd/mm/yyyy, d/m/yy o yyyy-mm-dd.
def month_name_es_from_date(date_str: str) -> str:
    """Extrae nombre de mes en español minúsculas desde dd/mm/yyyy, dd/mm/yy o yyyy-mm-dd."""
    s = (date_str or "").strip()
    if not s:
        return ""
    # dd/mm/yyyy o d/m/yyyy o dd/mm/yy
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$", s)
    if m:
        month = int(m.group(2))
        if 1 <= month <= 12:
            return _MESES_ES[month - 1]
        return ""
    # yyyy-mm-dd
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        month = int(m.group(2))
        if 1 <= month <= 12:
            return _MESES_ES[month - 1]
    return ""


def format_pepe_money(raw: Any) -> str:
    """Formato pepe: $99.000,00 (es-AR). Vacío si no hay número."""
    if raw is None:
        return ""
    if isinstance(raw, (int, float)):
        n = float(raw)
    else:
        s = str(raw).strip()
        if not s:
            return ""
        s = s.replace("$", "").replace(" ", "").strip()
        if not s:
            return ""
        # 1.234,56 → 1234.56 ; 1234.56 → 1234.56
        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(".", "").replace(",", ".")
        try:
            n = float(s)
        except ValueError:
            m = _NUM_RE.search(str(raw))
            if not m:
                return str(raw).strip()
            return format_pepe_money(m.group(0))
    neg = n < 0
    n = abs(n)
    ints, frac = f"{n:.2f}".split(".")
    groups: List[str] = []
    while ints:
        groups.insert(0, ints[-3:])
        ints = ints[:-3]
    body = ".".join(groups) + "," + frac
    return ("-$" if neg else "$") + body


def pepe_gastos_values(record: Dict[str, Any]) -> List[str]:
    """Valores en orden PEPE_GASTOS_COLUMNS desde un record excel_store / match."""
    fecha = str(record.get("fecha") or "").strip()
    fecha_pago = str(record.get("fecha_pago") or "").strip()
    mes = str(record.get("mes") or "").strip() or month_name_es_from_date(fecha)
    mes_pago = (
        str(record.get("mes_pago") or "").strip() or month_name_es_from_date(fecha_pago)
    )
    proveedor = (
        str(record.get("proveedor_match") or "").strip()
        or str(record.get("proveedor") or "").strip()
    )
    concepto = str(record.get("concepto") or "").strip()
    forma = (
        str(record.get("forma_pago_match") or "").strip()
        or str(record.get("forma_pago") or "").strip()
    )
    categoria = str(
        record.get("categoria_gasto") or record.get("categoria") or ""
    ).strip()
    estado = str(record.get("estado_deuda") or "").strip() or "Pagado"
    monto_raw = record.get("monto")
    if monto_raw is None or str(monto_raw).strip() == "":
        monto = ""
    else:
        monto = format_pepe_money(monto_raw)

    return [
        mes,
        str(record.get("sucursal") or "").strip(),
        proveedor,
        concepto,
        fecha,
        monto,
        fecha_pago,
        mes_pago,
        forma,
        categoria,
        str(record.get("observacion") or "").strip(),
        estado,
    ]


def pepe_gastos_rows(records: Sequence[Dict[str, Any]]) -> List[List[str]]:
    return [pepe_gastos_values(r) for r in records]
