"""Re-mapea IDs de catálogo Odoo al cargar filas guardadas en otro tenant (p. ej. Aliare vs Dinner)."""

from typing import Any, Dict, List, Optional, Set

from facturia_matching.infra.config import DEFAULT_JOURNAL_NAME, DEFAULT_RUBRO_NAME
from facturia_matching.odoo.catalog import (
    build_partner_cuit_to_id,
    get_catalog,
    resolve_account_id,
    resolve_doc_type_id,
    resolve_id_fuzzy,
    resolve_partner_id,
)
from facturia_matching.odoo.env import supports_rubro_field
from facturia_matching.padron.postgres import match_proveedor
from facturia_matching.odoo.purchase_matching import (
    _group_rows_by_comprobante,
    _propagate_partner_for_matching,
    clear_comprobante_purchase_fields,
)
from facturia_matching.infra.normalization import normalize


def _catalog_id_set(items: List[Dict[str, Any]]) -> Set[str]:
    return {str(x["id"]) for x in (items or []) if x.get("id") is not None}


def _str_id(value: Any) -> str:
    return str(value or "").strip()


def _infer_doc_type_label(header: Dict[str, Any]) -> str:
    iva = _str_id(header.get("iva_pct")).upper()
    if iva in ("IVA NO CORRESPONDE", "0", "0%"):
        return "FACTURAS C"
    return ""


def _remap_product_id(
    row: Dict[str, Any],
    productos: List[Dict[str, Any]],
    valid_products: Set[str],
) -> None:
    current = _str_id(row.get("invoice_line_ids/product_id"))
    if not current or current in valid_products:
        return
    code = _str_id(row.get("__item_codigo"))
    if code:
        for p in productos:
            if _str_id(p.get("code")) == code:
                row["invoice_line_ids/product_id"] = str(p["id"])
                return
    name = _str_id(row.get("invoice_line_ids/name"))
    if name:
        new_id = resolve_id_fuzzy(name, productos, min_score=72.0)
        if new_id:
            row["invoice_line_ids/product_id"] = new_id


def _set_comprobante_header_field(
    comp_rows: List[Dict[str, Any]],
    key: str,
    value: str,
) -> None:
    if not value or not comp_rows:
        return
    header = comp_rows[0]
    header[key] = value


def remap_saved_rows_to_catalog(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ajusta partner_id y otros IDs Odoo de filas persistidas al catálogo del tenant actual.

    Usa CUIT / nombre de proveedor y padrón para rubro, diario y cuenta cuando el ID
  guardado no existe en el catálogo activo (cambio de empresa / perfil Odoo).
    """
    if not rows:
        return rows

    catalog, from_odoo = get_catalog()
    if not from_odoo or not catalog:
        return rows

    proveedores = catalog.get("proveedores") or []
    partner_cuit_to_id = catalog.get("partner_cuit_to_id") or build_partner_cuit_to_id(proveedores)
    valid_partners = _catalog_id_set(proveedores)
    valid_journals = _catalog_id_set(catalog.get("journals") or [])
    valid_rubros = _catalog_id_set(catalog.get("rubros") or [])
    valid_accounts = _catalog_id_set(catalog.get("cuentas") or [])
    valid_doc_types = _catalog_id_set(catalog.get("document_types") or [])
    valid_products = _catalog_id_set(catalog.get("productos") or [])

    maps = catalog.get("maps") or {}
    doc_label_map = maps.get("document_type_labels") or {}
    account_maps = maps.get("accounts") or {}
    journals_odoo = catalog.get("journals") or []
    rubros_odoo = catalog.get("rubros") or []
    cuentas_odoo = catalog.get("cuentas") or []
    productos = catalog.get("productos") or []

    groups = _group_rows_by_comprobante(rows)
    for comp_rows in groups.values():
        if not comp_rows:
            continue
        header = comp_rows[0]
        nombre = normalize(header.get("Nombre de Proveedor") or "")
        cuit = normalize(header.get("CUIT") or "")
        if not nombre and not cuit:
            continue

        old_partner = _str_id(header.get("partner_id"))
        new_partner, _ = resolve_partner_id(nombre, cuit, proveedores, partner_cuit_to_id)
        if not new_partner:
            matched_name, _, _, _, _ = match_proveedor(nombre, cuit)
            if matched_name:
                new_partner = resolve_id_fuzzy(matched_name, proveedores, min_score=72.0)

        partner_changed = bool(new_partner and new_partner != old_partner)
        if new_partner and (partner_changed or (old_partner and old_partner not in valid_partners)):
            for row in comp_rows:
                cur = _str_id(row.get("partner_id"))
                if partner_changed or row is header or not cur or cur not in valid_partners:
                    row["partner_id"] = new_partner
            if partner_changed:
                clear_comprobante_purchase_fields(comp_rows)

        matched_name, matched_rubro, matched_diario, matched_cuenta, _ = match_proveedor(
            nombre, cuit
        )

        old_journal = _str_id(header.get("journal_id"))
        if matched_diario or (old_journal and old_journal not in valid_journals):
            new_journal = resolve_id_fuzzy(
                matched_diario,
                journals_odoo,
                fallback_name=DEFAULT_JOURNAL_NAME or None,
                min_score=75.0,
            )
            if new_journal:
                _set_comprobante_header_field(comp_rows, "journal_id", new_journal)

        if supports_rubro_field():
            old_rubro = _str_id(header.get("x_studio_category"))
            if matched_rubro or (old_rubro and old_rubro not in valid_rubros):
                new_rubro = resolve_id_fuzzy(
                    matched_rubro,
                    rubros_odoo,
                    fallback_name=DEFAULT_RUBRO_NAME or None,
                    min_score=72.0,
                )
                if new_rubro:
                    _set_comprobante_header_field(comp_rows, "x_studio_category", new_rubro)
        else:
            for row in comp_rows:
                row["x_studio_category"] = ""

        old_account = _str_id(header.get("invoice_line_ids/account_id"))
        if matched_cuenta or (old_account and old_account not in valid_accounts):
            new_account = resolve_account_id(
                matched_cuenta,
                cuentas_odoo,
                account_maps,
                min_score=65.0,
            )
            if new_account:
                _set_comprobante_header_field(comp_rows, "invoice_line_ids/account_id", new_account)

        old_doc = _str_id(header.get("l10n_latam_document_type_id"))
        if old_doc and old_doc not in valid_doc_types:
            doc_label = _infer_doc_type_label(header)
            if doc_label:
                new_doc = resolve_doc_type_id(doc_label, doc_label_map)
                if new_doc:
                    _set_comprobante_header_field(
                        comp_rows, "l10n_latam_document_type_id", new_doc
                    )

    for row in rows:
        if isinstance(row, dict):
            _remap_product_id(row, productos, valid_products)

    _propagate_partner_for_matching(rows)
    return rows
