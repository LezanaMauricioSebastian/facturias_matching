# API pública del paquete `import_`

Símbolos exportados desde `facturia_matching.odoo.import_` (`__init__.py` + `__all__`).

---

## Entrypoint principal

### `import_rows_to_odoo`

```python
def import_rows_to_odoo(
    rows: List[Dict[str, Any]],
    *,
    skip_duplicates: bool = True,
    update_taxes_if_exists: bool = True,
) -> Dict[str, Any]:
```

**Caller:** `POST /api/odoo/import` en `api/routes.py`

**Parámetros:**

| Parámetro | Default | Efecto |
|-----------|---------|--------|
| `skip_duplicates` | `True` | Busca factura existente por partner + doc |
| `update_taxes_if_exists` | `True` | Si existe, `sync_move_taxes_from_group` en lugar de skip |

**Respuesta exitosa (campos principales):**

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `ok` | bool | False si hubo errores parciales |
| `created` | list | `{id, name, state, document_number}` nuevos |
| `updated_taxes` | list | Resumen sync por comprobante existente o post-create |
| `skipped` | list | Duplicados sin update (`reason: already_exists`) |
| `errors` | list | `{document_number, error}` o con `move_id` si create ok pero sync falló |

---

## Sync (reutilizable)

| Función | Uso |
|---------|-----|
| `sync_move_taxes_from_group(config, move_id, group)` | Alinear borrador Odoo con filas UI |
| `update_move_taxes_from_group` | Alias de `sync_move_taxes_from_group` |

---

## Preparación y validación (tests + uso interno)

| Función | Descripción |
|---------|-------------|
| `validate_rows_for_import(rows)` | → `Optional[str]` error |
| `group_rows_into_invoices(rows)` | Agrupa por comprobante |
| `propagate_invoice_headers(group)` | Propaga cabecera |
| `_prepare_rows_for_import(config, rows)` | Prep completa → `(groups, warnings)` |

---

## Planificación (tests)

| Función | Descripción |
|---------|-------------|
| `plan_move_header_updates(move, group)` | Fechas encabezado |
| `plan_invoice_origin_update(current, group)` | OC en encabezado |
| `plan_line_tax_updates(product_lines, content_rows)` | Diff `tax_ids` |
| `plan_product_line_content_updates(...)` | Diff contenido línea |
| `plan_product_price_quantity_reapply(...)` | Re-aplica price/qty final |
| `plan_purchase_line_updates(...)` | Diff `purchase_line_id` |
| `plan_tax_line_amount_overwrites(tax_lines, expected)` | Diff montos tax |

---

## Impuestos

| Función | Descripción |
|---------|-------------|
| `_tax_ids_for_odoo_line(row, group)` | tax_ids para una línea producto |
| `collect_expected_tax_amounts_from_group(group)` | `{tax_id: monto}` esperado |
| `_tax_line_amount_write_vals(amount, line, …)` | Vals para write línea tax |

---

## Purchase / OC

| Función | Descripción |
|---------|-------------|
| `sanitize_group_purchase_lines(config, group)` | Quita OC ids inválidos |
| `_should_refresh_purchase_links(rows)` | ¿Refresh antes de import? |
| `_dedupe_group_oc_line_ids(group)` | Dedupe `__oc_line_id` |

---

## Create / duplicados (tests)

| Función | Descripción |
|---------|-------------|
| `_build_move_vals(group)` | Dict `account.move.create` |
| `_build_line_command(row, group, …)` | Tupla línea Odoo |
| `_find_existing_move(config, partner_id, doc)` | Busca duplicado |
| `_document_numbers_match` / `_move_matches_document_number` | Comparación doc |
| `_invoice_due_date_from_group(group)` | ISO due date |

---

## Utilidades Odoo

| Símbolo | Descripción |
|---------|-------------|
| `_move_line_supports_purchase_link(config)` | ¿Tenant tiene purchase? |
| `_move_product_line_fields(config)` | Campos `search_read` |
| `_MOVE_LINE_PURCHASE_LINK_CACHE` | Cache fields_get |
| `_batch_write_move_lines(config, move_id, updates)` | Batch write líneas |
| `_account_requires_maturity(account_row)` | ¿Cuenta AP/AR? |

---

## Quién importa qué (repo)

| Archivo | Imports |
|---------|---------|
| `api/routes.py` | `import_rows_to_odoo` |
| `tests/test_odoo_import.py` | ~30 símbolos (públicos y `_` helpers) |
| `tests/test_iva_tax_resolve.py` | `_tax_ids_for_odoo_line`, `collect_expected_*`, `group_*`, `propagate_*` |
| `tests/test_comprobante_tax.py` | `_tax_ids_for_odoo_line`, `collect_expected_*` |
| `tests/test_tax_pipeline.py` | `collect_expected_tax_amounts_from_group` |
| `tests/test_padron_taxes_iibb.py` | `collect_expected_tax_amounts_from_group` |

**Regla:** código de aplicación solo debería usar `import_rows_to_odoo` (y eventualmente `sync_*` si se añade endpoint de re-sync). El resto es API de test o extensión interna.

---

## Importar desde submódulos (desarrollo)

Preferido para código **dentro** del paquete:

```python
from facturia_matching.odoo.import_.taxes import collect_expected_tax_amounts_from_group
```

Para callers externos y tests existentes, seguir usando:

```python
from facturia_matching.odoo.import_ import collect_expected_tax_amounts_from_group
```

---

## Símbolos no reexportados (internos)

Ejemplos — importar solo desde su submódulo si hace falta en tests nuevos:

| Símbolo | Módulo |
|---------|--------|
| `_apply_tax_line_amount_overwrites` | `taxes` |
| `_refresh_purchase_links` | `purchase` |
| `_get_move_product_lines` | `move_lines` |
| `_po_link_write_vals` | `planning` |
| `_normalize`, `_parse_amount_loose` | `_utils` |

Ver [modulos.md](modulos.md) para lista completa.
