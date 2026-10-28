"""Proyecta un export_template de FacturIA sobre el matching Excel de un proceso."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

# source_value → clave de listas del padrón Excel.
# rubro / diario no tienen lista en el Sheet: is_dropdown true y options [].
DROPDOWN_SOURCES: Dict[str, str] = {
    "cabecera.proveedor.nombre": "proveedores",
    "cabecera.proveedor.razon_social": "proveedores",
    "cabecera.concepto": "conceptos",
    "cabecera.forma_de_pago": "formas_pago",
    "cabecera.FormaPago": "formas_pago",
    "items[].producto": "productos",
    "cabecera.rubro": "rubros",
    "cabecera.diario": "diarios",
}

# Match Excel pisa el valor FacturIA cuando viene no vacío.
_HEADER_EXCEL = {
    "cabecera.proveedor.nombre": "__excel_proveedor",
    "cabecera.proveedor.razon_social": "__excel_proveedor",
    "cabecera.concepto": "__excel_concepto",
    "cabecera.forma_de_pago": "__excel_forma_pago",
    "cabecera.FormaPago": "__excel_forma_pago",
}
_ITEM_EXCEL = {
    "items[].producto": "__excel_producto",
}


def is_dropdown_source(source_value: str, source_type: str = "canonical") -> bool:
    if str(source_type or "").strip().lower() == "static":
        return False
    return str(source_value or "").strip() in DROPDOWN_SOURCES


def facturas_from_json_data(raw: Any) -> List[Dict[str, Any]]:
    """Facturas en el mismo orden que parse_process_json (salta wraps sin json)."""
    obj = _unwrap_json(raw)
    if not isinstance(obj, dict):
        return []
    out: List[Dict[str, Any]] = []
    for fac_wrap in obj.get("facturas") or []:
        j = fac_wrap.get("json") if isinstance(fac_wrap, dict) else None
        if not isinstance(j, dict):
            continue
        fac = j.get("factura") if isinstance(j.get("factura"), dict) else {}
        out.append(fac)
    return out


def project_template(
    template: Dict[str, Any],
    facturas: Sequence[Dict[str, Any]],
    excel_rows: Sequence[Dict[str, Any]],
    padron: Optional[Dict[str, Any]] = None,
    lookups: Optional[Dict[Any, Any]] = None,
    gastos_records: Optional[Sequence[Dict[str, Any]]] = None,
    company_id: int = 0,
) -> List[Dict[str, Any]]:
    """Una entrada por hoja: columns (con is_dropdown), options y rows."""
    by_idx: Dict[int, List[Dict[str, Any]]] = {}
    for row in excel_rows or []:
        if not isinstance(row, dict):
            continue
        idx = row.get("__comprobante_idx")
        try:
            key = int(idx) if idx is not None and str(idx).strip() != "" else 0
        except (TypeError, ValueError):
            key = 0
        by_idx.setdefault(key, []).append(row)

    lists = _option_lists(padron or {})
    sheets_out: List[Dict[str, Any]] = []
    for sheet in template.get("sheets") or []:
        columns = list(sheet.get("columns") or [])
        col_meta = [_column_meta(c) for c in columns]
        options: Dict[str, List[str]] = {}
        for col, meta in zip(columns, col_meta):
            if not meta["is_dropdown"]:
                continue
            from facturia_matching.padron.template_lookup import lookup_key, options_for

            if lookup_key(col):
                options[meta["name"]] = options_for(col, lookups)
                continue
            key = DROPDOWN_SOURCES.get(str(col.get("source_value") or "").strip(), "")
            options[meta["name"]] = list(lists.get(key) or [])
        from facturia_matching.padron.column_suggest import build_lookup_decisions

        decisions = build_lookup_decisions(
            columns,
            facturas,
            by_idx,
            lookups,
            gastos_records,
            company_id=company_id,
        )
        sheets_out.append(
            {
                "name": str(sheet.get("name") or ""),
                "columns": col_meta,
                "options": options,
                "rows": _sheet_rows(
                    columns, facturas, by_idx, lookups, decisions, options
                ),
            }
        )
    return sheets_out


def _column_meta(col: Dict[str, Any]) -> Dict[str, Any]:
    from facturia_matching.padron.template_lookup import column_role, lookup_key, suggest_enabled

    source = "" if col.get("source_value") is None else str(col.get("source_value"))
    source_type = str(col.get("source_type") or "canonical")
    listed = lookup_key(col) is not None
    suggested = suggest_enabled(col) and bool(column_role(col))
    return {
        "name": str(col.get("header_label") or ""),
        "source": source,
        "is_dropdown": listed or suggested or is_dropdown_source(source, source_type),
    }


def _sheet_has_item_columns(columns: Sequence[Dict[str, Any]]) -> bool:
    for col in columns or []:
        source = str(col.get("source_value") or "").strip()
        if source.startswith("items[].") or source.startswith("items."):
            return True
    return False


def _sheet_expands_items(columns: Sequence[Dict[str, Any]]) -> bool:
    """Una fila por ítem solo si la hoja tiene columnas items[].

    Coincidir con no abre filas. La preview de Gastos es una fila por factura
    (el pie dice «N filas»). Si devolvemos una por ítem, FacturIA alinea por
    posición: el mes muestra la fecha cruda y un total vacío hereda el monto
    del comprobante siguiente.
    """
    return _sheet_has_item_columns(columns)


def _sheet_rows(
    columns: Sequence[Dict[str, Any]],
    facturas: Sequence[Dict[str, Any]],
    by_idx: Dict[int, List[Dict[str, Any]]],
    lookups: Optional[Dict[Any, Any]] = None,
    decisions: Optional[Dict[Any, str]] = None,
    column_options: Optional[Dict[str, List[str]]] = None,
) -> List[Dict[str, str]]:
    """Una fila por ítem si hay columnas items[]. Si no, una por comprobante.

    Gastos tiene Coincidir con y FacturIA igual muestra una fila por factura.
    Abrir una por ítem desalinea Mes, Fecha y Monto.
    """
    expand_items = _sheet_expands_items(columns)
    rows: List[Dict[str, str]] = []
    for idx, fac in enumerate(facturas or []):
        if not isinstance(fac, dict):
            fac = {}
        excel_lines = by_idx.get(idx) or []
        header_excel = excel_lines[0] if excel_lines else {}
        items = fac.get("items") if isinstance(fac.get("items"), list) else []
        line_items: List[Any] = list(items) if items else [{}]
        if not expand_items:
            line_items = line_items[:1]
        for line_index, item in enumerate(line_items):
            line_excel = excel_lines[line_index] if line_index < len(excel_lines) else {}
            item_dict = item if isinstance(item, dict) else {}
            record: Dict[str, str] = {}
            for col in columns:
                name = str(col.get("header_label") or "")
                record[name] = _cell_value(
                    col,
                    fac,
                    item_dict,
                    line_index,
                    header_excel,
                    line_excel,
                    lookups,
                    comp_idx=idx,
                    decisions=decisions,
                    column_options=(column_options or {}).get(name) or [],
                )
            rows.append(record)
    return rows


def _cell_value(
    col: Dict[str, Any],
    fac: Dict[str, Any],
    item: Dict[str, Any],
    line_index: int,
    header_excel: Dict[str, Any],
    line_excel: Dict[str, Any],
    lookups: Optional[Dict[Any, Any]] = None,
    comp_idx: int = 0,
    decisions: Optional[Dict[Any, str]] = None,
    column_options: Optional[Sequence[str]] = None,
) -> str:
    source_type = str(col.get("source_type") or "canonical").strip().lower()
    source = str(col.get("source_value") or "")
    source_key = source.strip()
    is_item = source_key.startswith("items[].") or source_key.startswith("items.")
    from facturia_matching.padron.template_lookup import (
        column_role,
        concept_choice,
        lookup_key,
        pipeline_suggestion,
        suggest_enabled,
        suggest_for,
    )

    raw = ""
    invoice_raw = ""
    if source_type != "static":
        invoice_raw = _raw_source_value(
            fac, item, source_key, header_excel, line_excel, overlay=False
        )
        raw = _raw_source_value(fac, item, source_key, header_excel, line_excel)
    # El texto de la factura gana si ya es un valor de la lista (mayúsculas,
    # acentos, S.A./S.R.L.). No lo pisa un CUIT de otra empresa ni el historial.
    from facturia_matching.padron.excel import wire_listed_value

    wired = (
        wire_listed_value(invoice_raw, list(column_options or []))
        if str(invoice_raw or "").strip()
        else ""
    )
    if wired and (line_index == 0 or _repeats(col) or is_item):
        return wired
    # Coincidir con: sin tilde = fuzzy + historial; con tilde = IA + historial.
    # Vale para cualquier columna vinculada, no solo concepto o categoría.
    name = str(col.get("header_label") or "")
    if lookup_key(col) and decisions is not None and (comp_idx, name) in decisions:
        picked = str(decisions.get((comp_idx, name)) or "")
        if line_index > 0 and not _repeats(col) and not is_item:
            return picked if suggest_enabled(col) else ""
        if suggest_enabled(col) or picked:
            return picked
        return ""
    # Concepto / categoría sin lista vinculada: tilde = IA; sin tilde = fuzzy.
    role = column_role(col)
    if role in ("concepto", "categoria"):
        handled, concept_val = concept_choice(col, header_excel, line_excel)
        if handled:
            if line_index > 0 and not _repeats(col) and not is_item:
                return concept_val if suggest_enabled(col) else ""
            if concept_val or suggest_enabled(col):
                return concept_val
    # Tilde: matching Excel (proveedor, forma de pago, lookup del Sheet).
    suggested = ""
    if suggest_enabled(col):
        suggested = pipeline_suggestion(col, header_excel, line_excel) or suggest_for(
            col, raw, lookups
        )
    # should_repeat=0 deja vacía la cabecera cruda desde la 2ª línea.
    # Un hit de lookup/Excel se conserva: si no, la UI muestra el CUIT.
    # Monto/fecha no son esa sugerencia: si el origen se leyó vacío, no se inventan.
    if line_index > 0 and not _repeats(col) and not is_item:
        return suggested
    if suggest_enabled(col):
        if suggested:
            return suggested
        if column_role(col):
            return ""
    if _explicit_source_empty(source_type, source_key, raw) and _scalar_label(col):
        return ""
    # Sin origen mapeado, Fecha/Monto solo se completan si la tilde de sugerir está prendida.
    if (
        _scalar_label(col)
        and source_type == "static"
        and not str(raw or "").strip()
        and not suggest_enabled(col)
    ):
        return ""
    payload = _facturia_scalar(col, fac, raw)
    if payload:
        return payload
    if source_type == "static":
        return source
    return _format_source_date(source_key, raw)


def _label(col: Dict[str, Any]) -> str:
    label = str(col.get("header_label") or "").strip().casefold()
    for src, dst in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
        label = label.replace(src, dst)
    return label


def _scalar_label(col: Dict[str, Any]) -> str:
    """Cabecera que se completa con la factura (no con un catálogo)."""
    return {
        "fecha de pago": "fecha_pago",
        "fecha": "fecha",
        "mes de pago": "mes_pago",
        "mes": "mes",
        "monto": "monto",
        "observacion": "observacion",
    }.get(_label(col), "")


def _explicit_source_empty(source_type: str, source_key: str, raw: str) -> bool:
    """El template apunta a un campo y la extracción lo trajo vacío."""
    return source_type != "static" and bool(source_key) and not str(raw or "").strip()


def _format_source_date(source_key: str, raw: str) -> str:
    key = str(source_key or "").strip().lower()
    if "fecha" not in key and not key.endswith("vencimiento"):
        return raw
    from facturia_matching.infra.normalization import normalize_date_ddmmyyyy

    return normalize_date_ddmmyyyy(raw) or raw


def _facturia_scalar(col: Dict[str, Any], fac: Dict[str, Any], raw: str = "") -> str:
    """Fecha, monto, mes, fecha de pago y observación: lo que trae la factura.

    Si el origen canónico ya tiene valor, se usa ese (la fecha no se cambia por otro
    campo). Un ISO se normaliza a DD/MM/YYYY. Mes / Mes de pago son el mes en español.
    """
    from facturia_matching.infra.normalization import normalize_date_ddmmyyyy
    from facturia_matching.padron.pepe_schema import format_pepe_money, month_name_es_from_date
    from facturia_matching.padron.process_to_invoice import factura_to_invoice_input

    field = _scalar_label(col)
    if not field or not isinstance(fac, dict):
        return ""
    seen = str(raw or "").strip()
    inv = factura_to_invoice_input(fac)
    if field == "monto":
        return format_pepe_money(seen if seen else inv.get("monto"))
    if field == "fecha":
        return normalize_date_ddmmyyyy(seen if seen else inv.get("fecha"))
    if field == "fecha_pago":
        return normalize_date_ddmmyyyy(seen if seen else inv.get("fecha_pago"))
    if field == "mes":
        return month_name_es_from_date(seen if seen else str(inv.get("fecha") or ""))
    if field == "mes_pago":
        return month_name_es_from_date(seen if seen else str(inv.get("fecha_pago") or ""))
    if seen and field == "observacion":
        return seen
    return str(inv.get(field) or "").strip()


def _raw_source_value(
    fac: Dict[str, Any],
    item: Dict[str, Any],
    source_key: str,
    header_excel: Dict[str, Any],
    line_excel: Dict[str, Any],
    overlay: bool = True,
) -> str:
    is_item = source_key.startswith("items[].") or source_key.startswith("items.")
    if is_item:
        if source_key.startswith("items[]."):
            path = source_key[len("items[].") :]
        elif "." in source_key:
            path = source_key.split(".", 1)[1]
        else:
            path = ""
        overlay_key = _ITEM_EXCEL.get(source_key)
        if overlay and overlay_key:
            hit = str((line_excel or {}).get(overlay_key) or "").strip()
            if hit:
                return hit
        return _dig(item, path)
    if source_key.startswith("cabecera."):
        path = source_key[len("cabecera.") :]
        overlay_key = _HEADER_EXCEL.get(source_key)
        if overlay and overlay_key:
            hit = str((header_excel or {}).get(overlay_key) or "").strip()
            if hit:
                return hit
        return _dig(fac, path)
    return _dig(fac, source_key)


def _repeats(col: Dict[str, Any]) -> bool:
    raw = col.get("should_repeat")
    if raw is None or str(raw).strip() == "":
        return True
    try:
        return int(raw) != 0
    except (TypeError, ValueError):
        return True


def _dig(obj: Any, path: str) -> str:
    cur: Any = obj
    for part in [p for p in str(path or "").split(".") if p]:
        if not isinstance(cur, dict):
            return ""
        if part in cur:
            cur = cur.get(part)
            continue
        found = None
        part_l = part.lower()
        for key, value in cur.items():
            if str(key).lower() == part_l:
                found = value
                break
        if found is None:
            return ""
        cur = found
    return _stringify(cur)


def _stringify(value: Any) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value != value:
            return ""
        if value == int(value):
            return str(int(value))
        return str(value)
    return str(value).strip()


def _option_lists(padron: Dict[str, Any]) -> Dict[str, List[str]]:
    return {
        "proveedores": _proveedor_names(padron.get("proveedores") or []),
        "conceptos": _string_list(padron.get("conceptos") or []),
        "formas_pago": _string_list(padron.get("formas_pago") or []),
        "productos": _named(padron.get("productos") or [], "nombre"),
        "rubros": _string_list(padron.get("rubros") or []),
        "diarios": _string_list(padron.get("diarios") or []),
    }


def _proveedor_names(rows: Sequence[Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    for row in rows:
        if isinstance(row, str):
            name = row.strip()
        elif isinstance(row, dict):
            name = str(row.get("razon_social") or row.get("nombre_fantasia") or "").strip()
        else:
            name = ""
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            out.append(name)
    return out


def _named(rows: Sequence[Any], field: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for row in rows:
        if isinstance(row, str):
            name = row.strip()
        elif isinstance(row, dict):
            name = str(row.get(field) or row.get("nombre") or row.get("name") or "").strip()
        else:
            name = ""
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            out.append(name)
    return out


def _string_list(values: Sequence[Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        if isinstance(value, dict):
            name = str(value.get("nombre") or value.get("name") or value.get("id") or "").strip()
        else:
            name = str(value or "").strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            out.append(name)
    return out


def _unwrap_json(raw: Any) -> Any:
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    obj: Any = raw
    if isinstance(obj, str):
        if not obj.strip():
            return {}
        obj = json.loads(obj)
        if isinstance(obj, str):
            obj = json.loads(obj) if obj.strip() else {}
    return obj
