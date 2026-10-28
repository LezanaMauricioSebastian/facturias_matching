"""Build a human-readable matching preview from proceso rows."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Optional


def _s(row: dict, *keys: str) -> str:
    for k in keys:
        v = row.get(k)
        if v is None:
            continue
        t = str(v).strip()
        if t:
            return t
    return ""


def _comp_idx(row: dict) -> int:
    raw = row.get("__comprobante_idx")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _group_rows(rows: List[dict]) -> "OrderedDict[int, List[dict]]":
    groups: "OrderedDict[int, List[dict]]" = OrderedDict()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        idx = _comp_idx(row)
        groups.setdefault(idx, []).append(row)
    return groups


def build_match_preview(
    rows: List[dict],
    *,
    process_number: str,
    odoo_profile: str = "default",
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """Summarize matches + gaps for ChatGPT to show the accountant."""
    groups = _group_rows(rows)
    comprobantes: List[Dict[str, Any]] = []
    all_gaps: List[str] = []

    for idx, group in groups.items():
        first = group[0]
        partner = _s(first, "partner_id")
        cuit = _s(first, "CUIT", "cuit", "vat")
        doc = _s(first, "l10n_latam_document_number")
        doc_type = _s(first, "l10n_latam_document_type_id")
        date = _s(first, "invoice_date")
        journal = _s(first, "journal_id")
        subtotal = _s(first, "__fac_subtotal")
        iva = _s(first, "__fac_iva_monto")
        gaps: List[str] = []

        if not partner:
            gaps.append("Sin proveedor Odoo (partner_id)")
        if not doc:
            gaps.append("Sin número de comprobante")
        if not date:
            gaps.append("Sin fecha")
        if not journal:
            gaps.append("Sin diario")

        lines_out: List[Dict[str, Any]] = []
        for i, row in enumerate(group):
            label = _s(row, "invoice_line_ids/name")
            product = _s(row, "invoice_line_ids/product_id")
            account = _s(row, "invoice_line_ids/account_id")
            qty = _s(row, "invoice_line_ids/quantity", "__fac_item_cantidad")
            price = _s(row, "invoice_line_ids/price_unit")
            iva_pct = _s(row, "iva_pct")
            line_gaps: List[str] = []
            if not product:
                line_gaps.append("sin producto")
            if not account:
                line_gaps.append("sin cuenta")
            if line_gaps:
                gaps.append(f"Línea {i + 1}: {', '.join(line_gaps)}")
            lines_out.append(
                {
                    "etiqueta": label or "(sin etiqueta)",
                    "producto": product or None,
                    "cuenta": account or None,
                    "cantidad": qty or None,
                    "precio_unitario": price or None,
                    "iva_pct": iva_pct or None,
                    "ok": not line_gaps,
                }
            )

        ready = len(gaps) == 0
        if gaps:
            all_gaps.extend([f"Comprobante {idx}: {g}" for g in gaps])

        comprobantes.append(
            {
                "comprobante_idx": idx,
                "numero": doc or None,
                "tipo": doc_type or None,
                "fecha": date or None,
                "cuit": cuit or None,
                "proveedor": partner or None,
                "diario": journal or None,
                "subtotal_fac": subtotal or None,
                "iva_monto_fac": iva or None,
                "lineas": lines_out,
                "gaps": gaps,
                "ready_for_draft_import": ready,
            }
        )

    ready_all = bool(comprobantes) and all(c["ready_for_draft_import"] for c in comprobantes)
    ask = (
        "Mostrá este resumen al contador y preguntá si los datos son correctos. "
        "Si dice que sí, llamá confirm_invoice_preview con el preview_id. "
        "Si hay que corregir algo, pedí el cambio y volvé a preview_invoice_match. "
        "Nunca llames import_odoo_draft sin confirmation_token."
    )
    if all_gaps:
        ask = (
            "Hay gaps de matching. Listalos al contador y preguntá cómo resolverlos "
            "(o si quiere importar igual en borrador). " + ask
        )

    return {
        "process_number": str(process_number),
        "odoo_profile": odoo_profile or "default",
        "source": source,
        "comprobante_count": len(comprobantes),
        "comprobantes": comprobantes,
        "gaps": all_gaps,
        "ready_for_draft_import": ready_all,
        "ask_user": ask,
    }
