"""Amount parsing, formatting and comprobante-level tax helpers."""

import re
from typing import Any, Dict, List, Optional

from facturia_matching.core.constants import IVA_OPTIONS, IVA_SPECIAL_OPTIONS
from facturia_matching.infra.normalization import normalize, pick

_FAC_SUBTOTAL_KEYS = [
    "subtotal",
    "subtotal_sin_iva",
    "subtotal_sin_ivas",
    "base_imponible",
    "importe_neto",
    "total_sin_iva",
    "total_neto",
    "neto",
    "importe_total_neto",
    "monto_neto",
]
_FAC_IVA_MONTO_KEYS = [
    "iva_monto",
    "iva_total",
    "importe_iva",
    "total_iva",
    "monto_iva",
    "impuesto_iva",
]
_FAC_IVA_RATE_KEYS = ["iva_21", "iva_10_5", "iva_27", "iva_2_5", "iva_5"]
_FAC_PERCEPCION_AMOUNT_KEYS = ["percepcion_iibb", "percepcion_iva", "otros_tributos"]

_CSV_AMOUNT_ROW_KEYS = frozenset(
    {
        "invoice_line_ids/quantity",
        "invoice_line_ids/price_unit",
        "iva_monto",
        "otros_impuestos_monto",
    }
)


def normalize_iva_pct_value(raw: str) -> str:
    s = normalize(raw)
    if not s or s in IVA_SPECIAL_OPTIONS:
        return s
    if s in IVA_OPTIONS:
        return s
    cleaned = s.replace(" ", "")
    m = re.match(r"^(\d+)\.(\d+)$", cleaned)
    if m and "," not in cleaned:
        s = f"{m.group(1)},{m.group(2)}"
        if s in IVA_OPTIONS:
            return s
    return s


def iva_pct_for_odoo_tax_label(iva_pct: str) -> str:
    s = normalize(iva_pct)
    if re.match(r"^\d+,\d+$", s.replace(" ", "")):
        return s.replace(",", ".")
    return s


def build_tax_names(row: Dict[str, Any]) -> List[str]:
    names: List[str] = []

    iva_pct = normalize(row.get("iva_pct"))
    if iva_pct:
        if iva_pct in IVA_SPECIAL_OPTIONS:
            names.append(iva_pct)
        elif iva_pct != "0":
            names.append(f"IVA {iva_pct_for_odoo_tax_label(iva_pct)}%")

    for k, v in row.items():
        if not isinstance(k, str):
            continue
        if k == "otros_impuestos" or (k.startswith("otros_impuestos_") and not k.endswith("_monto")):
            n = normalize(v)
            if n:
                names.append(n)

    seen = set()
    out: List[str] = []
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        out.append(n)

    return out


def parse_amount(raw: Any) -> Optional[float]:
    s = normalize(raw)
    if not s or s.lower() == "nan":
        return None
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_amount_loose(raw: Any) -> Optional[float]:
    s = normalize(raw)
    if not s or s.lower() == "nan":
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts) >= 2 and all(p.isdigit() and len(p) == 3 for p in parts[1:]):
            s = "".join(parts)
    try:
        return float(s)
    except ValueError:
        return None


def format_amount_for_odoo_csv(raw: Any, *, money: bool = False) -> str:
    n = parse_amount_loose(raw)
    if n is None:
        return normalize(raw)
    if money:
        return f"{round(n, 2):.2f}"
    s = f"{round(n, 6):.6f}".rstrip("0").rstrip(".")
    return s or "0"


def is_otros_monto_row_key(key: str) -> bool:
    return key == "otros_impuestos_monto" or (
        key.startswith("otros_impuestos_") and key.endswith("_monto")
    )


def csv_export_cell(row: Dict[str, Any], key: str) -> str:
    val = row.get(key, "")
    if key in _CSV_AMOUNT_ROW_KEYS or is_otros_monto_row_key(key):
        return format_amount_for_odoo_csv(val, money=key != "invoice_line_ids/quantity")
    return "" if val is None else str(val)


def rows_prepared_for_odoo_csv(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = [dict(r) for r in rows if isinstance(r, dict)]
    header_keys = (
        "l10n_latam_document_number",
        "partner_id",
        "l10n_latam_document_type_id",
        "invoice_date",
        "invoice_date_due",
        "x_studio_category",
        "journal_id",
    )
    for i in range(1, len(out)):
        cur, prev = out[i], out[i - 1]
        same_inv = (
            cur.get("__comprobante_idx") is not None
            and cur.get("__comprobante_idx") == prev.get("__comprobante_idx")
        ) or (
            not normalize(cur.get("l10n_latam_document_number"))
            and normalize(prev.get("l10n_latam_document_number"))
        )
        if not same_inv:
            continue
        for k in header_keys:
            if not normalize(cur.get(k)) and normalize(prev.get(k)):
                cur[k] = prev[k]
    return out


def amount_to_str(val: float) -> str:
    if abs(val) < 1e-12:
        return ""
    return f"{round(val, 2):.2f}"


def resolve_fac_item_qty_price(item: Dict[str, Any]) -> tuple[str, str]:
    """
    Cantidad y precio unitario para fila UI desde ítem FacturIA.
    Si precio_unitario falta, deriva de subtotal_sin_iva ÷ cantidad.
    """
    if not isinstance(item, dict):
        return "", ""

    qty_raw = item.get("cantidad")
    price_raw = item.get("precio_unitario")

    qty = parse_amount(qty_raw)
    price = parse_amount(price_raw)

    line_net = parse_amount(item.get("subtotal_sin_iva"))
    if line_net is None:
        line_net = parse_amount(item.get("subtotal"))

    if price is not None and price != 0:
        q_out = "" if qty_raw is None and qty is None else str(qty_raw if qty_raw is not None else qty)
        if price_raw is not None:
            p_out = str(price_raw)
        else:
            p_out = amount_to_str(price) or str(price)
        return q_out, p_out

    if line_net is not None and line_net != 0:
        if qty is not None and qty != 0:
            unit = line_net / qty
            q_out = str(qty_raw) if qty_raw is not None else str(qty)
            return q_out, amount_to_str(unit) or f"{unit:.6f}".rstrip("0").rstrip(".")
        return "1", amount_to_str(line_net) or str(line_net)

    if qty_raw is not None:
        return str(qty_raw), "" if price_raw is None else str(price_raw)
    return "", "" if price_raw is None else str(price_raw)


def fac_header_amount_str(fac: Dict[str, Any], candidates: List[str]) -> str:
    if not isinstance(fac, dict):
        return ""
    return pick(fac, candidates)


_FAC_IVA_RATE_MAP = {
    "iva_21": "21",
    "iva_10_5": "10.5",
    "iva_27": "27",
    "iva_2_5": "2.5",
    "iva_5": "5",
}


def fac_iva_montos_dict(fac: Dict[str, Any]) -> Dict[str, str]:
    """Montos IVA por alícuota desde JSON FacturIA (iva_21, iva_10_5, …)."""
    if not isinstance(fac, dict):
        return {}
    out: Dict[str, str] = {}
    for fac_key, rate in _FAC_IVA_RATE_MAP.items():
        amt = parse_amount(pick(fac, [fac_key]))
        if amt is not None and amt > 0:
            out[rate] = amount_to_str(amt) or str(amt)
    return out


def fac_iva_monto_str(fac: Dict[str, Any]) -> str:
    if not isinstance(fac, dict):
        return ""
    total = 0.0
    found = False
    for key in _FAC_IVA_RATE_KEYS:
        amt = parse_amount(pick(fac, [key]))
        if amt is not None and amt > 0:
            total += amt
            found = True
    if found:
        return amount_to_str(total)
    return fac_header_amount_str(fac, _FAC_IVA_MONTO_KEYS)


def otros_impuesto_monto_key(n: int) -> str:
    return "otros_impuestos_monto" if n == 1 else f"otros_impuestos_{n}_monto"


def apply_fac_percepciones_to_row(fac: Dict[str, Any], row_out: Dict[str, Any]) -> None:
    if not isinstance(fac, dict) or not isinstance(row_out, dict):
        return
    percepciones: List[Dict[str, str]] = []
    slot = 1
    for fac_key in _FAC_PERCEPCION_AMOUNT_KEYS:
        amt = parse_amount(pick(fac, [fac_key]))
        if amt is None or amt <= 0:
            continue
        monto_key = otros_impuesto_monto_key(slot)
        monto_str = amount_to_str(amt)
        if not normalize(row_out.get(monto_key)):
            row_out[monto_key] = monto_str
        percepciones.append(
            {"amount_key": fac_key, "monto": monto_str, "ui_monto_key": monto_key}
        )
        slot += 1
    if percepciones:
        row_out["__fac_percepciones"] = percepciones
