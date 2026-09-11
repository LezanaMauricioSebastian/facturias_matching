"""Map FacturIA process json_data → InvoiceInput-shaped dicts for Excel padron matching."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def _pick(d: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def factura_to_invoice_input(
    fac: Dict[str, Any],
    *,
    company_id: int = 0,
) -> Dict[str, Any]:
    """Convert one FacturIA `factura` object into fields for InvoiceInput / _match_invoice."""
    prov = fac.get("proveedor") if isinstance(fac.get("proveedor"), dict) else {}
    proveedor = _pick(prov, "razon_social", "nombre", "nombre_fantasia")
    cuit = _pick(prov, "cuit", "cuit_cuil", "documento")

    items = fac.get("items") if isinstance(fac.get("items"), list) else []
    lineas: List[str] = []
    unidades_medida: List[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        desc = _pick(it, "descripcion", "nombre", "detalle", "producto")
        if not desc:
            continue
        lineas.append(desc)
        unidades_medida.append(_pick(it, "unidad_medida", "um", "uom", "unidad"))

    forma_pago = _pick(
        fac,
        "forma_de_pago",
        "forma_pago",
        "medio_de_pago",
        "metodo_de_pago",
        "condicion_pago",
    )
    tipo = _pick(fac, "tipo_comprobante", "tipo")
    # Prefer letter-like types (A/B/C/M) when present in longer labels.
    if tipo and len(tipo) > 1:
        for letter in ("A", "B", "C", "M"):
            if letter in tipo.upper().split() or tipo.upper().endswith(f" {letter}"):
                tipo = letter
                break

    return {
        "mes": _pick(fac, "mes", "periodo"),
        "sucursal": _pick(fac, "sucursal", "local", "branch"),
        "proveedor": proveedor,
        "cuit": cuit,
        "lineas": lineas,
        "unidades_medida": unidades_medida,
        "forma_pago": forma_pago,
        "estado_deuda": _pick(fac, "estado_deuda", "estado", "estado_pago"),
        "tipo_comprobante": tipo,
        "company_id": company_id,
    }


def parse_process_json_data(json_data: Any) -> List[Dict[str, Any]]:
    """Return list of raw `factura` dicts from process json_data (str or dict)."""
    obj = json_data
    if obj is None:
        return []
    if isinstance(obj, (bytes, bytearray)):
        obj = obj.decode("utf-8")
    if isinstance(obj, str):
        obj = json.loads(obj) if obj.strip() else {}
    if isinstance(obj, str):
        obj = json.loads(obj) if obj.strip() else {}
    if not isinstance(obj, dict):
        return []

    out: List[Dict[str, Any]] = []
    for fac_wrap in obj.get("facturas") or []:
        if not isinstance(fac_wrap, dict):
            continue
        j = fac_wrap.get("json")
        if not isinstance(j, dict):
            continue
        fac = j.get("factura") if isinstance(j.get("factura"), dict) else None
        if isinstance(fac, dict):
            out.append(fac)
    return out


def invoices_from_process_row(
    process_row: Dict[str, Any],
    *,
    company_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    cid = company_id
    if cid is None:
        raw = process_row.get("company_id")
        if raw is not None and str(raw).strip().isdigit():
            cid = int(raw)
        else:
            cid = 0
    facturas = parse_process_json_data(process_row.get("json_data"))
    return [factura_to_invoice_input(fac, company_id=int(cid or 0)) for fac in facturas]
