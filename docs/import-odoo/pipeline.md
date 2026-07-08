# Pipeline de import

Secuencia temporal desde filas UI hasta factura sincronizada en Odoo.

Ver también: [iva-y-import-odoo.md](../iva-y-import-odoo.md) (reglas fiscales), [purchase-oc.md](purchase-oc.md), [impuestos.md](impuestos.md).

---

## Vista general

```mermaid
sequenceDiagram
  participant UI as Filas UI
  participant Entry as import_rows_to_odoo
  participant Prep as _prepare_rows_for_import
  participant Create as account.move.create
  participant Sync as sync_move_taxes_from_group
  participant Odoo as Odoo XML-RPC

  UI->>Entry: List[dict]
  Entry->>Entry: validate_rows_for_import
  Entry->>Prep: config, rows
  Prep->>Prep: refresh OC, group, reconcile IVA
  loop Por comprobante
    alt Duplicado skip_duplicates
      Entry->>Odoo: search_read ref
      Entry->>Sync: move existente
    else Nuevo
      Entry->>Create: _build_move_vals
      Create->>Odoo: create in_invoice
      Entry->>Sync: move_id nuevo
    end
    Sync->>Odoo: writes líneas y encabezado
  end
  Entry-->>UI: ok, created, updated_taxes, errors
```

---

## `import_rows_to_odoo`

**Archivo:** `create.py`

### 1. Configuración y autenticación

```python
config = get_odoo_import_config()
uid = get_odoo_uid_from_config(config)
```

Si faltan variables o falla auth → `{"ok": False, "error": "…"}`.

### 2. Validación

`validate_rows_for_import(rows)` — sin llamadas Odoo. Agrupa internamente con `propagate_invoice_headers` para validar cabecera por comprobante.

### 3. Preparación global

```python
groups, import_warnings = _prepare_rows_for_import(config, rows)
```

Una sola vez por request. Ver [\_prepare_rows_for_import](#_prepare_rows_for_import).

### 4. Por cada grupo (comprobante)

| Paso | Condición | Acción |
|------|-----------|--------|
| Buscar duplicado | `skip_duplicates` y hay partner + doc | `_find_existing_move` |
| Ya existe + `update_taxes_if_exists` | encontrado | `sync_move_taxes_from_group` → `updated_taxes` |
| Ya existe sin update | encontrado | `skipped` reason `already_exists` |
| Nuevo | no encontrado | `_build_move_vals` → `account.move.create` |
| Post-create | siempre (nuevo) | `sync_move_taxes_from_group` |
| Error en sync | excepción | factura creada pero `errors` con detalle |

### 5. Respuesta

```python
{
  "ok": bool,
  "uid": int,
  "db": str,
  "base_url": str,
  "created": [...],
  "updated_taxes": [...],  # _tax_sync_summary por comprobante
  "skipped": [...],
  "errors": [...],
}
```

`ok` es false si hubo errores mezclados con trabajo exitoso, o si no se hizo nada.

---

## `_prepare_rows_for_import`

**Archivo:** `purchase.py`

Orden fijo:

1. **Refresh OC** (si `_move_line_supports_purchase_link` y `_should_refresh_purchase_links`)
   - Llama `purchase_matching.enrich_rows_with_purchase_data`
   - Rellena `__oc_line_id` frescos
2. **Agrupar** — `group_rows_into_invoices` + `propagate_invoice_headers` por grupo
3. **Reconcile IVA** — `reconcile_fac_iva_for_import(group)` en cada grupo (no pisa pie en header/mixed)
4. **Sanitize OC** — si purchase soportado: `sanitize_group_purchase_lines` (quita ids inexistentes)
5. **Re-refresh** — si hubo sanitize, vuelve a matchear OC y re-agrupa
6. **Dedupe** — `_dedupe_group_oc_line_ids` por grupo

Devuelve `(groups, warnings)`; los warnings del primer grupo se adjuntan al resultado de sync de ese comprobante.

---

## `sync_move_taxes_from_group`

**Archivo:** `sync.py`

**Precondición:** factura en estado `draft` (si no → `ValueError`).

### Paso 1 — Encabezado

- `plan_move_header_updates` → `invoice_date`, `invoice_date_due`
- `plan_invoice_origin_update` → `invoice_origin`
- Un solo `account.move.write` si hay cambios

### Paso 2 — Fecha límite (primera pasada)

`_ensure_move_line_maturity` si hay `due_date_iso`

### Paso 3 — Líneas de producto (contenido + tax_ids)

- `plan_product_line_content_updates`
- `plan_line_tax_updates`
- **Merge** writes por `line_id` (contenido + `tax_ids` en un batch)
- `_batch_write_move_lines`
- Re-lee `product_lines`

### Paso 4 — Fecha límite (segunda pasada)

Si se completaron apuntes → warning con cantidad

### Paso 5 — Vínculos OC

Solo si `_move_line_supports_purchase_link`:

- `plan_purchase_line_updates`
- Por cada update: `_po_link_write_vals` (OC + price + qty + product)
- `_batch_write_move_lines_with_fallback` (context `"OC"`)
- Re-lee `product_lines` si hubo cambios

### Paso 6 — Re-aplicar precio y cantidad

Solo si purchase soportado:

- `plan_product_price_quantity_reapply` (empareja por OC o orden)
- `_batch_write_move_lines`

**Por qué antes de montos tax:** Odoo puede resetear `price_unit` al vincular OC; el precio UI debe quedar fijo antes de pisar IVA/IIBB.

### Paso 7 — Montos en líneas tax (último paso)

`_apply_tax_line_amount_overwrites`:

- `collect_expected_tax_amounts_from_group`
- `_ensure_missing_tax_lines_on_move` si faltan líneas tax (sin borrar `tax_ids`)
- `plan_tax_line_amount_overwrites` + batch write
- `_ensure_move_line_maturity` otra vez

**Por qué al final:** Odoo recalcula impuestos al vincular OC, al tocar `tax_ids` y al re-aplicar precio. Los montos del pie (IVA y otros impuestos / IIBB CABA) deben **sobreescribir** ese recálculo.

### Retorno

Dict con contadores (`product_lines_updated`, `tax_lines_updated`, …), listas de updates, `expected_tax_amounts`, `warnings`.

---

## `_build_move_vals` (create inicial)

**Archivo:** `create.py`

- `move_type`: `in_invoice`
- `partner_id`, `journal_id`, `invoice_date`, `invoice_date_due`
- `l10n_latam_document_number` + **`ref`** (mismo número — searchable en Odoo 19)
- `l10n_latam_document_type_id`, `x_studio_category` (si perfil soporta rubro)
- `invoice_origin` si hay OC
- `invoice_line_ids`: comandos `(0, 0, vals)` **sin** `purchase_line_id` ni `product_id` en create inicial (el sync los aplica después)

---

## `_find_existing_move`

**Archivo:** `create.py`

1. Domain: `move_type=in_invoice`, `partner_id`, opcionalmente `ref=doc_number`
2. `search_read` hasta 50/200 candidatos
3. Filtro Python: `_move_matches_document_number` (latam doc, ref, name con sufijos)

No filtra por `l10n_latam_document_number` en domain (campo computed sin store en Odoo 19+).

---

## Orden crítico (no reordenar sin tests)

| # | Operación | Motivo |
|---|-----------|--------|
| 1 | Contenido + tax_ids en producto | Base antes de tax lines |
| 2 | Vínculo OC | Odoo recalcula taxes y precio |
| 3 | Price/qty reapply | Pisa precio PO post-OC |
| 4 | Montos líneas tax | Pisa recálculo de Odoo (IVA + IIBB); **último paso** |

Tests de regresión: `test_plan_product_price_quantity_reapply_*` en `tests/test_odoo_import.py`.

---

## Errores frecuentes en runtime

| Síntoma | Revisar |
|---------|---------|
| "no está en borrador" | Factura ya publicada; sync solo en draft |
| "falta proveedor / diario" | `validate_rows_for_import` |
| OC no vincula | `__oc_line_id`, `sanitize_*`, Sudata sin purchase |
| IVA distinto al pie | `collect_expected_*`, [impuestos.md](impuestos.md) |
| IIBB / CABA no se sobreescribe al primer import | Orden sync: montos tax deben ir **después** de re-aplicar precio; ver paso 7 |
| Precio = precio PO | Falta paso 6 o `plan_product_price_quantity_reapply` |
| Fecha límite AP/AR | `_ensure_move_line_maturity`, [impuestos.md](impuestos.md#fecha-límite-date_maturity) |
