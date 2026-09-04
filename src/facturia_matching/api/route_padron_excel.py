"""API routes for Excel/Sheets padron management, matching, and invoice CRUD."""

import csv
import io
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from facturia_matching.padron import excel_store
from facturia_matching.padron import padron_config_store as cfg_store
from facturia_matching.padron.catalog_excel import invalidate_data_cache, load_padron
from facturia_matching.padron.excel import (
    match_bulk,
    match_forma_pago,
    match_one,
    match_producto,
    match_proveedor_excel,
)
from facturia_matching.padron.sheet_loader import (
    parse_file_bytes,
    preview as sheet_preview,
    preview_rows,
    reset_cache,
)

router = APIRouter(prefix="/api/padron-excel", tags=["padron-excel"])

PADRON_KINDS = cfg_store.PADRON_KINDS


class PreviewRequest(BaseModel):
    url: str = cfg_store.DEFAULT_SHEET_URL
    max_rows: int = 10


class PadronExcelConfigIn(BaseModel):
    company_id: int = 0
    sheet_url: Optional[str] = None
    refresh_minutes: Optional[int] = None
    mapping: Optional[Dict[str, Dict[str, str]]] = None


class MatchRequest(BaseModel):
    field: str
    queries: List[str]
    min_score: float = 72.0
    cuit: Optional[str] = None
    unidades_medida: Optional[List[str]] = None
    company_id: int = 0


class InvoiceInput(BaseModel):
    mes: str = ""
    sucursal: str = ""
    proveedor: str
    cuit: str = ""
    lineas: List[str] = Field(default_factory=list)
    unidades_medida: List[str] = Field(default_factory=list)
    forma_pago: str = ""
    estado_deuda: str = ""
    tipo_comprobante: str = ""
    company_id: int = 0


def _match_invoice(inv: InvoiceInput) -> Dict[str, Any]:
    padron = load_padron(inv.company_id)
    prov_hit = (
        match_proveedor_excel(inv.proveedor, inv.cuit, padron["proveedores"])
        if (inv.proveedor or inv.cuit)
        else None
    )

    best_concepto = None
    best_concepto_score = 0.0
    best_producto = None
    line_matches = []
    conceptos = padron.get("conceptos") or []
    productos = padron.get("productos") or []
    cat_map = padron.get("categoria_map") or {}

    for i, line in enumerate(inv.lineas):
        um = inv.unidades_medida[i] if i < len(inv.unidades_medida) else ""
        lm: Dict[str, Any] = {"query": line, "unidad_medida_factura": um}
        conc = match_one(line, conceptos) if line.strip() else None
        if conc:
            lm["concepto"] = conc[0]
            lm["concepto_score"] = conc[1]
            lm["categoria"] = cat_map.get(conc[0], "")
            if conc[1] > best_concepto_score:
                best_concepto = conc[0]
                best_concepto_score = conc[1]
        prod = match_producto(line, um, productos) if line.strip() else None
        if prod:
            lm["producto"] = prod
            if best_producto is None or prod["score"] > best_producto["score"]:
                best_producto = prod
        line_matches.append(lm)

    fp_hit = match_forma_pago(inv.forma_pago, padron["formas_pago"]) if inv.forma_pago else None
    categoria = cat_map.get(best_concepto, "") if best_concepto else ""

    return {
        "mes": inv.mes,
        "sucursal": inv.sucursal,
        "proveedor": inv.proveedor,
        "cuit": inv.cuit,
        "proveedor_match": (prov_hit or {}).get("match", ""),
        "proveedor_razon_social": (prov_hit or {}).get("razon_social", ""),
        "proveedor_nombre_fantasia": (prov_hit or {}).get("nombre_fantasia", ""),
        "proveedor_cuit": (prov_hit or {}).get("cuit", ""),
        "proveedor_score": (prov_hit or {}).get("score", 0.0),
        "concepto": best_concepto or "",
        "concepto_score": best_concepto_score,
        "categoria": categoria,
        "producto": (best_producto or {}).get("match", ""),
        "producto_score": (best_producto or {}).get("score", 0.0),
        "unidad_medida": (best_producto or {}).get("unidad_medida", ""),
        "um_match": (best_producto or {}).get("um_match"),
        "forma_pago": inv.forma_pago,
        "forma_pago_match": fp_hit[0] if fp_hit else "",
        "forma_pago_score": fp_hit[1] if fp_hit else 0.0,
        "estado_deuda": inv.estado_deuda,
        "tipo_comprobante": inv.tipo_comprobante,
        "lineas": inv.lineas,
        "unidades_medida": inv.unidades_medida,
        "line_matches": line_matches,
        "company_id": inv.company_id,
    }


@router.get("/config")
def get_config(company_id: int = Query(0)):
    return cfg_store.get_config(company_id)


@router.put("/config")
def put_config(body: PadronExcelConfigIn):
    cfg = cfg_store.save_config(
        body.company_id,
        {
            "sheet_url": body.sheet_url,
            "refresh_minutes": body.refresh_minutes,
            "mapping": body.mapping,
        },
    )
    invalidate_data_cache(body.company_id)
    return cfg


@router.post("/upload")
async def upload_padron(
    file: UploadFile = File(...),
    kind: str = Form(...),
    company_id: int = Form(0),
):
    if kind not in PADRON_KINDS:
        raise HTTPException(400, f"kind must be one of {list(PADRON_KINDS)}")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Archivo vacío")
    filename = file.filename or f"{kind}.csv"
    try:
        rows = parse_file_bytes(data, filename)
    except Exception as e:
        raise HTTPException(400, f"No se pudo parsear el archivo: {e}")
    cfg_store.save_upload(company_id, kind, filename, data)
    invalidate_data_cache(company_id)
    return {"kind": kind, "filename": filename, **preview_rows(rows)}


@router.get("/data")
def get_data(company_id: int = Query(0), sheet_url: Optional[str] = Query(None)):
    if sheet_url:
        cfg_store.save_config(company_id, {"sheet_url": sheet_url})
        invalidate_data_cache(company_id)
    padron = load_padron(company_id)
    return {
        "proveedores": padron["proveedores"],
        "productos": padron["productos"],
        "formas_pago": padron["formas_pago"],
        "conceptos": padron["conceptos"],
        "categoria_map": padron["categoria_map"],
        "config": padron["config"],
        "row_count": {
            "proveedores": len(padron["proveedores"]),
            "productos": len(padron["productos"]),
            "formas_pago": len(padron["formas_pago"]),
            "conceptos": len(padron["conceptos"]),
        },
    }


@router.post("/preview")
def preview_sheet(body: PreviewRequest):
    try:
        return sheet_preview(body.url, max_rows=body.max_rows)
    except Exception as e:
        raise HTTPException(400, f"Error fetching sheet: {e}")


@router.post("/match")
def match(body: MatchRequest):
    padron = load_padron(body.company_id)
    field = body.field

    if field == "proveedor":
        results = []
        for q in body.queries:
            hit = match_proveedor_excel(q, body.cuit or "", padron["proveedores"], body.min_score)
            if hit:
                results.append({"query": q, **hit})
            else:
                results.append({"query": q, "match": None, "score": 0.0})
        return {"field": field, "results": results}

    if field == "producto":
        ums = body.unidades_medida or []
        results = []
        for i, q in enumerate(body.queries):
            um = ums[i] if i < len(ums) else ""
            hit = match_producto(q, um, padron["productos"], body.min_score)
            if hit:
                results.append({"query": q, **hit})
            else:
                results.append({"query": q, "match": None, "score": 0.0, "unidad_medida": "", "um_match": None})
        return {"field": field, "results": results}

    if field == "concepto":
        results = match_bulk(body.queries, padron["conceptos"], body.min_score)
        cat_map = padron.get("categoria_map") or {}
        for r in results:
            if r.get("match"):
                r["categoria"] = cat_map.get(r["match"], "")
        return {"field": field, "results": results}

    if field == "forma_pago":
        return {"field": field, "results": match_bulk(body.queries, padron["formas_pago"], body.min_score)}

    raise HTTPException(400, "field must be one of: proveedor, producto, concepto, forma_pago")


@router.post("/facturas")
def create_factura(body: InvoiceInput):
    matched = _match_invoice(body)
    return excel_store.add_record(matched)


@router.post("/facturas/batch")
def create_facturas_batch(items: List[InvoiceInput]):
    matched = [_match_invoice(inv) for inv in items]
    return excel_store.add_many(matched)


@router.get("/facturas")
def list_facturas(limit: int = Query(500)):
    return excel_store.list_records(limit=limit)


EXPORT_COLUMNS = [
    "Mes",
    "Sucursal",
    "Proveedores",
    "CUIT",
    "Conceptos",
    "Producto",
    "Unidad de Medida",
    "Forma de Pago",
    "Estado de Deuda",
    "Tipo Comprobante",
    "Categoría",
]


@router.get("/facturas/export/csv")
def export_csv():
    records = excel_store.list_records()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_COLUMNS)
    for r in records:
        writer.writerow(
            [
                r.get("mes", ""),
                r.get("sucursal", ""),
                r.get("proveedor_match") or r.get("proveedor", ""),
                r.get("proveedor_cuit") or r.get("cuit", ""),
                r.get("concepto", ""),
                r.get("producto", ""),
                r.get("unidad_medida", ""),
                r.get("forma_pago_match") or r.get("forma_pago", ""),
                r.get("estado_deuda", ""),
                r.get("tipo_comprobante", ""),
                r.get("categoria", ""),
            ]
        )
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=facturas_padron.csv"},
    )


@router.get("/facturas/{record_id}")
def get_factura(record_id: str):
    r = excel_store.get_record(record_id)
    if not r:
        raise HTTPException(404, "Record not found")
    return r


@router.put("/facturas/{record_id}")
def update_factura(record_id: str, body: InvoiceInput):
    """Re-match + replace fields of an existing invoice (keeps id / created_at)."""
    if not excel_store.get_record(record_id):
        raise HTTPException(404, "Record not found")
    matched = _match_invoice(body)
    r = excel_store.update_record(record_id, matched)
    if not r:
        raise HTTPException(404, "Record not found")
    return r


@router.delete("/facturas/{record_id}")
def delete_factura(record_id: str):
    ok = excel_store.delete_record(record_id)
    if not ok:
        raise HTTPException(404, "Record not found")
    return {"ok": True}


@router.post("/invalidate-cache")
def invalidate_cache(company_id: int = Query(0)):
    reset_cache()
    invalidate_data_cache(company_id)
    return {"ok": True}
