"""
Importación de filas UI → facturas de proveedor en Odoo (account.move, in_invoice).
Usa la misma instancia Odoo del perfil activo (Dinner o Aliare).

Documentación: docs/import-odoo/README.md
"""

from facturia_matching.odoo.import_._utils import (
    _MOVE_LINE_PURCHASE_LINK_CACHE,
    _move_line_supports_purchase_link,
    _move_product_line_fields,
)
from facturia_matching.odoo.import_.create import (
    _build_move_vals,
    _document_numbers_match,
    _find_existing_move,
    _move_matches_document_number,
    import_rows_to_odoo,
)
from facturia_matching.odoo.import_.move_lines import _batch_write_move_lines
from facturia_matching.odoo.import_.planning import (
    plan_invoice_origin_update,
    plan_line_tax_updates,
    plan_move_header_updates,
    plan_product_line_content_updates,
    plan_product_price_quantity_reapply,
)
from facturia_matching.odoo.import_.purchase import (
    _dedupe_group_oc_line_ids,
    _prepare_rows_for_import,
    _should_refresh_purchase_links,
    plan_purchase_line_updates,
    sanitize_group_purchase_lines,
)
from facturia_matching.odoo.import_.rows import (
    _build_line_command,
    _invoice_due_date_from_group,
    group_rows_into_invoices,
    propagate_invoice_headers,
    validate_rows_for_import,
)
from facturia_matching.odoo.import_.sync import (
    sync_move_taxes_from_group,
    update_move_taxes_from_group,
)
from facturia_matching.odoo.import_.taxes import (
    _account_requires_maturity,
    _tax_ids_for_odoo_line,
    _tax_line_amount_write_vals,
    collect_expected_tax_amounts_from_group,
    plan_tax_line_amount_overwrites,
)

__all__ = [
    "_MOVE_LINE_PURCHASE_LINK_CACHE",
    "_account_requires_maturity",
    "_batch_write_move_lines",
    "_build_line_command",
    "_build_move_vals",
    "_dedupe_group_oc_line_ids",
    "_document_numbers_match",
    "_find_existing_move",
    "_invoice_due_date_from_group",
    "_move_line_supports_purchase_link",
    "_move_matches_document_number",
    "_move_product_line_fields",
    "_prepare_rows_for_import",
    "_should_refresh_purchase_links",
    "_tax_ids_for_odoo_line",
    "_tax_line_amount_write_vals",
    "collect_expected_tax_amounts_from_group",
    "group_rows_into_invoices",
    "import_rows_to_odoo",
    "plan_invoice_origin_update",
    "plan_line_tax_updates",
    "plan_move_header_updates",
    "plan_product_line_content_updates",
    "plan_product_price_quantity_reapply",
    "plan_purchase_line_updates",
    "plan_tax_line_amount_overwrites",
    "propagate_invoice_headers",
    "sanitize_group_purchase_lines",
    "sync_move_taxes_from_group",
    "update_move_taxes_from_group",
    "validate_rows_for_import",
]
