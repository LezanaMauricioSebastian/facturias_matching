"""Coincidir con / Sugerir para cualquier columna vinculada del template.

Si el texto de la factura ya es un valor de la lista (mayúsculas, acentos,
S.A./S.R.L.), gana ese. Si no, sin tilde: fuzzy contra la lista, y si el
historial de Gastos ya tiene un valor de esa columna para el proveedor, gana ese.
Con tilde: un prompt genérico elige un valor de la misma lista, con el
historial como ejemplos.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from rapidfuzz import fuzz

from facturia_matching.infra.normalization import normalize

DecisionKey = Tuple[int, str]


def history_keys(col: Dict[str, Any]) -> List[str]:
    """Nombres con los que esta columna puede aparecer en la hoja Gastos."""
    parts = (
        col.get("header_label"),
        col.get("lookup_match_column"),
        col.get("lookup_return_column"),
    )
    blob = " ".join(str(p or "") for p in parts).casefold()
    for src, dst in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
        blob = blob.replace(src, dst)
    keys: List[str] = []
    if "categoria" in blob:
        keys.append("categoria")
    if "concepto" in blob:
        keys.append("concepto")
    if "proveedor" in blob or "razon social" in blob:
        keys.append("proveedor")
    if "forma de pago" in blob or "formapago" in blob:
        keys.append("forma_pago")
    for part in parts:
        name = " ".join(normalize(part).lower().split())
        if name and name not in keys:
            keys.append(name)
    return keys


def _value_from_record(record: Dict[str, Any], keys: Sequence[str]) -> str:
    valores = record.get("valores") if isinstance(record.get("valores"), dict) else {}
    for key in keys:
        raw = str(record.get(key) or "").strip()
        if not raw:
            raw = str(valores.get(key) or "").strip()
        if raw:
            return raw
    return ""


def dominant_from_history(
    records: Optional[Sequence[Dict[str, Any]]],
    col: Dict[str, Any],
    proveedor: str,
    allowed: Sequence[str],
) -> str:
    """Valor más usado de esta columna para ese proveedor, si está en la lista."""
    from facturia_matching.padron.concept_ai import _resolve_from_list
    from facturia_matching.padron.excel import company_key

    prov_q = company_key(proveedor) or normalize(proveedor).upper()
    if not prov_q or not records:
        return ""
    keys = history_keys(col)
    pool: List[Dict[str, Any]] = []
    fuzzy_pool: List[Dict[str, Any]] = []
    for record in records:
        raw_name = record.get("proveedor") or ""
        rp = company_key(raw_name) or normalize(raw_name).upper()
        if not rp:
            continue
        if rp == prov_q:
            pool.append(record)
        elif min(len(prov_q), len(rp)) >= 4 and float(fuzz.token_set_ratio(prov_q, rp)) >= 90.0:
            fuzzy_pool.append(record)
    pool = pool or fuzzy_pool
    counts: Dict[str, int] = {}
    display: Dict[str, str] = {}
    for record in pool:
        raw = _value_from_record(record, keys)
        if not raw:
            continue
        canon = _resolve_from_list(raw, list(allowed)) if allowed else raw
        if allowed and not canon:
            continue
        label = canon or raw
        key = normalize(label).upper()
        counts[key] = counts.get(key, 0) + 1
        display[key] = label
    if not counts:
        return ""
    best = max(counts, key=lambda item: counts[item])
    return display.get(best) or ""


def fuzzy_lookup_value(
    col: Dict[str, Any],
    *,
    raw: str,
    descripcion: str,
    proveedor: str,
    options: Sequence[str],
    lookups: Optional[Dict[Any, Any]],
    records: Optional[Sequence[Dict[str, Any]]],
    header_excel: Optional[Dict[str, Any]],
    line_excel: Optional[Dict[str, Any]],
) -> str:
    """Nombre de la lista si la factura ya lo trae; si no, historial y fuzzy.

    Razón social: «LA ALEMANA S.R.L» es «La Alemana». El historial de otro
    proveedor (p. ej. Gran Crianza) no reemplaza ese nombre.
    """
    from facturia_matching.padron.excel import match_one, wire_listed_value
    from facturia_matching.padron.template_lookup import (
        column_role,
        pipeline_suggestion,
        suggest_for,
    )

    role = column_role(col)
    # Si el texto de la factura ya es un valor de la lista (mismas letras,
    # ignorando mayúsculas, acentos y S.A./S.R.L.), se usa ese. El historial
    # no lo pisa: «EFECTIVO» es «Efectivo», no «(vacío)».
    listed_query = raw or (proveedor if role == "proveedor" else "")
    listed = wire_listed_value(listed_query, options) if str(listed_query or "").strip() else ""
    if listed:
        return listed
    hist = dominant_from_history(records, col, proveedor, options)
    if hist:
        return hist
    exact = suggest_for(col, raw, lookups)
    if exact:
        return exact
    queries = (raw, proveedor) if role == "proveedor" else (raw, descripcion, proveedor)
    for query in queries:
        hit = match_one(query, list(options)) if str(query or "").strip() else None
        if hit:
            return hit[0]
    piped = pipeline_suggestion(col, header_excel, line_excel)
    if not piped:
        return ""
    from facturia_matching.padron.concept_ai import _resolve_from_list

    return _resolve_from_list(piped, list(options)) or ""


def suggest_lookup_columns(
    *,
    columns: Sequence[Dict[str, Any]],
    proveedor: str,
    descripciones: Sequence[str],
    examples: Sequence[Dict[str, Any]],
    company_id: int = 0,
) -> Dict[str, str]:
    """Una llamada: cada columna tildada elige un valor de su lista."""
    from facturia_matching.padron.concept_ai import (
        _call_deepseek,
        _parse_json_array,
        _resolve_from_list,
        is_concept_ai_enabled,
    )

    pending = [c for c in columns if c.get("options")]
    if not pending or not is_concept_ai_enabled():
        return {}
    prompt = _build_prompt(
        proveedor=proveedor,
        descripciones=list(descripciones or []),
        columns=pending,
        examples=list(examples or []),
    )
    try:
        raw = _call_deepseek(prompt, max_tokens=min(80 * len(pending) + 64, 800))
        parsed = _parse_json_array(raw)
    except Exception:
        return {}
    by_name = {str(c.get("name") or ""): list(c.get("options") or []) for c in pending}
    out: Dict[str, str] = {}
    for i, obj in enumerate(parsed):
        name = str(obj.get("col") or obj.get("columna") or obj.get("name") or "").strip()
        if not name and i < len(pending):
            name = str(pending[i].get("name") or "")
        options = by_name.get(name) or []
        if not options:
            for label, opts in by_name.items():
                if normalize(label).upper() == normalize(name).upper():
                    name = label
                    options = opts
                    break
        value = _resolve_from_list(str(obj.get("valor") or obj.get("value") or ""), options)
        if name and value:
            out[name] = value
    return out


def _build_prompt(
    *,
    proveedor: str,
    descripciones: Sequence[str],
    columns: Sequence[Dict[str, Any]],
    examples: Sequence[Dict[str, Any]],
) -> str:
    lines = [
        "Sos un asistente que completa columnas de una planilla de gastos.",
        "Para cada columna elegí UN valor, SOLO de su lista permitida.",
        "Si el historial del cliente ya usó un valor para este proveedor, preferilo.",
        'Respondé ÚNICAMENTE un JSON array (sin markdown):',
        '[{"col":"nombre de la columna","valor":"..."}]',
        "",
        f'Proveedor: "{normalize(proveedor) or "(desconocido)"}"',
        "",
        "Texto de la factura:",
    ]
    for desc in descripciones:
        text = normalize(desc)
        if text:
            lines.append(f'- "{text}"')
    lines.append("")
    lines.append("Columnas a completar:")
    for col in columns:
        lines.append(f'- {col.get("name")}:')
        for opt in col.get("options") or []:
            lines.append(f"  - {opt}")
    if examples:
        lines.append("")
        lines.append("Historial del cliente (lo que ya cargó):")
        for ex in examples[:20]:
            bits = []
            for key in ("proveedor", "concepto", "categoria", "descripcion"):
                val = str(ex.get(key) or "").strip()
                if val:
                    bits.append(f'{key}="{val}"')
            valores = ex.get("valores") if isinstance(ex.get("valores"), dict) else {}
            for key, val in valores.items():
                text = str(val or "").strip()
                if text and key not in ("proveedor", "concepto", "categoria", "descripcion"):
                    bits.append(f'{key}="{text}"')
            if bits:
                lines.append("  - " + " ".join(bits))
    return "\n".join(lines)


def build_lookup_decisions(
    columns: Sequence[Dict[str, Any]],
    facturas: Sequence[Dict[str, Any]],
    by_idx: Dict[int, List[Dict[str, Any]]],
    lookups: Optional[Dict[Any, Any]],
    gastos_records: Optional[Sequence[Dict[str, Any]]] = None,
    company_id: int = 0,
) -> Dict[DecisionKey, str]:
    """Valor por (comprobante, columna) para cada columna con Coincidir con."""
    from facturia_matching.infra.normalization import normalize as norm
    from facturia_matching.padron.gastos_history import top_k_examples
    from facturia_matching.padron.template_lookup import (
        lookup_key,
        options_for,
        suggest_enabled,
    )

    linked = [c for c in columns if lookup_key(c)]
    if not linked:
        return {}
    out: Dict[DecisionKey, str] = {}
    for idx, fac in enumerate(facturas or []):
        if not isinstance(fac, dict):
            fac = {}
        excel_lines = by_idx.get(idx) or []
        header_excel = excel_lines[0] if excel_lines else {}
        proveedor = _proveedor_for_history(fac, header_excel, linked, lookups)
        items = fac.get("items") if isinstance(fac.get("items"), list) else []
        descripciones = [
            norm((it or {}).get("descripcion"))
            for it in items
            if isinstance(it, dict) and norm((it or {}).get("descripcion"))
        ]
        ai_columns: List[Dict[str, Any]] = []
        for col in linked:
            name = str(col.get("header_label") or "")
            options = options_for(col, lookups)
            if not options:
                continue
            raw = _raw_for(col, fac, items[:1][0] if items else {}, header_excel)
            from facturia_matching.padron.excel import wire_listed_value
            from facturia_matching.padron.template_lookup import column_role

            wired = wire_listed_value(raw, options) if str(raw or "").strip() else ""
            if not wired and column_role(col) == "proveedor":
                wired = wire_listed_value(proveedor, options)
            if wired:
                out[(idx, name)] = wired
                continue
            if suggest_enabled(col):
                ai_columns.append({"name": name, "options": options, "col": col})
                continue
            desc = descripciones[0] if descripciones else ""
            out[(idx, name)] = fuzzy_lookup_value(
                col,
                raw=raw,
                descripcion=desc,
                proveedor=proveedor,
                options=options,
                lookups=lookups,
                records=gastos_records,
                header_excel=header_excel,
                line_excel=excel_lines[0] if excel_lines else {},
            )
        if ai_columns:
            examples = top_k_examples(
                list(gastos_records or []),
                proveedor=proveedor,
                descripcion=descripciones[0] if descripciones else "",
                k=15,
            )
            picked = suggest_lookup_columns(
                columns=ai_columns,
                proveedor=proveedor,
                descripciones=descripciones,
                examples=examples,
                company_id=company_id,
            )
            for spec in ai_columns:
                name = str(spec.get("name") or "")
                out[(idx, name)] = str(picked.get(name) or "")
    return out


def _raw_for(
    col: Dict[str, Any],
    fac: Dict[str, Any],
    item: Dict[str, Any],
    header_excel: Dict[str, Any],
) -> str:
    from facturia_matching.padron.template_entrega import _raw_source_value

    source_type = str(col.get("source_type") or "canonical").strip().lower()
    source_key = str(col.get("source_value") or "").strip()
    if source_type == "static":
        return ""
    return _raw_source_value(
        fac,
        item if isinstance(item, dict) else {},
        source_key,
        header_excel,
        header_excel,
        overlay=False,
    )


def _proveedor_for_history(
    fac: Dict[str, Any],
    header_excel: Dict[str, Any],
    columns: Sequence[Dict[str, Any]],
    lookups: Optional[Dict[Any, Any]],
) -> str:
    """Proveedor del historial: el nombre de la factura si está en la lista.

    `__excel_proveedor` solo se usa cuando es la misma empresa. Si el match
    Excel dijo Gran Crianza y la factura dice La Alemana, el historial es el
    de La Alemana.
    """
    from facturia_matching.infra.normalization import normalize as norm
    from facturia_matching.padron.excel import pick_listed_company, same_company
    from facturia_matching.padron.template_lookup import column_role, options_for

    prov = fac.get("proveedor") if isinstance(fac.get("proveedor"), dict) else {}
    invoice_name = norm(prov.get("razon_social") or prov.get("nombre") or "")
    excel_name = str((header_excel or {}).get("__excel_proveedor") or "").strip()
    options: List[str] = []
    for col in columns:
        if column_role(col) != "proveedor":
            continue
        options = options_for(col, lookups)
        if options:
            break
    listed = pick_listed_company(invoice_name, options) if invoice_name and options else ""
    if listed:
        return listed
    if excel_name and (not invoice_name or same_company(excel_name, invoice_name)):
        return excel_name
    return invoice_name or excel_name
