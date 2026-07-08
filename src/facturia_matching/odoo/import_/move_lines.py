"""Odoo move line reads and batch writes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from facturia_matching.odoo.api import odoo_execute_kw_with_config

from facturia_matching.odoo.import_._utils import _move_product_line_fields


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


def _write_move_lines_individually(
    config: Dict[str, Any],
    updates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Write directo en account.move.line (compatible con ACLs restrictivas en prod)."""
    applied: List[Dict[str, Any]] = []
    for item in updates:
        odoo_execute_kw_with_config(
            config,
            "account.move.line",
            "write",
            [[item["line_id"]], item["write_vals"]],
        )
        applied.append(item)
    return applied


def _batch_write_move_lines(
    config: Dict[str, Any],
    move_id: int,
    updates: List[Dict[str, Any]],
    warnings: Optional[List[str]] = None,
    *,
    context: str = "",
) -> List[Dict[str, Any]]:
    """
    Intenta un solo account.move.write con line_ids; si falla (p. ej. Access Denied en prod),
    reintenta con writes línea a línea en account.move.line.
    """
    if not updates:
        return []
    line_cmds = [(1, int(item["line_id"]), dict(item["write_vals"])) for item in updates]
    try:
        odoo_execute_kw_with_config(
            config,
            "account.move",
            "write",
            [[move_id], {"line_ids": line_cmds}],
        )
        return list(updates)
    except Exception as exc:
        prefix = f"{context}: " if context else ""
        if warnings is not None:
            warnings.append(f"{prefix}batch falló ({exc}); se reintenta línea a línea")
        applied: List[Dict[str, Any]] = []
        for item in updates:
            try:
                _write_move_lines_individually(config, [item])
                applied.append(item)
            except Exception as line_exc:
                if warnings is not None:
                    warnings.append(
                        f"{prefix}{item.get('line_name') or item.get('line_id')}: {line_exc}"
                    )
                else:
                    raise line_exc from exc
        if not applied:
            raise exc
        return applied


def _batch_write_move_lines_with_fallback(
    config: Dict[str, Any],
    move_id: int,
    updates: List[Dict[str, Any]],
    warnings: List[str],
    *,
    context: str = "",
) -> List[Dict[str, Any]]:
    """Alias con warnings obligatorios (p. ej. vínculos OC)."""
    return _batch_write_move_lines(
        config, move_id, updates, warnings, context=context
    )
