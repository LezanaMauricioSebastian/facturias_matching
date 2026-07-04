"""Clasificación de IVA por comprobante y totales (FacturIA vs líneas)."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from facturia_matching.core.amounts import amount_to_str, parse_amount_loose

_TAX_TOLERANCE = 0.02
_IVA_NO_CORRESPONDE = re.compile(r"no corresponde", re.I)


def _normalize(raw: Any) -> str:
    if raw is None:
        return ""
    return " ".join(str(raw).strip().split())


def iva_pct_to_rate(raw: Any) -> float:
    s = _normalize(raw).replace(",", ".")
    if not s or s == "0" or _IVA_NO_CORRESPONDE.search(s):
        return 0.0
    m = re.match(r"^(\d+(?:\.\d+)?)", s)
    if not m:
        return 0.0
    return float(m.group(1)) / 100.0


def line_base(row: Dict[str, Any]) -> float:
    qty = parse_amount_loose(row.get("invoice_line_ids/quantity"))
    price = parse_amount_loose(row.get("invoice_line_ids/price_unit"))
    if qty is None or price is None:
        return 0.0
    return float(qty) * float(price)


def line_iva_suggested(row: Dict[str, Any]) -> float:
    return line_base(row) * iva_pct_to_rate(row.get("iva_pct"))


def line_iva_monto(row: Dict[str, Any]) -> float:
    """Monto IVA de la fila: iva_monto guardado o sugerido (qty × precio × %)."""
    explicit = parse_amount_loose(row.get("iva_monto"))
    if explicit is not None and explicit > 0:
        return float(explicit)
    return line_iva_suggested(row)


def sum_line_iva_montos(group_rows: List[Dict[str, Any]]) -> float:
    return sum(line_iva_monto(r) for r in group_rows if isinstance(r, dict))


def sum_line_bases(group_rows: List[Dict[str, Any]]) -> float:
    return sum(line_base(r) for r in group_rows if isinstance(r, dict))


def sum_line_iva(group_rows: List[Dict[str, Any]]) -> float:
    return sum(line_iva_suggested(r) for r in group_rows if isinstance(r, dict))


def _first_row(group_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    for row in group_rows:
        if isinstance(row, dict):
            return row
    return {}


def fac_subtotal(group_rows: List[Dict[str, Any]]) -> Optional[float]:
    amt = parse_amount_loose(_first_row(group_rows).get("__fac_subtotal"))
    return amt if amt is not None and amt > 0 else None


def fac_iva_monto(group_rows: List[Dict[str, Any]]) -> Optional[float]:
    first = _first_row(group_rows)
    amt = parse_amount_loose(first.get("__fac_iva_monto"))
    if amt is not None and amt > 0:
        return amt
    legacy = parse_amount_loose(first.get("iva_monto"))
    if legacy is not None and legacy > 0 and first.get("__iva_monto_manual"):
        return legacy
    return None


def _iva_rate_key_from_pct(raw: Any) -> Optional[str]:
    rate = iva_pct_to_rate(raw) * 100
    if rate <= 0:
        return None
    if abs(rate - round(rate)) < 1e-9:
        return str(int(round(rate)))
    return str(rate).rstrip("0").rstrip(".")


def _explicit_fac_iva_montos(group_rows: List[Dict[str, Any]]) -> Dict[str, float]:
    """Montos desde __fac_iva_montos JSON (sin inferencia por línea)."""
    first = _first_row(group_rows)
    raw = first.get("__fac_iva_montos")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            return {}
        out: Dict[str, float] = {}
        for k, v in parsed.items():
            if str(k) == "_total":
                continue
            amt = _parse_amount_key(v)
            if amt is not None and amt > 0:
                out[str(k)] = amt
        return out
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def fac_iva_montos(group_rows: List[Dict[str, Any]]) -> Dict[str, float]:
    """Montos IVA por alícuota desde __fac_iva_montos o sugeridos por línea."""
    explicit = _explicit_fac_iva_montos(group_rows)
    header = fac_iva_monto(group_rows)
    mode = classify_comprobante_tax_mode(group_rows)

    if explicit and header is not None and header > 0:
        explicit_sum = round(sum(explicit.values()), 2)
        tol = max(_TAX_TOLERANCE, explicit_sum * 0.001)
        if abs(explicit_sum - header) > tol and mode in ("header", "mixed"):
            if len(explicit) == 1:
                key = next(iter(explicit))
                return {key: round(header, 2)}

    if explicit:
        return explicit
    suggested: Dict[str, float] = defaultdict(float)
    for row in group_rows:
        if not isinstance(row, dict) or not _line_has_content(row):
            continue
        key = _iva_rate_key_from_pct(row.get("iva_pct"))
        if not key:
            continue
        suggested[key] += line_iva_suggested(row)

    mode = classify_comprobante_tax_mode(group_rows)
    header = fac_iva_monto(group_rows)

    if mode == "header" and header is not None and header > 0:
        if len(suggested) == 1:
            key = next(iter(suggested))
            return {key: round(header, 2)}
        return {"21": round(header, 2)}

    if suggested:
        return {k: round(v, 2) for k, v in suggested.items()}

    if header is not None and header > 0:
        keys = list(suggested.keys())
        fallback = keys[0] if keys else "21"
        return {fallback: round(header, 2)}
    return {}


def _write_fac_iva_montos_from_line_amounts(group_rows: List[Dict[str, Any]]) -> None:
    montos: Dict[str, float] = defaultdict(float)
    for row in group_rows:
        if not isinstance(row, dict) or not _line_has_content(row):
            continue
        key = _iva_rate_key_from_pct(row.get("iva_pct"))
        if not key:
            continue
        montos[key] += line_iva_monto(row)
    if not montos:
        return
    first = _first_row(group_rows)
    clean = {
        k: (amount_to_str(v) or str(round(v, 2)))
        for k, v in montos.items()
        if v > 0
    }
    if not clean:
        return
    first["__fac_iva_montos"] = json.dumps(clean, ensure_ascii=False)
    total = sum(montos.values())
    first["__fac_iva_monto"] = amount_to_str(total) or str(round(total, 2))


def _lines_with_iva_rate(group_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    content = [r for r in group_rows if isinstance(r, dict) and _line_has_content(r)]
    return [r for r in content if iva_pct_to_rate(r.get("iva_pct")) > 0]


def _line_iva_differs_from_header(group_rows: List[Dict[str, Any]]) -> bool:
    """True cuando el IVA por fila no coincide con el encabezado FacturIA guardado."""
    lines_with_rate = _lines_with_iva_rate(group_rows)
    if not lines_with_rate:
        return False
    line_sum = sum_line_iva_montos(group_rows)
    if line_sum <= 0:
        return False
    if any(isinstance(r, dict) and r.get("__iva_monto_manual") for r in lines_with_rate):
        return True
    header_iva = fac_iva_monto(group_rows) or 0.0
    if header_iva <= 0:
        return True
    tol = max(_TAX_TOLERANCE, max(line_sum, header_iva) * 0.001)
    return abs(line_sum - header_iva) > tol


def reconcile_fac_iva_for_import(group_rows: List[Dict[str, Any]]) -> None:
    """
    Import Odoo: alinea __fac_iva_monto(s) con iva_monto de filas cuando difieren
    del encabezado (p. ej. usuario editó la columna pero el JSON quedó viejo).

    En header/mixed el pie FacturIA es la fuente de verdad para sobreescribir Odoo.
    """
    mode = classify_comprobante_tax_mode(group_rows)
    line_manual = any(
        isinstance(r, dict) and r.get("__iva_monto_manual") for r in group_rows
    )
    if line_manual:
        _write_fac_iva_montos_from_line_amounts(group_rows)
        return
    if mode in ("header", "mixed"):
        if _explicit_fac_iva_montos(group_rows) or fac_iva_monto(group_rows):
            return
    if not _lines_with_iva_rate(group_rows):
        return
    if _line_iva_differs_from_header(group_rows) or mode == "line":
        _write_fac_iva_montos_from_line_amounts(group_rows)


def sync_fac_iva_montos_from_lines(group_rows: List[Dict[str, Any]]) -> None:
    """Alinea __fac_iva_montos con montos por línea (UI / autosave)."""
    if classify_comprobante_tax_mode(group_rows) != "line":
        return
    _write_fac_iva_montos_from_line_amounts(group_rows)


def _parse_amount_key(raw: Any) -> Optional[float]:
    if isinstance(raw, (int, float)):
        return float(raw)
    return parse_amount_loose(raw)


def sum_otros_impuestos(group_rows: List[Dict[str, Any]]) -> float:
    total = 0.0
    for row in group_rows:
        if not isinstance(row, dict):
            continue
        amt = parse_amount_loose(row.get("otros_impuestos_monto"))
        if amt:
            total += amt
        for n in range(2, 21):
            extra = parse_amount_loose(row.get(f"otros_impuestos_{n}_monto"))
            if extra:
                total += extra
    return total


def all_lines_have_iva_pct(group_rows: List[Dict[str, Any]]) -> bool:
    content = [r for r in group_rows if isinstance(r, dict) and _line_has_content(r)]
    if not content:
        return False
    return all(iva_pct_to_rate(r.get("iva_pct")) > 0 for r in content)


def _line_has_content(row: Dict[str, Any]) -> bool:
    return bool(
        _normalize(row.get("invoice_line_ids/name"))
        or parse_amount_loose(row.get("invoice_line_ids/price_unit")) is not None
        or parse_amount_loose(row.get("invoice_line_ids/quantity")) is not None
    )


def _group_rows_by_comprobante(rows: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    groups: Dict[Any, List[Dict[str, Any]]] = {}
    order: List[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = row.get("__comprobante_idx", 0)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    return [groups[k] for k in order]


def sanitize_inflated_line_amounts(rows: List[Dict[str, Any]]) -> int:
    """
    Corrige cantidad × precio cuando desborda el subtotal FacturIA
    (p. ej. código de producto interpretado como cantidad).
    """
    fixed = 0
    for group in _group_rows_by_comprobante(rows):
        base_fac = fac_subtotal(group)
        if base_fac is None or base_fac <= 0:
            continue
        cap = base_fac * 1.001 + _TAX_TOLERANCE
        for row in group:
            qty = parse_amount_loose(row.get("invoice_line_ids/quantity"))
            price = parse_amount_loose(row.get("invoice_line_ids/price_unit"))
            if qty is None or price is None or qty <= 0 or price <= 0:
                continue
            if qty * price <= cap:
                continue
            if price <= cap:
                row["invoice_line_ids/quantity"] = "1"
                fixed += 1
            elif qty <= cap:
                row["invoice_line_ids/price_unit"] = amount_to_str(base_fac / qty)
                fixed += 1
            else:
                row["invoice_line_ids/quantity"] = ""
                row["invoice_line_ids/price_unit"] = ""
                fixed += 1
    return fixed


def classify_comprobante_tax_mode(group_rows: List[Dict[str, Any]]) -> str:
    """Return 'line', 'header', or 'mixed'."""
    if not group_rows:
        return "header"
    header_iva = fac_iva_monto(group_rows) or 0.0
    line_iva_sum = sum_line_iva_montos(group_rows)
    content = [r for r in group_rows if isinstance(r, dict) and _line_has_content(r)]
    lines_with_rate = [r for r in content if iva_pct_to_rate(r.get("iva_pct")) > 0]

    if header_iva <= 0 and not lines_with_rate:
        return "header"

    if (
        lines_with_rate
        and len(lines_with_rate) == len(content)
        and header_iva > 0
        and abs(line_iva_sum - header_iva) <= max(_TAX_TOLERANCE, header_iva * 0.001)
    ):
        return "line"

    if header_iva > 0 and not lines_with_rate:
        return "header"

    if header_iva > 0 and lines_with_rate:
        if abs(line_iva_sum - header_iva) <= max(_TAX_TOLERANCE, header_iva * 0.001):
            return "line"
        # Una sola línea: encabezado FacturIA si el % no cierra; salvo IVA editado en la fila.
        if len(content) == 1:
            row = lines_with_rate[0]
            explicit = parse_amount_loose(row.get("iva_monto"))
            sug = line_iva_suggested(row)
            if row.get("__iva_monto_manual"):
                return "line"
            if (
                explicit is not None
                and explicit > 0
                and sug > 0
                and abs(explicit - sug) > max(_TAX_TOLERANCE, sug * 0.001)
            ):
                return "line"
            return "header"
        return "mixed"

    if lines_with_rate and header_iva <= 0:
        return "line"

    return "header"


def compute_comprobante_totals(group_rows: List[Dict[str, Any]], mode: Optional[str] = None) -> Dict[str, Any]:
    mode = mode or classify_comprobante_tax_mode(group_rows)
    base_lines = sum_line_bases(group_rows)
    base_fac = fac_subtotal(group_rows)
    iva_fac = fac_iva_monto(group_rows)
    line_iva_sum = sum_line_iva(group_rows)
    otros = sum_otros_impuestos(group_rows)

    explicit_montos = _explicit_fac_iva_montos(group_rows)
    if mode == "line":
        iva_odoo = round(sum_line_iva_montos(group_rows), 2)
    elif explicit_montos:
        iva_odoo = round(sum(explicit_montos.values()), 2)
    elif iva_fac is not None and iva_fac > 0:
        iva_odoo = iva_fac
    else:
        iva_odoo = iva_fac or 0.0

    if mode == "header" and base_fac is not None:
        base_odoo = base_fac
    else:
        base_odoo = base_lines
    total_fac = (base_fac if base_fac is not None else base_lines) + (iva_fac or 0.0) + otros
    total_odoo = base_odoo + iva_odoo + otros

    warnings: List[str] = []
    if base_fac is not None and mode != "header" and abs(base_fac - base_lines) > max(_TAX_TOLERANCE, base_fac * 0.001):
        warnings.append(
            f"Base FacturIA ({base_fac:.2f}) ≠ suma de líneas ({base_lines:.2f})"
        )
    if iva_fac is not None and mode == "mixed":
        warnings.append(
            f"IVA por línea ({line_iva_sum:.2f}) ≠ total FacturIA ({iva_fac:.2f})"
        )

    return {
        "mode": mode,
        "base_lines": round(base_lines, 2),
        "base_fac": round(base_fac, 2) if base_fac is not None else None,
        "base_odoo": round(base_odoo, 2),
        "iva_fac": round(iva_fac, 2) if iva_fac is not None else None,
        "iva_odoo": round(iva_odoo, 2),
        "line_iva_sum": round(line_iva_sum, 2),
        "otros": round(otros, 2),
        "total_fac": round(total_fac, 2),
        "total_odoo": round(total_odoo, 2),
        "warnings": warnings,
    }
