"""Parse FacturIA process JSON and build UI rows."""

import json
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from facturia_matching.core.amounts import (
    apply_fac_percepciones_to_row,
    fac_header_amount_str,
    fac_iva_montos_dict,
    fac_iva_monto_str,
    normalize_iva_pct_value,
    resolve_fac_item_qty_price,
)
from facturia_matching.persistence.back_check import get_process
from facturia_matching.infra.config import DEFAULT_JOURNAL_NAME, DEFAULT_RUBRO_NAME
from facturia_matching.core.constants import IVA_SPECIAL_OPTIONS
from facturia_matching.odoo.catalog import (
    get_catalog,
    resolve_account_id,
    resolve_doc_type_id,
    resolve_id_fuzzy,
    resolve_partner_id,
)
from facturia_matching.odoo.env import supports_rubro_field
from facturia_matching.padron.postgres import match_proveedor
from facturia_matching.padron.taxes import (
    PadronTaxMatchCache,
    apply_padron_taxes_to_row,
    get_tax_name_by_id,
)
from facturia_matching.core.comprobante_tax import sanitize_inflated_line_amounts
from facturia_matching.odoo.purchase_matching import enrich_rows_with_purchase_data
from facturia_matching.infra.normalization import doc_type_label, normalize, normalize_comprobante_number, normalize_date_ddmmyyyy

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


def parse_process_json(
    process_number: str, empresa: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, Any]]:
    catalog, odoo_ok = get_catalog()
    maps = (catalog or {}).get("maps") or {}
    doc_label_map = maps.get("document_type_labels") or {}
    proveedores_odoo = (catalog or {}).get("proveedores") or []
    journals_odoo = (catalog or {}).get("journals") or []
    cuentas_odoo = (catalog or {}).get("cuentas") or []
    rubros_odoo = (catalog or {}).get("rubros") or []
    partner_cuit_to_id = (catalog or {}).get("partner_cuit_to_id") or {}

    row = get_process(int(process_number), empresa=empresa)
    if not row:
        return ([], [], {"enabled": False})

    json_data = row.get("json_data")
    if json_data is None:
        raise HTTPException(status_code=500, detail="El proceso no tiene json_data.")
    try:
        obj = json.loads(json_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo parsear json_data del proceso: {e}")

    facturas = obj.get("facturas") or []
    out_rows: List[Dict[str, Any]] = []
    etiqueta_opts: List[str] = []
    comprobante_idx = -1
    tax_match_cache = PadronTaxMatchCache()

    for fac_wrap in facturas:
        j = fac_wrap.get("json") if isinstance(fac_wrap, dict) else None
        if not isinstance(j, dict):
            continue
        fac = j.get("factura") if isinstance(j.get("factura"), dict) else {}
        comprobante_idx += 1

        fac_subtotal_hdr = fac_header_amount_str(fac, _FAC_SUBTOTAL_KEYS)
        fac_iva_monto_hdr = fac_iva_monto_str(fac)
        fac_iva_montos_hdr = fac_iva_montos_dict(fac)
        fac_iva_montos_json = (
            json.dumps(fac_iva_montos_hdr, ensure_ascii=False) if fac_iva_montos_hdr else ""
        )

        nro = normalize_comprobante_number(fac.get("numero_factura"))
        fecha = normalize_date_ddmmyyyy(fac.get("fecha"))
        venc = normalize_date_ddmmyyyy(
            fac.get("fecha_de_vencimiento") or fac.get("fecha_de_vencimiento") or fac.get("fecha_vencimiento")
        )
        tipo = normalize(fac.get("tipo_comprobante"))
        doc_type_label_val = doc_type_label(tipo)
        doc_type_id = resolve_doc_type_id(doc_type_label_val, doc_label_map) if odoo_ok else ""

        prov = fac.get("proveedor") if isinstance(fac.get("proveedor"), dict) else {}
        prov_nombre = normalize(prov.get("razon_social") or prov.get("nombre") or "")
        prov_cuit = normalize(prov.get("cuit") or "")

        matched_name, matched_rubro, matched_diario, matched_cuenta, score = match_proveedor(
            prov_nombre, prov_cuit
        )

        if odoo_ok:
            partner_id, score_odoo = resolve_partner_id(
                prov_nombre,
                prov_cuit,
                proveedores_odoo,
                partner_cuit_to_id,
            )
            if not partner_id and matched_name:
                partner_id = resolve_id_fuzzy(matched_name, proveedores_odoo, min_score=72.0)
                score_odoo = score if not score_odoo else score_odoo
            score = max(score, score_odoo)
            journal_id = resolve_id_fuzzy(
                matched_diario,
                journals_odoo,
                fallback_name=DEFAULT_JOURNAL_NAME or None,
                min_score=75.0,
            )
            account_maps = maps.get("accounts") or {}
            account_id = resolve_account_id(
                matched_cuenta,
                cuentas_odoo,
                account_maps,
                min_score=65.0,
            )
            if supports_rubro_field():
                rubro_id = resolve_id_fuzzy(
                    matched_rubro,
                    rubros_odoo,
                    fallback_name=DEFAULT_RUBRO_NAME or None,
                    min_score=72.0,
                )
            else:
                rubro_id = ""
        else:
            partner_id = ""
            journal_id = ""
            account_id = ""
            rubro_id = ""

        items = fac.get("items") if isinstance(fac.get("items"), list) else []
        if not items:
            items = [{"descripcion": "", "cantidad": "", "precio_unitario": ""}]

        comprobante_tax_match = tax_match_cache.get(prov_nombre, prov_cuit)
        comprobante_tax_names = get_tax_name_by_id() if comprobante_tax_match[0] else None

        for i, it in enumerate(items):
            desc = normalize((it or {}).get("descripcion"))
            if desc:
                etiqueta_opts.append(desc)
            qty = (it or {}).get("cantidad")
            price = (it or {}).get("precio_unitario")
            qty_str, price_str = resolve_fac_item_qty_price(it or {})
            if qty_str or price_str:
                qty = qty_str if qty_str else qty
                price = price_str if price_str else price
            iva = (it or {}).get("alicuota_iva")
            otros_imp = (it or {}).get("otros_impuestos") or (it or {}).get("otros_tributos") or ""
            item_codigo = normalize((it or {}).get("codigo"))
            item_um = normalize((it or {}).get("unidad_medida"))

            mismo_comprobante = i > 0
            otros_imp_n = normalize(otros_imp)
            iva_str = "" if iva is None else normalize_iva_pct_value(str(iva).strip())

            if (not iva_str) and otros_imp_n in IVA_SPECIAL_OPTIONS:
                iva_str = otros_imp_n
                otros_imp_n = ""

            if (not iva_str) and doc_type_label_val == "FACTURAS C":
                iva_str = "IVA No Corresponde"

            row_out = {
                "l10n_latam_document_number": "" if mismo_comprobante else nro,
                "partner_id": "" if mismo_comprobante else partner_id,
                "l10n_latam_document_type_id": "" if mismo_comprobante else doc_type_id,
                "invoice_date": "" if mismo_comprobante else fecha,
                "invoice_date_due": "" if mismo_comprobante else venc,
                "x_studio_category": "" if mismo_comprobante else rubro_id,
                "invoice_line_ids/name": desc,
                "invoice_line_ids/product_id": "",
                "journal_id": "" if mismo_comprobante else journal_id,
                "invoice_line_ids/account_id": "" if mismo_comprobante else account_id,
                "invoice_line_ids/quantity": "" if qty is None else str(qty),
                "invoice_line_ids/price_unit": "" if price is None else str(price),
                "iva_pct": iva_str,
                "iva_monto": "",
                "otros_impuestos": otros_imp_n,
                "otros_impuestos_monto": "",
                "Nombre de Proveedor": prov_nombre,
                "CUIT": prov_cuit,
                "Nombre de producto": desc,
                "__item_codigo": item_codigo,
                "__fac_item_cantidad": "" if (it or {}).get("cantidad") is None else str((it or {}).get("cantidad")),
                "__um_proveedor": item_um,
                "_match_score_proveedor": score,
                "__comprobante_idx": comprobante_idx,
                "__fac_subtotal": fac_subtotal_hdr if i == 0 else "",
                "__fac_iva_monto": fac_iva_monto_hdr if i == 0 else "",
                "__fac_iva_montos": fac_iva_montos_json if i == 0 else "",
            }
            if i == 0:
                apply_fac_percepciones_to_row(fac, row_out)
            apply_padron_taxes_to_row(
                row_out,
                prov_nombre,
                prov_cuit,
                tax_match=comprobante_tax_match,
                name_by_id=comprobante_tax_names,
            )
            out_rows.append(row_out)

    etiqueta_opts = sorted({p for p in etiqueta_opts if p})

    purchase_summary: Dict[str, Any] = {"enabled": False}
    if odoo_ok and out_rows:
        purchase_summary = enrich_rows_with_purchase_data(out_rows)

    sanitize_inflated_line_amounts(out_rows)

    return (out_rows, etiqueta_opts, purchase_summary)


def attach_facturia_item_quantities(
    rows: List[Dict[str, Any]],
    process_number: str,
    empresa: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Inyecta __fac_item_cantidad desde json_data (p. ej. conversiones guardadas antiguas)."""
    if not rows:
        return rows

    row = get_process(process_number, empresa=empresa)
    if not row or not row.get("json_data"):
        return rows

    try:
        obj = json.loads(row["json_data"])
    except Exception:
        return rows

    by_comprobante: Dict[Any, List[str]] = {}
    comprobante_idx = -1
    for fac_wrap in obj.get("facturas") or []:
        j = fac_wrap.get("json") if isinstance(fac_wrap, dict) else None
        if not isinstance(j, dict):
            continue
        fac = j.get("factura") if isinstance(j.get("factura"), dict) else {}
        comprobante_idx += 1
        items = fac.get("items") if isinstance(fac.get("items"), list) else []
        qtys: List[str] = []
        for it in items:
            if not isinstance(it, dict):
                qtys.append("")
                continue
            raw = it.get("cantidad")
            qtys.append("" if raw is None else str(raw))
        by_comprobante[comprobante_idx] = qtys

    line_idx: Dict[Any, int] = {}
    for ui_row in rows:
        if not isinstance(ui_row, dict):
            continue
        comp = ui_row.get("__comprobante_idx", 0)
        idx = line_idx.get(comp, 0)
        line_idx[comp] = idx + 1
        qtys = by_comprobante.get(comp, [])
        if idx < len(qtys) and qtys[idx]:
            ui_row["__fac_item_cantidad"] = qtys[idx]

    return rows


def backfill_fac_iva_montos_from_process(
    rows: List[Dict[str, Any]],
    process_number: str,
    empresa: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Completa __fac_iva_montos en conversiones guardadas desde el JSON FacturIA
    (iva_21, iva_10_5, …) cuando el proceso no trae alícuota por línea.
    """
    if not rows:
        return rows

    process_row = get_process(process_number, empresa=empresa)
    if not process_row or not process_row.get("json_data"):
        return rows

    try:
        obj = json.loads(process_row["json_data"])
    except Exception:
        return rows

    montos_by_idx: Dict[Any, str] = {}
    comprobante_idx = -1
    for fac_wrap in obj.get("facturas") or []:
        j = fac_wrap.get("json") if isinstance(fac_wrap, dict) else None
        if not isinstance(j, dict):
            continue
        fac = j.get("factura") if isinstance(j.get("factura"), dict) else {}
        comprobante_idx += 1
        montos = fac_iva_montos_dict(fac)
        if montos:
            montos_by_idx[comprobante_idx] = json.dumps(montos, ensure_ascii=False)

    if not montos_by_idx:
        return rows

    from facturia_matching.core.amounts import amount_to_str, parse_amount

    seen: set = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        idx = row.get("__comprobante_idx", 0)
        if idx in seen:
            continue
        seen.add(idx)
        if str(row.get("__fac_iva_montos") or "").strip():
            continue
        montos_json = montos_by_idx.get(idx)
        if not montos_json:
            continue
        row["__fac_iva_montos"] = montos_json
        if not str(row.get("__fac_iva_monto") or "").strip():
            try:
                parsed = json.loads(montos_json)
                total = sum(parse_amount(v) or 0.0 for v in parsed.values())
                if total > 0:
                    row["__fac_iva_monto"] = amount_to_str(total) or str(total)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
    return rows


def build_output_rows(filas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return filas
