"""
Importación de filas UI → facturas de proveedor en Odoo (account.move, in_invoice).
Usa credenciales ODOO_*_TEST del .env.
"""

from __future__ import annotations

import re
from datetime import date
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from odoo_api import get_odoo_test_config, get_odoo_uid_from_config, is_odoo_config_ready, odoo_execute_kw_with_config
from padron_taxes import IVA_TAX_IDS, build_csv_tax_ids_dot_id, resolve_tax_label_to_id, tax_id_for_csv_export

_DATE_DD_MM = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _normalize(s: Any) -> str:
    if s is None:
        return ""
    return " ".join(str(s).strip().split())


def _int_id(raw: Any) -> Optional[int]:
    s = _normalize(raw)
    if not s or not s.isdigit():
        return None
    return int(s)


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


def _build_line_command(row: Dict[str, Any]) -> Tuple[int, int, Dict[str, Any]]:
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
    tax_ids = _tax_ids_from_row(row)
    if tax_ids:
        vals["tax_ids"] = [(6, 0, tax_ids)]
    return (0, 0, vals)


def _content_rows_from_group(group: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in group if _line_has_content(r)]


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


def collect_expected_tax_amounts_from_group(group: List[Dict[str, Any]]) -> Dict[int, float]:
    """
    Montos de impuesto esperados desde FacturIA (filas UI), indexados por account.tax id.
    """
    amounts: Dict[int, float] = defaultdict(float)

    for row in group:
        if not isinstance(row, dict):
            continue
        tax_ids = _tax_ids_from_row(row)
        if not tax_ids:
            continue

        iva_amt = _parse_amount_loose(row.get("iva_monto"))
        if iva_amt is not None and iva_amt > 0:
            iva_tid_s = tax_id_for_csv_export(row)
            iva_tid: Optional[int] = None
            if iva_tid_s and iva_tid_s.isdigit():
                iva_tid = int(iva_tid_s)
            else:
                for tid in tax_ids:
                    if tid in IVA_TAX_IDS:
                        iva_tid = tid
                        break
            if iva_tid is not None:
                amounts[iva_tid] += iva_amt

        other_ids = [tid for tid in tax_ids if tid not in IVA_TAX_IDS]
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
        tax_ids = _tax_ids_from_row(row)
        if not tax_ids:
            line_name = _normalize(line.get("name")) or f"#{line.get('id')}"
            warnings.append(f"Línea {i + 1} ({line_name}): sin tax_ids en la fila UI, se omite")
            continue
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
        {"fields": ["id", "name", "sequence", "tax_ids"], "order": "sequence,id"},
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
                "amount_currency",
                "balance",
                "debit",
                "credit",
                "price_subtotal",
            ],
            "order": "sequence,id",
        },
    )


def _tax_line_amount_write_vals(amount: float, existing_line: Dict[str, Any]) -> Dict[str, float]:
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
        return {
            "debit": 0.0,
            "credit": amount,
            "balance": -amount,
            "amount_currency": -amount,
        }
    return {
        "debit": amount,
        "credit": 0.0,
        "balance": amount,
        "amount_currency": amount,
    }


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


def sync_move_taxes_from_group(
    config: Dict[str, Any],
    move_id: int,
    group: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Sincroniza impuestos de una factura ya creada en Odoo (borrador):

    1. Ajusta tax_ids en líneas de producto (tipos de impuesto correctos).
    2. Vuelve a leer la factura y obtiene líneas display_type=tax.
    3. Sobreescribe montos de esas líneas con iva_monto / otros_impuestos_monto de FacturIA.
    """
    move_rows = odoo_execute_kw_with_config(
        config,
        "account.move",
        "read",
        [[move_id]],
        {"fields": ["id", "name", "state", "l10n_latam_document_number"]},
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

    expected_amounts = collect_expected_tax_amounts_from_group(group)
    tax_lines = _get_move_tax_lines(config, move_id)
    tax_line_by_id = {line["id"]: line for line in tax_lines}

    planned_amounts, warnings_amt = plan_tax_line_amount_overwrites(tax_lines, expected_amounts)
    warnings.extend(warnings_amt)

    tax_line_updates: List[Dict[str, Any]] = []
    for item in planned_amounts:
        existing = tax_line_by_id.get(item["line_id"], {})
        write_vals = _tax_line_amount_write_vals(item["new_amount"], existing)
        odoo_execute_kw_with_config(
            config,
            "account.move.line",
            "write",
            [[item["line_id"]], write_vals],
        )
        tax_line_updates.append({**item, "write_vals": write_vals})

    return {
        "move_id": move_id,
        "name": move.get("name"),
        "document_number": move.get("l10n_latam_document_number"),
        "state": move.get("state"),
        "product_lines_updated": len(product_updates),
        "tax_lines_updated": len(tax_line_updates),
        "lines_updated": len(tax_line_updates),
        "product_updates": product_updates,
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
        "l10n_latam_document_number": _normalize(header.get("l10n_latam_document_number")),
        "invoice_date": _date_ddmm_to_iso(header.get("invoice_date")),
    }
    due = _date_ddmm_to_iso(header.get("invoice_date_due"))
    if due:
        vals["invoice_date_due"] = due
    doc_type_id = _int_id(header.get("l10n_latam_document_type_id"))
    if doc_type_id:
        vals["l10n_latam_document_type_id"] = doc_type_id
    rubro_id = _int_id(header.get("x_studio_category"))
    if rubro_id:
        vals["x_studio_category"] = rubro_id

    line_cmds = [_build_line_command(r) for r in group if _line_has_content(r)]
    vals["invoice_line_ids"] = line_cmds
    return vals


def _document_numbers_match(left: Any, right: Any) -> bool:
    """Compara números de comprobante; Odoo TEST a veces ignora el filtro '=' en search."""
    a = _normalize(left)
    b = _normalize(right)
    if not a or not b:
        return False
    if a == b:
        return True
    # Variante sin ceros a la izquierda en cada tramo (00008-… vs 0008-…)
    def _canonical(doc: str) -> str:
        parts = doc.split("-")
        return "-".join(p.lstrip("0") or "0" for p in parts)

    return _canonical(a) == _canonical(b)


def _find_existing_move(
    config: Dict[str, Any],
    partner_id: int,
    doc_number: str,
) -> Optional[Dict[str, Any]]:
    domain = [
        ("move_type", "=", "in_invoice"),
        ("partner_id", "=", partner_id),
        ("l10n_latam_document_number", "=", doc_number),
    ]
    rows = odoo_execute_kw_with_config(
        config,
        "account.move",
        "search_read",
        [domain],
        {"fields": ["id", "name", "state", "l10n_latam_document_number"], "limit": 50},
    )
    for row in rows or []:
        if _document_numbers_match(row.get("l10n_latam_document_number"), doc_number):
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
        "tax_lines_updated": result.get("tax_lines_updated", 0),
        "expected_tax_amounts": result.get("expected_tax_amounts", {}),
        "product_updates": result.get("product_updates", []),
        "tax_line_updates": result.get("tax_line_updates", []),
        "updates": result.get("tax_line_updates", result.get("updates", [])),
        "warnings": result.get("warnings", []),
    }


def import_rows_to_odoo_test(
    rows: List[Dict[str, Any]],
    *,
    skip_duplicates: bool = True,
    update_taxes_if_exists: bool = True,
) -> Dict[str, Any]:
    """
    Crea facturas de proveedor en borrador en Odoo TEST.
    Tras crear (o si ya existe y update_taxes_if_exists=True), relee la factura,
    localiza líneas display_type=tax y sobreescribe montos con FacturIA.
    Devuelve {ok, created, updated_taxes, skipped, errors}.
    """
    config = get_odoo_test_config()
    if not is_odoo_config_ready(config):
        return {
            "ok": False,
            "error": "Faltan ODOO_API_TEST, ODOO_DB_TEST, ODOO_USER_TEST, ODOO_PASSWORD_TEST en .env",
        }

    err = validate_rows_for_import(rows)
    if err:
        return {"ok": False, "error": err}

    uid = get_odoo_uid_from_config(config)
    if uid is None:
        return {"ok": False, "error": "No se pudo autenticar en Odoo TEST (revisá usuario/contraseña/db)."}

    created: List[Dict[str, Any]] = []
    updated_taxes: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    groups = [propagate_invoice_headers(g) for g in group_rows_into_invoices(rows)]

    for group in groups:
        header = group[0]
        doc_number = _normalize(header.get("l10n_latam_document_number"))
        partner_id = _int_id(header.get("partner_id"))
        try:
            if skip_duplicates and partner_id and doc_number:
                existing = _find_existing_move(config, partner_id, doc_number)
                if existing:
                    if update_taxes_if_exists:
                        result = sync_move_taxes_from_group(
                            config, int(existing["id"]), group
                        )
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
