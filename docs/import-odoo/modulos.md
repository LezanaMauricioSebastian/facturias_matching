# Módulos del paquete `import_`

Referencia archivo por archivo. Rutas relativas a `src/facturia_matching/odoo/import_/`.

Índice del paquete: [README.md](README.md).

---

## `__init__.py`

Reexporta la API pública para mantener:

```python
from facturia_matching.odoo.import_ import import_rows_to_odoo
```

Lista completa en [api-publica.md](api-publica.md). No añadir lógica aquí.

---

## `_utils.py`

Utilidades compartidas sin dependencias internas del paquete.

| Función / constante | Rol |
|---------------------|-----|
| `_MOVE_LINE_PURCHASE_LINK_CACHE` | Cache `{base_url\|db → bool}` de soporte `purchase_line_id` |
| `_odoo_config_cache_key` | Clave de cache desde config Odoo |
| `_move_line_supports_purchase_link` | `fields_get` en `account.move.line`; false en tenants sin purchase |
| `_move_product_line_fields` | Lista de campos para `search_read` de líneas producto |
| `_normalize` | Strip y colapsar espacios |
| `_int_id` | String → int si es dígito |
| `_m2o_id` | Valor many2one Odoo → id |
| `_floats_differ` | Comparación con tolerancia |
| `_parse_amount_loose` | Monto es-AR / US (`1.234,56`, miles con punto) |
| `_date_ddmm_to_iso` | `DD/MM/YYYY` o ISO → `YYYY-MM-DD` |
| `_line_has_content` | ¿La fila tiene línea de producto importable? |
| `_content_rows_from_group` | Filtra filas con contenido en un grupo |
| `_first_content_row_index` / `_is_first_content_row` | Primera línea con producto (IIBB consolidado) |

**Depende de:** `odoo.api.odoo_execute_kw_with_config` (solo para `fields_get`).

---

## `rows.py`

Agrupación, validación y construcción de líneas para create.

| Función | Rol |
|---------|-----|
| `_invoice_group_key` | Clave estable: `idx:N`, `doc:…` o `row:N` |
| `group_rows_into_invoices` | `List[fila]` → `List[List[fila]]` por comprobante |
| `propagate_invoice_headers` | Copia cabecera a líneas hijas (como CSV) |
| `validate_rows_for_import` | Valida partner, journal, doc, fecha, cuenta; devuelve `str` error o `None` |
| `_invoice_origin_from_group` | Texto `invoice_origin` desde `__selected_oc_name` o `__oc_name` |
| `_build_line_command` | `(0, 0, vals)` con qty, price, account, product, tax_ids |
| `_invoice_due_date_from_group` | `invoice_date_due` o fallback `invoice_date` |

**Depende de:** `_utils`, `taxes._tax_ids_for_odoo_line`.

---

## `purchase.py`

Orden de compra: refresh, validación en Odoo, dedupe y plan de vínculos.

| Función | Rol |
|---------|-----|
| `_purchase_line_id_raw` | `purchase_line_id` desde línea Odoo |
| `_purchase_line_id_from_row` | `__oc_line_id` desde fila UI |
| `_existing_purchase_line_ids` | `search` en `purchase.order.line` |
| `sanitize_group_purchase_lines` | Quita `__oc_line_id` inexistentes; warnings |
| `_should_refresh_purchase_links` | ¿Hace falta re-matchear OC antes de import? |
| `_refresh_purchase_links` | Llama `purchase_matching.enrich_rows_with_purchase_data` |
| `_dedupe_group_oc_line_ids` | Odoo no permite dos líneas con mismo `purchase_line_id` |
| `_prepare_rows_for_import` | Orquesta refresh OC → group → reconcile IVA → sanitize → dedupe |
| `plan_purchase_line_updates` | Diff `purchase_line_id` por orden UI ↔ Odoo |

**Depende de:** `_utils`, `rows`, `core.comprobante_tax.reconcile_fac_iva_for_import`, lazy `purchase_matching`.

Detalle: [purchase-oc.md](purchase-oc.md).

---

## `taxes.py`

Resolución de `tax_ids`, montos esperados y escritura en líneas `display_type=tax`.

| Función | Rol |
|---------|-----|
| `_tax_ids_from_row` | Parse `build_csv_tax_ids_dot_id` → lista de ids |
| `_otros_impuesto_slot_keys` / `_iter_otros_impuesto_slots` | Slots 1..20 otros impuestos |
| `_padron_other_tax_ids_from_row` | `_padron_other_tax_ids` sin IVA |
| `_comprobante_non_iva_tax_ids` | IIBB/percepciones en cualquier fila del grupo |
| `_merge_comprobante_non_iva_tax_ids` | En header/mixed, merge en primera línea con contenido |
| `_filter_iva_tax_ids_for_row` | Quita IVA numérico de línea en modo header |
| `_tax_ids_for_odoo_line` | **API clave:** tax_ids para una línea de producto |
| `_tax_line_id_raw` / `_line_amount_abs` | Lectura línea tax Odoo |
| `_iva_tax_id_for_rate` / `_iva_tax_resolve_row` | Mapeo alícuota → `account.tax` id del perfil |
| `collect_expected_tax_amounts_from_group` | `{tax_id: monto}` desde filas UI |
| `_account_rows_by_id` / `_account_requires_maturity` | Cuentas AP/AR para `date_maturity` |
| `_ensure_move_line_maturity` | Completa `date_maturity` en apuntes sin fecha |
| `_get_move_tax_lines` | `search_read` líneas `display_type=tax` |
| `_tax_line_amount_write_vals` | debit/credit/balance para pisar monto tax |
| `plan_tax_line_amount_overwrites` | Plan diff montos tax vs esperados |
| `_ensure_missing_tax_lines_on_move` | Refuerza `tax_ids` si falta línea tax en Odoo |
| `_ensure_iibb_tax_lines_on_move` | Alias → `_ensure_missing_tax_lines_on_move` |
| `_apply_tax_line_amount_overwrites` | Ejecuta plan + batch write |

**Depende de:** `_utils`, `core.comprobante_tax`, `padron.taxes`, lazy `move_lines`.

Detalle: [impuestos.md](impuestos.md).

---

## `planning.py`

Funciones `plan_*`: calculan qué escribir sin ejecutar RPC (salvo que el caller lo haga después).

| Función | Rol |
|---------|-----|
| `plan_invoice_origin_update` | Diff `invoice_origin` encabezado |
| `plan_move_header_updates` | Diff `invoice_date` / `invoice_date_due` |
| `plan_line_tax_updates` | Diff `tax_ids` por orden de líneas |
| `plan_product_line_content_updates` | Diff producto, qty, price, name, account |
| `_pair_product_line_for_row` | Empareja por `purchase_line_id` o índice |
| `plan_product_price_quantity_reapply` | Re-aplica solo price/qty al **final** del sync |
| `_po_link_write_vals` | Write vals para vínculo OC + price + qty + product |

**Emparejamiento:** por defecto por **orden** (`sequence,id` en Odoo ↔ filas con contenido en UI). Con OC, `plan_product_price_quantity_reapply` empareja por `purchase_line_id`.

---

## `move_lines.py`

Lectura y escritura batch de `account.move.line`.

| Función | Rol |
|---------|-----|
| `_get_move_product_lines` | Líneas editables (no tax, section, note, payment_term) |
| `_batch_write_move_lines` | Un `account.move.write` con `line_ids=[(1, id, vals), …]` |
| `_batch_write_move_lines_with_fallback` | Batch; si falla, write línea a línea + warnings |

---

## `sync.py`

Sincroniza una factura en borrador ya existente con las filas UI del comprobante.

| Función | Rol |
|---------|-----|
| `sync_move_taxes_from_group` | Pipeline completo post-create (ver [pipeline.md](pipeline.md)) |
| `update_move_taxes_from_group` | Alias retrocompatible |

**Orden interno:** encabezado → maturity → contenido + tax_ids (batch) → maturity → OC → re-aplicar price/qty → montos tax.

---

## `create.py`

Creación de moves, detección de duplicados y entrypoint HTTP.

| Función | Rol |
|---------|-----|
| `_build_move_vals` | Dict para `account.move.create` (sin OC en create inicial) |
| `_canonical_document_number` / `_document_numbers_match` | Comparación flexible de números de comprobante |
| `_move_matches_document_number` | Match por latam doc, ref o name |
| `_find_existing_move` | `search_read` por partner; filtro Python (ref almacenado) |
| `_tax_sync_summary` | Formato respuesta API para un comprobante actualizado |
| `_import_config_error_message` / `_import_odoo_target_label` | Mensajes según perfil |
| `import_rows_to_odoo` | **Entrypoint:** validar → prepare → create/update → sync |

**Duplicados:** `partner_id` + `l10n_latam_document_number` → busca por `ref`; si `skip_duplicates` y existe, sync o skip.

---

## Grafo “quién llama a quién” (runtime)

```
import_rows_to_odoo
  ├── validate_rows_for_import
  ├── _prepare_rows_for_import
  │     ├── _refresh_purchase_links → purchase_matching
  │     ├── group_rows_into_invoices / propagate_invoice_headers
  │     ├── reconcile_fac_iva_for_import
  │     ├── sanitize_group_purchase_lines
  │     └── _dedupe_group_oc_line_ids
  ├── _find_existing_move | _build_move_vals + create
  └── sync_move_taxes_from_group
        ├── plan_move_header_updates / plan_invoice_origin_update
        ├── plan_product_line_content_updates + plan_line_tax_updates
        ├── plan_purchase_line_updates + _po_link_write_vals
        ├── plan_product_price_quantity_reapply
        └── _apply_tax_line_amount_overwrites
```

---

## Tamaños aproximados (líneas)

| Archivo | ~Líneas |
|---------|---------|
| `_utils.py` | 134 |
| `rows.py` | 145 |
| `purchase.py` | 221 |
| `planning.py` | 281 |
| `move_lines.py` | 77 |
| `sync.py` | 241 |
| `create.py` | 314 |
| `taxes.py` | 547 |
| `__init__.py` | 84 |

El módulo más grande es `taxes.py` (resolución + RPC de líneas tax). Si crece más, candidatos a extraer: `tax_ids.py` vs `tax_lines_rpc.py`.
