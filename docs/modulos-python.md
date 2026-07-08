# Módulos Python (`src/facturia_matching/`)

Referencia archivo por archivo. Rutas relativas a `src/facturia_matching/`.

---

## Raíz del paquete

| Archivo | Rol |
|---------|-----|
| `main.py` | Crea `FastAPI`, CORS, monta estáticos, incluye `api.routes.router`. |
| `__init__.py` | Marcador de paquete. |

---

## `api/`

| Archivo | Rol |
|---------|-----|
| `routes.py` | Todos los endpoints. Helpers `_resolve_request_odoo_profile`, `_build_proceso_response`, manejo de errores MySQL/conversión. |
| `__init__.py` | Vacío / export mínimo. |

**Funciones clave en `routes.py`:**

- `_with_odoo_profile()` — context manager por request.
- `_build_proceso_response()` — envuelve filas con `build_output_rows`, metadata de conversión y purchase matching.

---

## `core/`

| Archivo | Rol |
|---------|-----|
| `process.py` | **`parse_process_json`**: JSON FacturIA → filas; matching proveedor/cuenta/diario/tipo doc; aplica impuestos padrón; enriquece OC. **`build_output_rows`**: ordena columnas para UI. **`attach_facturia_item_quantities`**, **`backfill_fac_iva_montos_from_process`**. |
| `comprobante_tax.py` | Modos `line` / `header` / `mixed`; totales por comprobante; **`fac_iva_montos`** / **`_explicit_fac_iva_montos`** (parseo es-AR del JSON del pie; en `header` con una alícuota usa `__fac_iva_monto` aunque el precio de línea no cierre con el %); `sanitize_inflated_line_amounts`; **`reconcile_fac_iva_for_import`** (no recalcula desde líneas si hay pie en header/mixed). **Debe parity con JS** (`ivaBreakdown.js`, `rows/totals.js`). |
| `amounts.py` | Parseo de montos FacturIA (`parse_amount_loose`, `_sanitize_hybrid_amount_string` para híbridos tipo `350.0,00`); `fac_header_amount_str`, percepciones, qty/price. |
| `options.py` | Opciones para comboboxes: desde Odoo catalog y/o Postgres (`get_options`, `build_metadata_payload`). |
| `constants.py` | `OUTPUT_HEADERS`, headers CSV, columnas purchase, `IVA_OPTIONS`, `append_purchase_columns`. |
| `__init__.py` | Re-exports si aplica. |

---

## `padron/`

| Archivo | Rol |
|---------|-----|
| `postgres.py` | Cache de vista padrón; `detect_padron_fields`; **`match_proveedor`** (fuzzy CUIT/nombre); `get_table_columns`. Respeta `PADRON_SOURCE` y orden Odoo-first en Aliare/Sudata. |
| `odoo.py` | **`build_padron_rows_from_odoo`**: últimas facturas proveedor → filas estilo padrón (rubro, cuenta, diario). |
| `taxes.py` | Padrón fiscal; **`match_padron_taxes`**, **`apply_padron_taxes_to_row`** (solo slot 1 en UI; `_padron_other_tax_ids` para import); resolución label → tax id; IVA por alícuota desde catálogo Odoo del perfil activo; remapeo ids padrón vía `PADRON_TAX_SOURCE_PROFILE`; IIBB/percepciones por nombre. |
| `__init__.py` | Marcador. |

---

## `odoo/`

| Archivo | Rol |
|---------|-----|
| `env.py` | Perfiles, URLs, DB name resolution, `build_odoo_*_config`, `get_conversion_template_id`, flags `is_odoo_aliare_profile`, `uses_odoo_padron_first`. |
| `request_context.py` | `contextvars` para `odoo_profile` del request actual. |
| `api.py` | Conexión XML-RPC: `get_odoo_uid`, `odoo_search_read`, `get_active_odoo_config`, health checks. |
| `catalog.py` | **`get_catalog`** (cache): proveedores, journals, accounts, rubros, document types; maps para resolve por nombre/CUIT; `invalidate_catalog_cache`. |
| `document_types_i18n.py` | Normalización de etiquetas de tipos de comprobante latam. |
| `import_/` | Paquete de import a Odoo. **Documentación:** [docs/import-odoo/](../docs/import-odoo/README.md). Submódulos: `_utils`, `rows`, `purchase`, `taxes`, `planning`, `move_lines`, `sync`, `create`; `__init__.py` reexporta API pública. |
| `purchase_matching.py` | **`enrich_rows_with_purchase_data`**, **`apply_oc_selection`**, **`rematch_comprobante_purchase`**: fuzzy match líneas factura ↔ PO. `fetch_partner_po_lines` excluye OCs con `receipt_status=pending` (Odoo «No recibido»). |
| `__init__.py` | Marcador. |

---

## `persistence/`

| Archivo | Rol |
|---------|-----|
| `back_check.py` | **`get_process`**: lee MySQL `process` por `process_number` (+ `empresa`). Excepciones `MySQLUnavailableError`, `ProcessTableError`. |
| `process_conversions.py` | **`load_process_rows`**, **`save_conversion`**, **`delete_conversion`**, **`get_saved_conversion`**, **`infer_otro_impuesto_indices`**, **`_strip_empty_extra_otro_impuesto_slots`**. Tabla `process_conversions` + FK `export_templates`. |
| `saved_row_remap.py` | **`remap_saved_rows_to_catalog`**: al abrir conversión guardada, actualiza IDs de producto/tipo doc/etc. si el catálogo cambió. |
| `__init__.py` | Marcador. |

---

## `export/`

| Archivo | Rol |
|---------|-----|
| `csv_export.py` | **`build_csv_response`**: StreamingResponse CSV con headers Odoo y columnas dinámicas de otros impuestos. |
| `__init__.py` | Marcador. |

---

## `infra/`

| Archivo | Rol |
|---------|-----|
| `config.py` | Variables globales de BD; **`pg_connect`**, **`get_mysql_connection`**; constantes `DB_TABLE_NAME`, `PADRON_*`. |
| `env.py` | **`env_strip`** y helpers de lectura `.env`. |
| `db_resolve.py` | **`resolved_pg_dbname`**, **`mysql_connect_kwargs`**: autodetect DB cuando falta nombre. |
| `paths.py` | `HTML_DIR`, `JS_DIR`, `CSS_DIR`, `ENV_FILE`. |
| `normalization.py` | `normalize`, fechas DD/MM/YYYY, `normalize_comprobante_number`, `doc_type_label`. |
| `__init__.py` | Marcador. |

---

## Grafo de imports críticos

```
parse_process_json (core/process.py)
  ├── get_process (persistence/back_check)
  ├── get_catalog (odoo/catalog)
  ├── match_proveedor (padron/postgres)
  ├── apply_padron_taxes_to_row (padron/taxes)
  ├── enrich_rows_with_purchase_data (odoo/purchase_matching)
  └── sanitize_inflated_line_amounts (core/comprobante_tax)

load_process_rows (persistence/process_conversions)
  ├── get_saved_conversion / save_conversion
  ├── parse_process_json (si no hay guardado o regenerate)
  └── remap_saved_rows_to_catalog (si hay guardado)

import_rows_to_odoo (odoo/import_/create.py)
  ├── group_rows_into_invoices (odoo/import_/rows.py)
  ├── _prepare_rows_for_import (odoo/import_/purchase.py)
  ├── reconcile_fac_iva_for_import (core/comprobante_tax)
  └── sync_move_taxes_from_group (odoo/import_/sync.py)
        ├── plan_* (odoo/import_/planning.py)
        ├── vínculos OC (odoo/import_/purchase.py)
        ├── _ensure_missing_tax_lines_on_move (odoo/import_/taxes.py)
        ├── _apply_tax_line_amount_overwrites (odoo/import_/taxes.py)
        └── plan_product_price_quantity_reapply (odoo/import_/planning.py)
```

Detalle paso a paso: [import-odoo/pipeline.md](import-odoo/pipeline.md).

---

## Entrypoints fuera del paquete

| Archivo | Rol |
|---------|-----|
| `/main.py` (raíz) | `uvicorn.run("facturia_matching.main:app", ...)`. |

---

## Variables de entorno (puntero)

No duplicar la lista completa: ver `.env.example`, `.env.aliare.example`, `.env.sudata.example`.

Agrupadas por consumidor:

- **Postgres**: `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_TABLE_NAME`, `DB_TABLE_NAME_TAXES`
- **MySQL**: `DB_HOST_MYSQL`, `DB_USER_MYSQL`, `DB_PASSWORD_MYSQL`, `DB_NAME_MYSQL`
- **Odoo default**: `ODOO_BASE_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_PASSWORD` / `ODOO_API_KEY`
- **Odoo Aliare/Sudata**: mismas claves con sufijo `_ALIARE` / `_SUDATA`
- **Comportamiento**: `PADRON_SOURCE`, `PADRON_TAX_SOURCE_PROFILE`, `PADRON_FUZZY_MIN_SCORE`, `PADRON_LIMIT`

Definición en `infra/config.py` y `odoo/env.py`.
