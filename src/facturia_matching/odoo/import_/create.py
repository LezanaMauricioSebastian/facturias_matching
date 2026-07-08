"""Create Odoo vendor bills and orchestrate import."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from facturia_matching.odoo.api import (
    get_odoo_import_config,
    get_odoo_uid_from_config,
    is_odoo_config_ready,
    odoo_execute_kw_with_config,
)
from facturia_matching.odoo.env import (
    is_odoo_aliare_profile,
    is_odoo_sudata_profile,
    supports_rubro_field,
)

from facturia_matching.odoo.import_._utils import (
    _date_ddmm_to_iso,
    _int_id,
    _line_has_content,
    _normalize,
)
from facturia_matching.odoo.import_.purchase import _prepare_rows_for_import
from facturia_matching.odoo.import_.rows import (
    _build_line_command,
    _invoice_due_date_from_group,
    _invoice_origin_from_group,
    validate_rows_for_import,
)
from facturia_matching.odoo.import_.sync import sync_move_taxes_from_group


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
            created.append(
                {
                    "id": move_id,
                    "name": None,
                    "state": "draft",
                    "document_number": doc_number,
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
