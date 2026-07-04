"""
Importación de filas UI → facturas de proveedor en Odoo (account.move, in_invoice).
Usa la misma instancia Odoo del perfil activo (Dinner o Aliare).
"""

from __future__ import annotations

import json
import re
from datetime import date
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from facturia_matching.core.comprobante_tax import (
    classify_comprobante_tax_mode,
    fac_iva_monto,
    fac_iva_montos,
    iva_pct_to_rate,
    line_iva_monto,
    line_iva_suggested,
    reconcile_fac_iva_for_import,
    sync_fac_iva_montos_from_lines,
)
from facturia_matching.odoo.api import get_odoo_import_config, get_odoo_uid_from_config, is_odoo_config_ready, odoo_execute_kw_with_config
from facturia_matching.odoo.env import is_odoo_aliare_profile, is_odoo_sudata_profile, supports_rubro_field
from facturia_matching.padron.taxes import (
    build_csv_tax_ids_dot_id,
    is_iva_tax_id,
    iva_pct_requires_line_tax,
    resolve_tax_label_to_id,
    tax_id_for_csv_export,
)

_DATE_DD_MM = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")

_MOVE_LINE_PURCHASE_LINK_CACHE: Dict[str, bool] = {}


def _odoo_config_cache_key(config: Dict[str, Any]) -> str:
    return f"{config.get('base_url', '')}|{config.get('db', '')}"


def _move_line_supports_purchase_link(config: Dict[str, Any]) -> bool:
    """False si account.move.line no tiene purchase_line_id (ej. Odoo Cloud Sudata sin purchase)."""
    key = _odoo_config_cache_key(config)
    if key in _MOVE_LINE_PURCHASE_LINK_CACHE:
        return _MOVE_LINE_PURCHASE_LINK_CACHE[key]
    supported = False
    try:
        fg = odoo_execute_kw_with_config(
            config,
            "account.move.line",
            "fields_get",
            [],
            {"attributes": []},
        )
        supported = isinstance(fg, dict) and "purchase_line_id" in fg
    except Exception:
        supported = False
    _MOVE_LINE_PURCHASE_LINK_CACHE[key] = supported
    return supported


def _move_product_line_fields(config: Dict[str, Any]) -> List[str]:
    fields = ["id", "name", "sequence", "tax_ids"]
    if _move_line_supports_purchase_link(config):
        fields.append("purchase_line_id")
    fields.extend(["product_id", "quantity", "price_unit", "account_id"])
    return fields


def _normalize(s: Any) -> str:
    if s is None:
        return ""
    return " ".join(str(s).strip().split())


def _int_id(raw: Any) -> Optional[int]:
    s = _normalize(raw)
    if not s or not s.isdigit():
        return None
    return int(s)


def _m2o_id(raw: Any) -> Optional[int]:
    if isinstance(raw, (list, tuple)) and raw:
        try:
            return int(raw[0])
        except (TypeError, ValueError):
            return None
    if isinstance(raw, int):
        return raw
    return _int_id(raw)


def _floats_differ(left: float, right: float, tolerance: float = 0.001) -> bool:
    return abs(float(left) - float(right)) > tolerance


def _parse_amount_loose(raw: Any) -> Optional[float]:
    s = _normalize(raw)
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


def _date_ddmm_to_iso(raw: Any) -> Optional[str]:
    s = _normalize(raw)
    if not s:
        return None
    s = s.replace("-", "/")
    m = _DATE_DD_MM.match(s)
    if not m:
        if re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", s):
            return s
        return None
    dd, mm, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        d = date(yyyy, mm, dd)
    except ValueError:
        return None
    return d.isoformat()


def _tax_ids_from_row(row: Dict[str, Any]) -> List[int]:
    cell = build_csv_tax_ids_dot_id(row)
    out: List[int] = []
    seen: set = set()
    for part in (cell or "").split(","):
        p = part.strip()
        if p.isdigit():
            tid = int(p)
            if tid not in seen:
                seen.add(tid)
                out.append(tid)
    return out


def _first_content_row_index(group: List[Dict[str, Any]]) -> Optional[int]:
    for i, row in enumerate(group):
        if _line_has_content(row):
            return i
    return None


def _is_first_content_row(row: Dict[str, Any], group: List[Dict[str, Any]]) -> bool:
    idx = _first_content_row_index(group)
    if idx is None:
        return False
    return group[idx] is row


def _comprobante_non_iva_tax_ids(group: List[Dict[str, Any]]) -> List[int]:
    """Impuestos no-IVA del comprobante (IIBB/percepciones), en cualquier fila del grupo."""
    ids: List[int] = []
    seen: set = set()
    for row in group:
        if not isinstance(row, dict):
            continue
        row_non_iva = [tid for tid in _tax_ids_from_row(row) if not is_iva_tax_id(tid)]
        for tid in _padron_other_tax_ids_from_row(row):
            if tid not in row_non_iva:
                row_non_iva.append(tid)
        other_idx = 0
        for _n, label_key, monto_key in _iter_otros_impuesto_slots(row):
            label = _normalize(row.get(label_key))
            monto = _parse_amount_loose(row.get(monto_key))
            if not label and (monto is None or monto <= 0):
                continue
            tid = resolve_tax_label_to_id(label) if label else None
            if tid is None and monto is not None and monto > 0 and other_idx < len(row_non_iva):
                tid = row_non_iva[other_idx]
                other_idx += 1
            if tid is None or is_iva_tax_id(tid) or tid in seen:
                continue
            seen.add(tid)
            ids.append(int(tid))
        for tid in row_non_iva:
            if tid not in seen:
                seen.add(tid)
                ids.append(tid)
    return ids


def _merge_comprobante_non_iva_tax_ids(
    tax_ids: List[int],
    row: Dict[str, Any],
    group: List[Dict[str, Any]],
) -> List[int]:
    """En header/mixed, percepciones del comprobante van en la primera línea de producto."""
    mode = classify_comprobante_tax_mode(group)
    if mode not in ("header", "mixed") or not _is_first_content_row(row, group):
        return tax_ids
    merged = list(tax_ids)
    seen = set(merged)
    for tid in _comprobante_non_iva_tax_ids(group):
        if tid not in seen:
            seen.add(tid)
            merged.append(tid)
    return merged


def _filter_iva_tax_ids_for_row(
    row: Dict[str, Any],
    tax_ids: List[int],
    mode: str,
) -> List[int]:
    if not iva_pct_requires_line_tax(row.get("iva_pct")):
        return [tid for tid in tax_ids if not is_iva_tax_id(tid)]
    if mode == "header" and iva_pct_to_rate(row.get("iva_pct")) > 0:
        return [tid for tid in tax_ids if not is_iva_tax_id(tid)]
    return tax_ids


def _tax_ids_for_odoo_line(
    row: Dict[str, Any],
    group: Optional[List[Dict[str, Any]]] = None,
) -> List[int]:
    """
    tax_ids de una línea de producto en Odoo según arquitectura FacturIA:
    - header: IVA numérico solo en el total de abajo; Exento/No Gravado sí en línea.
    - line / mixed: IVA en la línea si esa fila trae iva_pct > 0 o Exento/No Gravado.
    - IIBB/percepciones a nivel comprobante se consolidan en la primera línea con contenido.
    """
    tax_ids = _tax_ids_from_row(row)
    if not group:
        return _filter_iva_tax_ids_for_row(row, tax_ids, "line")

    mode = classify_comprobante_tax_mode(group)
    result = _filter_iva_tax_ids_for_row(row, tax_ids, mode)
    return _merge_comprobante_non_iva_tax_ids(result, row, group)


def _line_has_content(row: Dict[str, Any]) -> bool:
    return bool(
        _normalize(row.get("invoice_line_ids/name"))
        or _parse_amount_loose(row.get("invoice_line_ids/price_unit")) is not None
        or _parse_amount_loose(row.get("invoice_line_ids/quantity")) is not None
    )


def _invoice_group_key(row: Dict[str, Any], row_index: int) -> str:
    idx = row.get("__comprobante_idx")
    if idx is not None:
        return f"idx:{idx}"
    doc = _normalize(row.get("l10n_latam_document_number"))
    if doc:
        return f"doc:{doc}"
    return f"row:{row_index}"


def group_rows_into_invoices(rows: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Agrupa filas por comprobante (__comprobante_idx o número de documento)."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        key = _invoice_group_key(row, i)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(dict(row))
    return [groups[k] for k in order]


def propagate_invoice_headers(group: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Copia encabezado del comprobante a líneas siguientes (misma lógica que CSV)."""
    if not group:
        return []
    out = [dict(group[0])]
    header_keys = (
        "l10n_latam_document_number",
        "partner_id",
        "l10n_latam_document_type_id",
        "invoice_date",
        "invoice_date_due",
        "x_studio_category",
        "journal_id",
    )
    for r in group[1:]:
        cur = dict(r)
        for k in header_keys:
            if not _normalize(cur.get(k)) and _normalize(out[0].get(k)):
                cur[k] = out[0][k]
        out.append(cur)
    return out


def validate_rows_for_import(rows: List[Dict[str, Any]]) -> Optional[str]:
    if not rows:
        return "No hay filas para importar."
    groups = [propagate_invoice_headers(g) for g in group_rows_into_invoices(rows)]
    for gi, group in enumerate(groups):
        header = group[0]
        label = _normalize(header.get("l10n_latam_document_number")) or f"comprobante {gi + 1}"
        if not _int_id(header.get("partner_id")):
            return f"{label}: falta proveedor (partner_id)."
        if not _int_id(header.get("journal_id")):
            return f"{label}: falta diario (journal_id)."
        if not _normalize(header.get("l10n_latam_document_number")):
            return f"Comprobante {gi + 1}: falta número de documento."
        if not _date_ddmm_to_iso(header.get("invoice_date")):
            return f"{label}: fecha de factura inválida o vacía."
        lines = [r for r in group if _line_has_content(r)]
        if not lines:
            return f"{label}: no hay líneas con descripción o importe."
        for li, line in enumerate(lines):
            if not _int_id(line.get("invoice_line_ids/account_id")):
                return f"{label}, línea {li + 1}: falta cuenta contable."
    return None


def _invoice_origin_from_group(group: List[Dict[str, Any]]) -> str:
    """Nombre(s) de OC para invoice_origin (vínculo visible en el encabezado Odoo)."""
    for row in group:
        selected = _normalize(row.get("__selected_oc_name"))
        if selected:
            return selected
    names: List[str] = []
    seen: set = set()
    for row in group:
        if not _line_has_content(row):
            continue
        name = _normalize(row.get("__oc_name"))
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return ", ".join(names)


def _build_line_command(
    row: Dict[str, Any],
    group: Optional[List[Dict[str, Any]]] = None,
    *,
    include_purchase_link: bool = True,
    include_product_id: bool = True,
) -> Tuple[int, int, Dict[str, Any]]:
    qty = _parse_amount_loose(row.get("invoice_line_ids/quantity"))
    if qty is None or qty <= 0:
        qty = 1.0
    price = _parse_amount_loose(row.get("invoice_line_ids/price_unit"))
    if price is None:
        price = 0.0
    vals: Dict[str, Any] = {
        "name": _normalize(row.get("invoice_line_ids/name")) or "Línea importada",
        "quantity": qty,
        "price_unit": price,
    }
    account_id = _int_id(row.get("invoice_line_ids/account_id"))
    if account_id:
        vals["account_id"] = account_id
    product_id = _int_id(row.get("invoice_line_ids/product_id"))
    if include_product_id and product_id:
        vals["product_id"] = product_id
    po_line_id = _int_id(row.get("__oc_line_id"))
    if include_purchase_link and po_line_id:
        vals["purchase_line_id"] = po_line_id
    tax_ids = _tax_ids_for_odoo_line(row, group)
    vals["tax_ids"] = [(6, 0, tax_ids)]
    return (0, 0, vals)


def _content_rows_from_group(group: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in group if _line_has_content(r)]


def _purchase_line_id_raw(line: Dict[str, Any]) -> Optional[int]:
    raw = line.get("purchase_line_id")
    if isinstance(raw, (list, tuple)) and raw:
        return int(raw[0])
    if isinstance(raw, int):
        return raw
    return None


def _purchase_line_id_from_row(row: Dict[str, Any]) -> Optional[int]:
    return _int_id(row.get("__oc_line_id"))


def _existing_purchase_line_ids(config: Dict[str, Any], ids: List[int]) -> set:
    if not ids:
        return set()
    found = odoo_execute_kw_with_config(
        config,
        "purchase.order.line",
        "search",
        [[("id", "in", sorted(set(ids)))]],
    )
    return {int(x) for x in (found or [])}


def sanitize_group_purchase_lines(
    config: Dict[str, Any],
    group: List[Dict[str, Any]],
) -> List[str]:
    """Quita __oc_line_id inexistentes en Odoo para evitar fallos al crear/vincular facturas."""
    warnings: List[str] = []
    ids: List[int] = []
    for row in group:
        po_line_id = _purchase_line_id_from_row(row)
        if po_line_id:
            ids.append(po_line_id)
    if not ids:
        return warnings

    existing = _existing_purchase_line_ids(config, ids)
    for row in group:
        po_line_id = _purchase_line_id_from_row(row)
        if not po_line_id or po_line_id in existing:
            continue
        line_name = _normalize(row.get("invoice_line_ids/name")) or "?"
        oc_name = _normalize(row.get("__oc_name")) or str(po_line_id)
        warnings.append(
            f"Línea {line_name}: OC {oc_name} (purchase_line_id {po_line_id}) "
            "no existe en Odoo; se importa sin vínculo OC"
        )
        row["__oc_line_id"] = ""
        row["__oc_line_name"] = ""
        row["__oc_order_id"] = ""
    return warnings


def _refresh_purchase_links(rows: List[Dict[str, Any]]) -> List[str]:
    """
    Re-matchea OC contra Odoo inmediatamente antes de importar.
    Garantiza __oc_line_id frescos aunque el cliente envíe filas guardadas sin IDs.
    """
    from facturia_matching.odoo.purchase_matching import clear_purchase_cache, enrich_rows_with_purchase_data

    if not rows:
        return []
    clear_purchase_cache()
    summary = enrich_rows_with_purchase_data(rows)
    warnings: List[str] = []
    if not summary.get("enabled"):
        return warnings
    matched = int(summary.get("rows_matched") or 0)
    total = int(summary.get("rows_total") or 0)
    if total and matched < total:
        warnings.append(f"OC: solo {matched}/{total} líneas tienen purchase_line_id para Odoo")
    return warnings


def _prepare_rows_for_import(
    config: Dict[str, Any],
    rows: List[Dict[str, Any]],
) -> Tuple[List[List[Dict[str, Any]]], List[str]]:
    """Refresca vínculos OC, agrupa comprobantes y valida purchase_line_id en Odoo."""
    warnings: List[str] = []
    purchase_ok = _move_line_supports_purchase_link(config)
    if purchase_ok:
        warnings.extend(_refresh_purchase_links(rows))

    groups = [propagate_invoice_headers(g) for g in group_rows_into_invoices(rows)]

    for group in groups:
        reconcile_fac_iva_for_import(group)

    if not purchase_ok:
        return groups, warnings

    sanitized_any = False
    for group in groups:
        group_warnings = sanitize_group_purchase_lines(config, group)
        if group_warnings:
            sanitized_any = True
            warnings.extend(group_warnings)

    if sanitized_any:
        warnings.extend(_refresh_purchase_links(rows))
        groups = [propagate_invoice_headers(g) for g in group_rows_into_invoices(rows)]

    for group in groups:
        warnings.extend(_dedupe_group_oc_line_ids(group))

    return groups, warnings


def _dedupe_group_oc_line_ids(group: List[Dict[str, Any]]) -> List[str]:
    """Odoo no permite dos líneas de factura con el mismo purchase_line_id."""
    warnings: List[str] = []
    seen: set = set()
    for row in group:
        if not _line_has_content(row):
            continue
        po_id = _purchase_line_id_from_row(row)
        if not po_id:
            continue
        if po_id in seen:
            line_name = _normalize(row.get("invoice_line_ids/name")) or "?"
            row["__oc_line_id"] = ""
            warnings.append(
                f"Línea {line_name}: línea OC {po_id} ya usada en otra fila; se importa sin vínculo"
            )
        else:
            seen.add(po_id)
    return warnings


def plan_purchase_line_updates(
    product_lines: List[Dict[str, Any]],
    content_rows: List[Dict[str, Any]],
    *,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Planifica purchase_line_id en líneas de producto (empareja por orden con filas UI).
    Permite actualizar o quitar el vínculo OC si cambió la selección en FacturIA.
    """
    if config is not None and not _move_line_supports_purchase_link(config):
        return [], []

    updates: List[Dict[str, Any]] = []
    warnings: List[str] = []
    rows = _content_rows_from_group(content_rows)
    if not product_lines:
        warnings.append("La factura no tiene líneas de producto")
        return updates, warnings
    if not rows:
        warnings.append("No hay filas con contenido para vincular OC")
        return updates, warnings

    n = min(len(product_lines), len(rows))
    if len(product_lines) != len(rows):
        warnings.append(
            f"OC: líneas Odoo ({len(product_lines)}) vs filas UI ({len(rows)}): "
            f"se actualizan las primeras {n} por orden"
        )

    for i in range(n):
        line = product_lines[i]
        row = rows[i]
        expected = _purchase_line_id_from_row(row)
        current = _purchase_line_id_raw(line)
        if expected == current:
            continue
        if not expected:
            # No intentar purchase_line_id=False: Odoo puede fallar con FK en líneas enlazadas.
            continue
        updates.append(
            {
                "line_id": line["id"],
                "line_name": line.get("name"),
                "row_index": i,
                "old_purchase_line_id": current,
                "new_purchase_line_id": expected,
            }
        )
    return updates, warnings


def plan_invoice_origin_update(
    current: Any,
    group: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Planifica invoice_origin del encabezado si difiere de la OC en filas UI."""
    expected = _invoice_origin_from_group(group)
    current_norm = _normalize(current)
    if expected == current_norm:
        return None
    return {
        "old_invoice_origin": current_norm,
        "new_invoice_origin": expected,
    }


def _invoice_due_date_from_group(group: List[Dict[str, Any]]) -> Optional[str]:
    """Fecha de vencimiento del comprobante; si falta, usa la fecha de factura."""
    header = group[0] if group else {}
    due = _date_ddmm_to_iso(header.get("invoice_date_due"))
    if due:
        return due
    return _date_ddmm_to_iso(header.get("invoice_date"))


def plan_move_header_updates(
    move: Dict[str, Any],
    group: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Planifica invoice_date / invoice_date_due del encabezado (requerido por Odoo en AP)."""
    if not group:
        return None
    header = group[0]
    vals: Dict[str, Any] = {}
    inv_date = _date_ddmm_to_iso(header.get("invoice_date"))
    if inv_date and _normalize(move.get("invoice_date")) != inv_date:
        vals["invoice_date"] = inv_date
    due = _invoice_due_date_from_group(group)
    if due and _normalize(move.get("invoice_date_due")) != due:
        vals["invoice_date_due"] = due
    return vals or None


_PAYABLE_RECEIVABLE_ACCOUNT_TYPES = frozenset(
    {"asset_receivable", "liability_payable", "receivable", "payable"}
)


def _account_rows_by_id(
    config: Dict[str, Any],
    account_ids: List[int],
) -> Dict[int, Dict[str, Any]]:
    ids = sorted({int(a) for a in account_ids if a})
    if not ids:
        return {}
    rows = odoo_execute_kw_with_config(
        config,
        "account.account",
        "read",
        [ids],
        {"fields": ["id", "account_type"]},
    )
    return {int(r["id"]): r for r in rows or [] if r.get("id")}


def _account_requires_maturity(account_row: Optional[Dict[str, Any]]) -> bool:
    if not account_row:
        return False
    account_type = _normalize(account_row.get("account_type"))
    return account_type in _PAYABLE_RECEIVABLE_ACCOUNT_TYPES


def _ensure_move_line_maturity(
    config: Dict[str, Any],
    move_id: int,
    due_date_iso: str,
) -> int:
    """
    Odoo exige date_maturity en apuntes de cuentas por pagar/cobrar.
    La fecha de vencimiento del encabezado no siempre se propaga al recalcular impuestos.
    """
    if not due_date_iso:
        return 0
    lines = odoo_execute_kw_with_config(
        config,
        "account.move.line",
        "search_read",
        [[("move_id", "=", move_id)]],
        {"fields": ["id", "date_maturity", "account_id"]},
    )
    account_ids = [_m2o_id(line.get("account_id")) for line in lines or []]
    accounts = _account_rows_by_id(config, [a for a in account_ids if a])
    fixed = 0
    for line in lines or []:
        acc_id = _m2o_id(line.get("account_id"))
        if not acc_id or not _account_requires_maturity(accounts.get(acc_id)):
            continue
        if _normalize(line.get("date_maturity")):
            continue
        odoo_execute_kw_with_config(
            config,
            "account.move.line",
            "write",
            [[line["id"]], {"date_maturity": due_date_iso}],
        )
        fixed += 1
    return fixed


def _ensure_payment_term_maturity(
    config: Dict[str, Any],
    move_id: int,
    due_date_iso: str,
) -> int:
    """Compat: delega en _ensure_move_line_maturity (cubre payment_term y demás AP/AR)."""
    return _ensure_move_line_maturity(config, move_id, due_date_iso)


def _otros_impuesto_slot_keys(n: int) -> Tuple[str, str]:
    if n == 1:
        return "otros_impuestos", "otros_impuestos_monto"
    return f"otros_impuestos_{n}", f"otros_impuestos_{n}_monto"


def _iter_otros_impuesto_slots(row: Dict[str, Any]) -> List[Tuple[int, str, str]]:
    slots: List[Tuple[int, str, str]] = []
    for n in range(1, 21):
        label_key, monto_key = _otros_impuesto_slot_keys(n)
        if _normalize(row.get(label_key)) or _parse_amount_loose(row.get(monto_key)):
            slots.append((n, label_key, monto_key))
    return slots


def _tax_line_id_raw(line: Dict[str, Any]) -> Optional[int]:
    raw = line.get("tax_line_id")
    if isinstance(raw, (list, tuple)) and raw:
        return int(raw[0])
    if isinstance(raw, int):
        return raw
    return None


def _line_amount_abs(line: Dict[str, Any]) -> float:
    for key in ("balance", "debit", "credit", "amount_currency", "price_subtotal"):
        amt = _parse_amount_loose(line.get(key))
        if amt is not None and abs(amt) > 0:
            return abs(amt)
    return 0.0


def _iva_tax_id_for_rate(rate_key: str, row: Dict[str, Any]) -> Optional[int]:
    if not rate_key or rate_key == "_total":
        tid_s = tax_id_for_csv_export(row)
        if tid_s and tid_s.isdigit():
            return int(tid_s)
        return None
    probe = dict(row)
    probe["iva_pct"] = str(rate_key).replace(".", ",")
    tid_s = tax_id_for_csv_export(probe)
    if tid_s and tid_s.isdigit():
        return int(tid_s)
    return None


def _padron_other_tax_ids_from_row(row: Dict[str, Any]) -> List[int]:
    raw = row.get("_padron_other_tax_ids") or []
    out: List[int] = []
    for x in raw:
        try:
            tid = int(x)
        except (TypeError, ValueError):
            continue
        if not is_iva_tax_id(tid) and tid not in out:
            out.append(tid)
    return out


def _iva_tax_resolve_row(group: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fila de referencia para resolver account.tax id por alícuota (perfil Odoo activo)."""
    for row in _content_rows_from_group(group):
        if iva_pct_requires_line_tax(row.get("iva_pct")):
            return row
    for row in group:
        if not isinstance(row, dict):
            continue
        if row.get("__fac_iva_montos") or row.get("__fac_iva_monto"):
            return row
    return group[0] if group else {}


def collect_expected_tax_amounts_from_group(group: List[Dict[str, Any]]) -> Dict[int, float]:
    """
    Montos de impuesto esperados desde FacturIA (filas UI), indexados por account.tax id.
    En modo header/mixed el IVA viene del pie (__fac_iva_monto / __fac_iva_montos).
    """
    amounts: Dict[int, float] = defaultdict(float)
    content_rows = _content_rows_from_group(group)
    if not content_rows:
        return {}

    mode = classify_comprobante_tax_mode(group)
    iva_resolve_row = _iva_tax_resolve_row(group)

    if mode == "line":
        for row in content_rows:
            iva_amt = line_iva_monto(row)
            if iva_amt <= 0:
                continue
            tax_ids = _tax_ids_from_row(row)
            iva_tid_s = tax_id_for_csv_export(row)
            iva_tid: Optional[int] = None
            if iva_tid_s and iva_tid_s.isdigit():
                iva_tid = int(iva_tid_s)
            else:
                for tid in tax_ids:
                    if is_iva_tax_id(tid):
                        iva_tid = tid
                        break
            if iva_tid is not None:
                amounts[iva_tid] += iva_amt
    else:
        for rate_key, amt in fac_iva_montos(group).items():
            iva_tid = _iva_tax_id_for_rate(rate_key, iva_resolve_row)
            if iva_tid is not None and amt > 0:
                amounts[iva_tid] += amt

    for row in group:
        if not isinstance(row, dict):
            continue

        other_ids = [tid for tid in _tax_ids_from_row(row) if not is_iva_tax_id(tid)]
        for tid in _padron_other_tax_ids_from_row(row):
            if tid not in other_ids:
                other_ids.append(tid)

        other_idx = 0
        for _n, label_key, monto_key in _iter_otros_impuesto_slots(row):
            monto = _parse_amount_loose(row.get(monto_key))
            if monto is None or monto <= 0:
                continue
            label = _normalize(row.get(label_key))
            tid = resolve_tax_label_to_id(label) if label else None
            if tid is None and other_idx < len(other_ids):
                tid = other_ids[other_idx]
                other_idx += 1
            if tid is not None:
                amounts[int(tid)] += monto

    return {tid: round(amt, 2) for tid, amt in amounts.items() if amt > 0}


def plan_line_tax_updates(
    product_lines: List[Dict[str, Any]],
    content_rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Planifica tax_ids en líneas de producto (paso 1 antes de pisar montos en líneas tax).
    Empareja por orden (sequence/id en Odoo ↔ filas UI del comprobante).
    """
    updates: List[Dict[str, Any]] = []
    warnings: List[str] = []
    rows = _content_rows_from_group(content_rows)
    if not product_lines:
        warnings.append("La factura no tiene líneas de producto")
        return updates, warnings
    if not rows:
        warnings.append("No hay filas con contenido para aplicar impuestos")
        return updates, warnings

    n = min(len(product_lines), len(rows))
    if len(product_lines) != len(rows):
        warnings.append(
            f"Líneas Odoo ({len(product_lines)}) vs filas UI ({len(rows)}): "
            f"se actualizan las primeras {n} por orden"
        )

    for i in range(n):
        line = product_lines[i]
        row = rows[i]
        tax_ids = _tax_ids_for_odoo_line(row, content_rows)
        old_tax_ids = line.get("tax_ids") or []
        if sorted(old_tax_ids) == sorted(tax_ids):
            continue
        updates.append(
            {
                "line_id": line["id"],
                "line_name": line.get("name"),
                "old_tax_ids": old_tax_ids,
                "new_tax_ids": tax_ids,
            }
        )
    return updates, warnings


def plan_product_line_content_updates(
    product_lines: List[Dict[str, Any]],
    content_rows: List[Dict[str, Any]],
    *,
    tolerance: float = 0.001,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Planifica product_id, quantity, price_unit, name y account_id en líneas de producto.
    Empareja por orden (sequence/id en Odoo ↔ filas UI del comprobante).
    """
    updates: List[Dict[str, Any]] = []
    warnings: List[str] = []
    rows = _content_rows_from_group(content_rows)
    if not product_lines:
        warnings.append("La factura no tiene líneas de producto")
        return updates, warnings
    if not rows:
        warnings.append("No hay filas con contenido para actualizar líneas de producto")
        return updates, warnings

    n = min(len(product_lines), len(rows))
    if len(product_lines) != len(rows):
        warnings.append(
            f"Líneas Odoo ({len(product_lines)}) vs filas UI ({len(rows)}): "
            f"se actualizan producto/cantidad/precio en las primeras {n} por orden"
        )

    for i in range(n):
        line = product_lines[i]
        row = rows[i]
        defer_product = bool(_purchase_line_id_from_row(row))
        _cmd, _zero, expected = _build_line_command(
            row,
            content_rows,
            include_purchase_link=False,
            include_product_id=not defer_product,
        )
        write_vals: Dict[str, Any] = {}

        exp_qty = float(expected["quantity"])
        cur_qty = _parse_amount_loose(line.get("quantity")) or 0.0
        if _floats_differ(cur_qty, exp_qty, tolerance):
            write_vals["quantity"] = exp_qty

        exp_price = float(expected["price_unit"])
        cur_price = _parse_amount_loose(line.get("price_unit")) or 0.0
        if _floats_differ(cur_price, exp_price, tolerance):
            write_vals["price_unit"] = exp_price

        exp_name = _normalize(expected.get("name"))
        cur_name = _normalize(line.get("name"))
        if exp_name and exp_name != cur_name:
            write_vals["name"] = exp_name

        exp_account = expected.get("account_id")
        cur_account = _m2o_id(line.get("account_id"))
        if exp_account and exp_account != cur_account:
            write_vals["account_id"] = exp_account

        exp_product = expected.get("product_id")
        cur_product = _m2o_id(line.get("product_id"))
        if not defer_product and exp_product is not None and exp_product != cur_product:
            write_vals["product_id"] = exp_product

        if not write_vals:
            continue
        updates.append(
            {
                "line_id": line["id"],
                "line_name": line.get("name"),
                "write_vals": write_vals,
            }
        )
    return updates, warnings


def _get_move_product_lines(config: Dict[str, Any], move_id: int) -> List[Dict[str, Any]]:
    """Líneas de factura editables (no impuestos ni secciones/notas)."""
    return odoo_execute_kw_with_config(
        config,
        "account.move.line",
        "search_read",
        [[
            ("move_id", "=", move_id),
            ("display_type", "not in", ["tax", "payment_term", "line_section", "line_note"]),
        ]],
        {
            "fields": _move_product_line_fields(config),
            "order": "sequence,id",
        },
    )


def _get_move_tax_lines(config: Dict[str, Any], move_id: int) -> List[Dict[str, Any]]:
    """Líneas de impuesto de la factura (display_type = tax), como en el script de referencia."""
    return odoo_execute_kw_with_config(
        config,
        "account.move.line",
        "search_read",
        [[("move_id", "=", move_id), ("display_type", "=", "tax")]],
        {
            "fields": [
                "id",
                "name",
                "tax_line_id",
                "account_id",
                "amount_currency",
                "balance",
                "debit",
                "credit",
                "price_subtotal",
            ],
            "order": "sequence,id",
        },
    )


def _tax_line_amount_write_vals(
    amount: float,
    existing_line: Dict[str, Any],
    *,
    due_date_iso: Optional[str] = None,
    account_row: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Valores para pisar montos en una línea account.move.line de tipo impuesto."""
    amount = round(float(amount), 2)
    balance = _parse_amount_loose(existing_line.get("balance"))
    debit = _parse_amount_loose(existing_line.get("debit")) or 0.0
    credit = _parse_amount_loose(existing_line.get("credit")) or 0.0

    use_credit = False
    if balance is not None and balance < 0:
        use_credit = True
    elif credit > debit:
        use_credit = True

    if use_credit:
        vals: Dict[str, Any] = {
            "debit": 0.0,
            "credit": amount,
            "balance": -amount,
            "amount_currency": -amount,
        }
    else:
        vals = {
            "debit": amount,
            "credit": 0.0,
            "balance": amount,
            "amount_currency": amount,
        }
    if due_date_iso and _account_requires_maturity(account_row):
        vals["date_maturity"] = due_date_iso
    return vals


def _ensure_missing_tax_lines_on_move(
    config: Dict[str, Any],
    move_id: int,
    group: List[Dict[str, Any]],
    product_lines: List[Dict[str, Any]],
) -> List[str]:
    """
    Si Odoo no generó líneas tax para impuestos esperados (IVA o IIBB),
    refuerza tax_ids en la primera línea de producto antes de pisar montos.
    """
    warnings: List[str] = []
    expected_amounts = collect_expected_tax_amounts_from_group(group)
    if not expected_amounts or not product_lines:
        return warnings

    tax_lines = _get_move_tax_lines(config, move_id)
    present = {tid for line in tax_lines if (tid := _tax_line_id_raw(line)) is not None}
    missing = [tid for tid in expected_amounts if tid not in present]
    if not missing:
        return warnings

    content_rows = _content_rows_from_group(group)
    if not content_rows:
        return warnings

    line = product_lines[0]
    desired = list(_tax_ids_for_odoo_line(content_rows[0], group))
    seen = set(desired)
    for tid in missing:
        if tid not in seen:
            seen.add(tid)
            desired.append(tid)
    odoo_execute_kw_with_config(
        config,
        "account.move.line",
        "write",
        [[line["id"]], {"tax_ids": [(6, 0, desired)]}],
    )
    warnings.append(
        f"Se reforzaron tax_ids en la primera línea para impuesto(s) faltante(s): {missing}"
    )
    return warnings


def _ensure_iibb_tax_lines_on_move(
    config: Dict[str, Any],
    move_id: int,
    group: List[Dict[str, Any]],
    product_lines: List[Dict[str, Any]],
) -> List[str]:
    """Alias retrocompatible → _ensure_missing_tax_lines_on_move."""
    return _ensure_missing_tax_lines_on_move(config, move_id, group, product_lines)


def _apply_tax_line_amount_overwrites(
    config: Dict[str, Any],
    move_id: int,
    group: List[Dict[str, Any]],
    *,
    due_date_iso: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], List[str], Dict[int, float]]:
    """Pisa montos en líneas display_type=tax con los valores de FacturIA."""
    expected_amounts = collect_expected_tax_amounts_from_group(group)
    product_lines = _get_move_product_lines(config, move_id)
    ensure_warnings = _ensure_missing_tax_lines_on_move(
        config, move_id, group, product_lines
    )
    tax_lines = _get_move_tax_lines(config, move_id)
    tax_line_by_id = {line["id"]: line for line in tax_lines}
    tax_account_ids = [_m2o_id(line.get("account_id")) for line in tax_lines]
    tax_accounts = _account_rows_by_id(config, [a for a in tax_account_ids if a])

    planned_amounts, warnings = plan_tax_line_amount_overwrites(tax_lines, expected_amounts)
    warnings = ensure_warnings + warnings
    tax_line_updates: List[Dict[str, Any]] = []
    for item in planned_amounts:
        existing = tax_line_by_id.get(item["line_id"], {})
        acc_id = _m2o_id(existing.get("account_id"))
        write_vals = _tax_line_amount_write_vals(
            item["new_amount"],
            existing,
            due_date_iso=due_date_iso,
            account_row=tax_accounts.get(acc_id) if acc_id else None,
        )
        odoo_execute_kw_with_config(
            config,
            "account.move.line",
            "write",
            [[item["line_id"]], write_vals],
        )
        tax_line_updates.append({**item, "write_vals": write_vals})

    if due_date_iso:
        _ensure_move_line_maturity(config, move_id, due_date_iso)

    return tax_line_updates, warnings, expected_amounts


def plan_tax_line_amount_overwrites(
    tax_lines: List[Dict[str, Any]],
    expected_amounts: Dict[int, float],
    *,
    tolerance: float = 0.02,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Planifica sobrescritura de montos en líneas display_type=tax,
    emparejando por tax_line_id con los montos que vienen de FacturIA.
    """
    updates: List[Dict[str, Any]] = []
    warnings: List[str] = []
    matched: set = set()

    for line in tax_lines:
        tid = _tax_line_id_raw(line)
        if tid is None:
            continue
        expected = expected_amounts.get(tid)
        if expected is None:
            continue
        matched.add(tid)
        current = _line_amount_abs(line)
        if abs(current - expected) <= tolerance:
            continue
        updates.append(
            {
                "line_id": line["id"],
                "tax_line_id": tid,
                "line_name": line.get("name"),
                "old_amount": current,
                "new_amount": expected,
            }
        )

    for tid, expected in expected_amounts.items():
        if tid not in matched:
            warnings.append(
                f"Impuesto id {tid} (${expected:.2f}): no hay línea tax en Odoo para sobreescribir"
            )

    return updates, warnings


def _po_link_write_vals(row: Dict[str, Any], po_line_id: int) -> Dict[str, Any]:
    """Vincula OC y producto en un solo write (evita auto-match parcial de Odoo)."""
    write_vals: Dict[str, Any] = {"purchase_line_id": po_line_id}
    product_id = _int_id(row.get("invoice_line_ids/product_id"))
    if product_id:
        write_vals["product_id"] = product_id
    return write_vals


def sync_move_taxes_from_group(
    config: Dict[str, Any],
    move_id: int,
    group: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Sincroniza una factura ya creada en Odoo (borrador) con las filas UI:

    1. invoice_origin del encabezado.
    2. product_id, cantidad, precio, etiqueta y cuenta en líneas de producto.
    3. tax_ids en líneas de producto.
    4. Montos en líneas display_type=tax (iva_monto / otros_impuestos_monto).
    5. Vínculos OC (purchase_line_id + product_id) — al final, en un solo write por línea.
    """
    move_rows = odoo_execute_kw_with_config(
        config,
        "account.move",
        "read",
        [[move_id]],
        {
            "fields": [
                "id",
                "name",
                "state",
                "l10n_latam_document_number",
                "invoice_origin",
                "invoice_date",
                "invoice_date_due",
            ]
        },
    )
    if not move_rows:
        raise ValueError(f"Factura {move_id} no encontrada")
    move = move_rows[0]
    state = _normalize(move.get("state"))
    if state and state != "draft":
        raise ValueError(
            f"Factura {move.get('name') or move_id} no está en borrador (state={state})"
        )

    warnings: List[str] = []
    # sanitize + refresh ya corrieron en _prepare_rows_for_import; no repetir aquí.

    header_plan = plan_move_header_updates(move, group)
    header_update: Optional[Dict[str, Any]] = None
    due_date_iso = _invoice_due_date_from_group(group)
    if header_plan:
        odoo_execute_kw_with_config(
            config,
            "account.move",
            "write",
            [[move_id], header_plan],
        )
        header_update = dict(header_plan)
        move = {**move, **header_plan}
        due_date_iso = header_plan.get("invoice_date_due") or due_date_iso

    if due_date_iso:
        _ensure_move_line_maturity(config, move_id, due_date_iso)

    product_lines = _get_move_product_lines(config, move_id)

    origin_plan = plan_invoice_origin_update(move.get("invoice_origin"), group)
    invoice_origin_update: Optional[Dict[str, Any]] = None
    if origin_plan:
        origin_vals: Dict[str, Any] = (
            {"invoice_origin": origin_plan["new_invoice_origin"]}
            if origin_plan["new_invoice_origin"]
            else {"invoice_origin": False}
        )
        odoo_execute_kw_with_config(
            config,
            "account.move",
            "write",
            [[move_id], origin_vals],
        )
        invoice_origin_update = {**origin_plan, "write_vals": origin_vals}

    planned_content, warnings_content = plan_product_line_content_updates(product_lines, group)
    warnings.extend(warnings_content)
    content_line_updates: List[Dict[str, Any]] = []
    for item in planned_content:
        odoo_execute_kw_with_config(
            config,
            "account.move.line",
            "write",
            [[item["line_id"]], item["write_vals"]],
        )
        content_line_updates.append(item)
    if content_line_updates:
        product_lines = _get_move_product_lines(config, move_id)

    planned_ids, warnings_ids = plan_line_tax_updates(product_lines, group)
    warnings.extend(warnings_ids)

    product_updates: List[Dict[str, Any]] = []
    for item in planned_ids:
        odoo_execute_kw_with_config(
            config,
            "account.move.line",
            "write",
            [[item["line_id"]], {"tax_ids": [(6, 0, item["new_tax_ids"])]}],
        )
        product_updates.append(item)

    if due_date_iso:
        maturity_fixed = _ensure_move_line_maturity(config, move_id, due_date_iso)
        if maturity_fixed:
            warnings.append(
                f"Se completó fecha límite en {maturity_fixed} apunte(s) contable(s)"
            )

    product_lines = _get_move_product_lines(config, move_id)
    ui_rows = _content_rows_from_group(group)
    purchase_line_updates: List[Dict[str, Any]] = []
    if _move_line_supports_purchase_link(config):
        planned_po, warnings_po = plan_purchase_line_updates(
            product_lines, group, config=config
        )
        warnings.extend(warnings_po)
        used_po_line_ids: set = set()
        for item in planned_po:
            po_line_id = item["new_purchase_line_id"]
            if not po_line_id or po_line_id in used_po_line_ids:
                if po_line_id in used_po_line_ids:
                    warnings.append(
                        f"OC línea {po_line_id} duplicada; se omite en {item.get('line_name') or '?'}"
                    )
                continue
            row_idx = int(item.get("row_index", 0))
            ui_row = ui_rows[row_idx] if row_idx < len(ui_rows) else {}
            write_vals = _po_link_write_vals(ui_row, int(po_line_id))
            try:
                odoo_execute_kw_with_config(
                    config,
                    "account.move.line",
                    "write",
                    [[item["line_id"]], write_vals],
                )
                used_po_line_ids.add(int(po_line_id))
                purchase_line_updates.append({**item, "write_vals": write_vals})
            except Exception as exc:
                warnings.append(
                    f"OC línea {po_line_id} en {item.get('line_name') or '?'}: no se pudo vincular ({exc})"
                )

    # Después de vínculos OC: Odoo puede recalcular impuestos; pisar montos al final.
    tax_line_updates, warnings_amt, expected_amounts = _apply_tax_line_amount_overwrites(
        config,
        move_id,
        group,
        due_date_iso=due_date_iso,
    )
    warnings.extend(warnings_amt)

    return {
        "move_id": move_id,
        "name": move.get("name"),
        "document_number": move.get("l10n_latam_document_number"),
        "state": move.get("state"),
        "product_lines_updated": len(product_updates),
        "content_lines_updated": len(content_line_updates),
        "purchase_lines_updated": len(purchase_line_updates),
        "tax_lines_updated": len(tax_line_updates),
        "lines_updated": len(tax_line_updates),
        "product_updates": product_updates,
        "content_line_updates": content_line_updates,
        "purchase_line_updates": purchase_line_updates,
        "invoice_origin_updated": invoice_origin_update is not None,
        "invoice_origin_update": invoice_origin_update,
        "tax_line_updates": tax_line_updates,
        "expected_tax_amounts": expected_amounts,
        "warnings": warnings,
    }


def update_move_taxes_from_group(
    config: Dict[str, Any],
    move_id: int,
    group: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Alias retrocompatible → sync_move_taxes_from_group."""
    return sync_move_taxes_from_group(config, move_id, group)


def _build_move_vals(group: List[Dict[str, Any]]) -> Dict[str, Any]:
    header = group[0]
    vals: Dict[str, Any] = {
        "move_type": "in_invoice",
        "partner_id": _int_id(header.get("partner_id")),
        "journal_id": _int_id(header.get("journal_id")),
        "invoice_date": _date_ddmm_to_iso(header.get("invoice_date")),
    }
    doc_number = _normalize(header.get("l10n_latam_document_number"))
    if doc_number:
        vals["l10n_latam_document_number"] = doc_number
        # ref es almacenado y searchable (Odoo 19 latam doc number a menudo no lo es).
        vals["ref"] = doc_number
    due = _invoice_due_date_from_group(group)
    if due:
        vals["invoice_date_due"] = due
    doc_type_id = _int_id(header.get("l10n_latam_document_type_id"))
    if doc_type_id:
        vals["l10n_latam_document_type_id"] = doc_type_id
    rubro_id = _int_id(header.get("x_studio_category"))
    if rubro_id and supports_rubro_field():
        vals["x_studio_category"] = rubro_id
    invoice_origin = _invoice_origin_from_group(group)
    if invoice_origin:
        vals["invoice_origin"] = invoice_origin

    line_cmds = [
        _build_line_command(
            r,
            group,
            include_purchase_link=False,
            include_product_id=False,
        )
        for r in group
        if _line_has_content(r)
    ]
    vals["invoice_line_ids"] = line_cmds
    return vals


def _canonical_document_number(doc: str) -> str:
    parts = doc.split("-")
    return "-".join(p.lstrip("0") or "0" for p in parts)


def _document_numbers_match(left: Any, right: Any) -> bool:
    """Compara números de comprobante; Odoo TEST a veces ignora el filtro '=' en search."""
    a = _normalize(left)
    b = _normalize(right)
    if not a or not b:
        return False
    if a == b:
        return True
    return _canonical_document_number(a) == _canonical_document_number(b)


def _move_matches_document_number(move: Dict[str, Any], doc_number: str) -> bool:
    """Match por latam doc, ref o name (latam doc suele ser no almacenado en Odoo 19)."""
    if not doc_number:
        return False
    for key in ("l10n_latam_document_number", "ref"):
        if _document_numbers_match(move.get(key), doc_number):
            return True
    name = _normalize(move.get("name"))
    if not name:
        return False
    if _document_numbers_match(name, doc_number):
        return True
    canon_doc = _canonical_document_number(doc_number)
    canon_name = _canonical_document_number(name)
    if canon_name == canon_doc:
        return True
    if canon_name.endswith(canon_doc) or f"-{canon_doc}" in canon_name:
        return True
    return False


_EXISTING_MOVE_FIELDS = ["id", "name", "state", "l10n_latam_document_number", "ref"]


def _find_existing_move(
    config: Dict[str, Any],
    partner_id: int,
    doc_number: str,
) -> Optional[Dict[str, Any]]:
    """
    Busca factura de proveedor existente por proveedor + número de comprobante.

    No usar l10n_latam_document_number en el domain: en Odoo 19+ suele ser computed
    sin store. ref (almacenado) + filtro en Python sobre los candidatos del proveedor.
    """
    base_domain = [
        ("move_type", "=", "in_invoice"),
        ("partner_id", "=", partner_id),
    ]
    search_domains: List[List[Any]] = [
        base_domain + [("ref", "=", doc_number)],
        base_domain,
    ]
    for domain in search_domains:
        limit = 50 if len(domain) > 2 else 200
        rows = odoo_execute_kw_with_config(
            config,
            "account.move",
            "search_read",
            [domain],
            {
                "fields": _EXISTING_MOVE_FIELDS,
                "limit": limit,
                "order": "id desc",
            },
        )
        for row in rows or []:
            if _move_matches_document_number(row, doc_number):
                return row
    return None


def _tax_sync_summary(doc_number: str, result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "document_number": doc_number,
        "move_id": result.get("move_id"),
        "name": result.get("name"),
        "state": result.get("state"),
        "lines_updated": result.get("tax_lines_updated", result.get("lines_updated", 0)),
        "product_lines_updated": result.get("product_lines_updated", 0),
        "content_lines_updated": result.get("content_lines_updated", 0),
        "purchase_lines_updated": result.get("purchase_lines_updated", 0),
        "tax_lines_updated": result.get("tax_lines_updated", 0),
        "invoice_origin_updated": result.get("invoice_origin_updated", False),
        "expected_tax_amounts": result.get("expected_tax_amounts", {}),
        "product_updates": result.get("product_updates", []),
        "content_line_updates": result.get("content_line_updates", []),
        "purchase_line_updates": result.get("purchase_line_updates", []),
        "invoice_origin_update": result.get("invoice_origin_update"),
        "tax_line_updates": result.get("tax_line_updates", []),
        "updates": result.get("tax_line_updates", result.get("updates", [])),
        "warnings": result.get("warnings", []),
    }


def _import_config_error_message() -> str:
    if is_odoo_sudata_profile():
        return (
            "Faltan variables Odoo Sudata (ODOO_BASE_URL_SUDATA o URL_SUDATA, "
            "ODOO_USER_SUDATA o USERNAME_SUDATA, y "
            "ODOO_API_KEY_SUDATA u ODOO_PASSWORD_SUDATA; ODOO_DB_SUDATA opcional)."
        )
    if is_odoo_aliare_profile():
        return (
            "Faltan variables Odoo Aliare (ODOO_BASE_URL_ALIARE, "
            "ODOO_USER_ALIARE u ODOO_USER_ID_ALIARE con email, y "
            "ODOO_API_KEY_ALIARE u ODOO_PASSWORD_ALIARE; ODOO_DB_ALIARE opcional)."
        )
    return (
        "Faltan variables Odoo Dinner (ODOO_BASE_URL, "
        "ODOO_USER_ID u ODOO_USER, y ODOO_PASSWORD u ODOO_API_KEY; ODOO_DB opcional)."
    )


def _import_odoo_target_label() -> str:
    if is_odoo_sudata_profile():
        return "Odoo Sudata"
    if is_odoo_aliare_profile():
        return "Odoo Aliare"
    return "Odoo Dinner"


def import_rows_to_odoo(
    rows: List[Dict[str, Any]],
    *,
    skip_duplicates: bool = True,
    update_taxes_if_exists: bool = True,
) -> Dict[str, Any]:
    """
    Crea facturas de proveedor en borrador en Odoo (Dinner o Aliare según perfil).
    Tras crear (o si ya existe y update_taxes_if_exists=True), sincroniza OC, impuestos
    y montos de líneas tax con las filas UI actuales.
    Devuelve {ok, created, updated_taxes, skipped, errors}.
    """
    config = get_odoo_import_config()
    if not is_odoo_config_ready(config):
        return {
            "ok": False,
            "error": _import_config_error_message(),
        }

    err = validate_rows_for_import(rows)
    if err:
        return {"ok": False, "error": err}

    uid = get_odoo_uid_from_config(config)
    if uid is None:
        return {
            "ok": False,
            "error": f"No se pudo autenticar en {_import_odoo_target_label()} (revisá usuario/contraseña/db).",
        }

    created: List[Dict[str, Any]] = []
    updated_taxes: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    groups, import_warnings = _prepare_rows_for_import(config, rows)

    for group in groups:
        header = group[0]
        doc_number = _normalize(header.get("l10n_latam_document_number"))
        partner_id = _int_id(header.get("partner_id"))
        try:
            group_warnings = list(import_warnings)
            import_warnings = []
            if skip_duplicates and partner_id and doc_number:
                existing = _find_existing_move(config, partner_id, doc_number)
                if existing:
                    if update_taxes_if_exists:
                        result = sync_move_taxes_from_group(
                            config, int(existing["id"]), group
                        )
                        if group_warnings:
                            result.setdefault("warnings", []).extend(group_warnings)
                        updated_taxes.append(_tax_sync_summary(doc_number, result))
                    else:
                        skipped.append(
                            {
                                "document_number": doc_number,
                                "move_id": existing.get("id"),
                                "name": existing.get("name"),
                                "state": existing.get("state"),
                                "reason": "already_exists",
                            }
                        )
                    continue

            vals = _build_move_vals(group)
            move_id = odoo_execute_kw_with_config(config, "account.move", "create", [vals])
            move_id = int(move_id)
            read = odoo_execute_kw_with_config(
                config,
                "account.move",
                "read",
                [[move_id]],
                {"fields": ["id", "name", "state", "l10n_latam_document_number"]},
            )
            info = read[0] if read else {"id": move_id}
            created.append(
                {
                    "id": info.get("id", move_id),
                    "name": info.get("name"),
                    "state": info.get("state"),
                    "document_number": info.get("l10n_latam_document_number") or doc_number,
                }
            )
            try:
                tax_result = sync_move_taxes_from_group(config, move_id, group)
                if group_warnings:
                    tax_result.setdefault("warnings", []).extend(group_warnings)
                updated_taxes.append(_tax_sync_summary(doc_number, tax_result))
            except Exception as tax_err:
                errors.append(
                    {
                        "document_number": doc_number,
                        "move_id": move_id,
                        "error": f"Factura creada pero falló sync de impuestos: {tax_err}",
                    }
                )
        except Exception as e:
            errors.append({"document_number": doc_number, "error": str(e)})

    had_work = bool(created) or bool(updated_taxes)
    ok = had_work and not errors
    if had_work and errors:
        ok = False
    if not had_work and errors:
        ok = False
    if not had_work and not errors and not skipped:
        return {"ok": False, "error": "No se creó ni actualizó ningún comprobante."}

    return {
        "ok": ok or had_work,
        "uid": uid,
        "db": config.get("db"),
        "base_url": config.get("base_url"),
        "created": created,
        "updated_taxes": updated_taxes,
        "skipped": skipped,
        "errors": errors,
    }
