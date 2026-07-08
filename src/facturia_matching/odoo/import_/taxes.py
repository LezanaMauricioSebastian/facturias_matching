"""Tax ID resolution, expected amounts, and tax-line Odoo read/write."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from facturia_matching.core.comprobante_tax import (
    classify_comprobante_tax_mode,
    fac_iva_montos,
    iva_pct_to_rate,
    line_iva_monto,
)
from facturia_matching.odoo.api import odoo_execute_kw_with_config
from facturia_matching.padron.taxes import (
    build_csv_tax_ids_dot_id,
    is_iva_tax_id,
    iva_pct_requires_line_tax,
    resolve_tax_label_to_id,
    tax_id_for_csv_export,
)

from facturia_matching.odoo.import_._utils import (
    _content_rows_from_group,
    _is_first_content_row,
    _m2o_id,
    _normalize,
    _parse_amount_loose,
)

_PAYABLE_RECEIVABLE_ACCOUNT_TYPES = frozenset(
    {"asset_receivable", "liability_payable", "receivable", "payable"}
)


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
    ids_to_fix: List[int] = []
    for line in lines or []:
        acc_id = _m2o_id(line.get("account_id"))
        if not acc_id or not _account_requires_maturity(accounts.get(acc_id)):
            continue
        if _normalize(line.get("date_maturity")):
            continue
        ids_to_fix.append(int(line["id"]))
    if ids_to_fix:
        odoo_execute_kw_with_config(
            config,
            "account.move.line",
            "write",
            [ids_to_fix, {"date_maturity": due_date_iso}],
        )
        fixed = len(ids_to_fix)
    return fixed


def _ensure_payment_term_maturity(
    config: Dict[str, Any],
    move_id: int,
    due_date_iso: str,
) -> int:
    """Compat: delega en _ensure_move_line_maturity (cubre payment_term y demás AP/AR)."""
    return _ensure_move_line_maturity(config, move_id, due_date_iso)


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


def _tax_ids_on_line(line: Dict[str, Any]) -> List[int]:
    """Normaliza tax_ids de una línea Odoo (lista de int o m2o)."""
    raw = line.get("tax_ids") or []
    out: List[int] = []
    for x in raw:
        if isinstance(x, int):
            out.append(x)
        elif isinstance(x, (list, tuple)) and x:
            try:
                out.append(int(x[0]))
            except (TypeError, ValueError):
                continue
    return out


def _trigger_product_line_tax_recompute(
    config: Dict[str, Any],
    move_id: int,
    line_id: int,
) -> None:
    """Toca la línea vía account.move para que Odoo sincronice líneas tax sin borrar tax_ids."""
    odoo_execute_kw_with_config(
        config,
        "account.move",
        "write",
        [[move_id], {"line_ids": [(1, int(line_id), {})]}],
    )


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
    line_id = int(line["id"])
    desired = list(_tax_ids_for_odoo_line(content_rows[0], group))
    seen = set(desired)
    for tid in missing:
        if tid not in seen:
            seen.add(tid)
            desired.append(tid)
    current = _tax_ids_on_line(line)
    current_set = set(current)
    desired_set = set(desired)
    to_add = [tid for tid in missing if tid not in current_set]

    if not to_add and current_set == desired_set:
        # tax_ids ya correctos pero Odoo no generó la línea tax: recalcular sin borrar impuestos.
        qty = _parse_amount_loose(line.get("quantity")) or 1.0
        price = _parse_amount_loose(line.get("price_unit")) or 0.0
        odoo_execute_kw_with_config(
            config,
            "account.move.line",
            "write",
            [[line_id], {"quantity": qty, "price_unit": price}],
        )
        _trigger_product_line_tax_recompute(config, move_id, line_id)
        warnings.append(
            f"Se forzó recálculo de impuestos en la primera línea para: {missing}"
        )
        return warnings

    tax_cmds: List[Any] = [(4, tid) for tid in to_add] if to_add else [(6, 0, desired)]
    odoo_execute_kw_with_config(
        config,
        "account.move.line",
        "write",
        [[line_id], {"tax_ids": tax_cmds}],
    )
    _trigger_product_line_tax_recompute(config, move_id, line_id)
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
    from facturia_matching.odoo.import_.move_lines import (
        _batch_write_move_lines,
        _get_move_product_lines,
    )

    expected_amounts = collect_expected_tax_amounts_from_group(group)
    all_warnings: List[str] = []
    tax_line_updates: List[Dict[str, Any]] = []

    for pass_idx in range(2):
        product_lines = _get_move_product_lines(config, move_id)
        ensure_warnings = _ensure_missing_tax_lines_on_move(
            config, move_id, group, product_lines
        )
        all_warnings.extend(ensure_warnings)
        tax_lines = _get_move_tax_lines(config, move_id)
        tax_line_by_id = {line["id"]: line for line in tax_lines}
        tax_account_ids = [_m2o_id(line.get("account_id")) for line in tax_lines]
        tax_accounts = _account_rows_by_id(config, [a for a in tax_account_ids if a])

        planned_amounts, warnings = plan_tax_line_amount_overwrites(
            tax_lines, expected_amounts
        )
        all_warnings.extend(warnings)
        tax_line_updates = []
        tax_batch: List[Dict[str, Any]] = []
        for item in planned_amounts:
            existing = tax_line_by_id.get(item["line_id"], {})
            acc_id = _m2o_id(existing.get("account_id"))
            write_vals = _tax_line_amount_write_vals(
                item["new_amount"],
                existing,
                due_date_iso=due_date_iso,
                account_row=tax_accounts.get(acc_id) if acc_id else None,
            )
            tax_batch.append(
                {
                    "line_id": item["line_id"],
                    "line_name": item.get("line_name"),
                    "write_vals": write_vals,
                }
            )
            tax_line_updates.append({**item, "write_vals": write_vals})
        if tax_batch:
            _batch_write_move_lines(config, move_id, tax_batch, all_warnings, context="impuesto")

        has_missing = any("no hay línea tax" in w for w in warnings)
        if not has_missing or pass_idx == 1:
            break

    if due_date_iso:
        _ensure_move_line_maturity(config, move_id, due_date_iso)

    return tax_line_updates, all_warnings, expected_amounts
