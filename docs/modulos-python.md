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
| `routes.py` | Facade: compone `route_meta` + `route_odoo` + `route_proceso` + `route_padron_excel`. |
| `profile.py` | `_resolve_request_odoo_profile`, `_with_odoo_profile`, `_public_health_payload`. |
| `proceso_response.py` | `_build_proceso_response`, `_handle_process_load_errors` (MySQL→503 / conversión→400). |
| `route_meta.py` | `/`, metadata, bootstrap, options, padrón, CSV. |
| `route_odoo.py` | Health Odoo + `POST /api/odoo/import` (+ callback FacturIA erp-imports si hay `import_id`/`token`). |
| `route_proceso.py` | `/api/proceso/*` (load, OC, UM, conversion, revert). |
| `route_padron_excel.py` | `/api/padron-excel/*`: config, upload CSV/XLSX, match, CRUD facturas, export. |
| `__init__.py` | Vacío / export mínimo. |

**Funciones clave:**

- `_with_odoo_profile()` (`profile.py`) — context manager por request.
- `_build_proceso_response()` (`proceso_response.py`) — envuelve filas con `build_output_rows`, metadata de conversión y purchase matching.

---

## `core/`

| Archivo | Rol |
|---------|-----|
| `process.py` | **`parse_process_json`**: JSON FacturIA → filas; matching proveedor/cuenta/diario/tipo doc; aplica **memoria de cabecera** (diario/cuenta/rubro desde conversiones pasadas del mismo partner) sobre el fuzzy del padrón; aplica impuestos padrón; enriquece OC. **`build_output_rows`**: ordena columnas para UI. **`attach_facturia_item_quantities`**, **`backfill_fac_iva_montos_from_process`**. |
| `comprobante_tax.py` | Modos `line` / `header` / `mixed`; totales por comprobante; **`fac_iva_montos`** / **`_explicit_fac_iva_montos`** (parseo es-AR del JSON del pie; en `header` con una alícuota usa `__fac_iva_monto` aunque el precio de línea no cierre con el %); `sanitize_inflated_line_amounts`; **`propagate_single_footer_iva_to_lines`** (un solo IVA en el pie → `iva_pct` en líneas vacías); **`reconcile_fac_iva_for_import`** (no recalcula desde líneas si hay pie en header/mixed). **Debe parity con JS** (`ivaBreakdown.js`, `rows/totals.js`, `migration.js`). |
| `amounts.py` | Parseo de montos FacturIA (`parse_amount_loose`, `_sanitize_hybrid_amount_string` para híbridos tipo `350.0,00`); **`format_fac_amount_for_ui`** (coma decimal sin miles, evita que `15.175` se lea como 15175); `fac_header_amount_str`, percepciones, qty/price. |
| `options.py` | Opciones para comboboxes: desde Odoo catalog y/o Postgres (`get_options`, `build_metadata_payload`). **`otros_impuestos_options_from_odoo`**: **todos** los `account.tax` del tenant (orden alfabético; EN→ES para Internal/Other taxes). |
| `constants.py` | `OUTPUT_HEADERS`, headers CSV, columnas purchase, `IVA_OPTIONS`, `append_purchase_columns`. |
| `__init__.py` | Re-exports si aplica. |

---

## `padron/`

| Archivo | Rol |
|---------|-----|
| `postgres.py` | Cache de vista padrón; `detect_padron_fields`; **`match_proveedor`** (fuzzy CUIT/nombre); `get_table_columns`. Respeta `PADRON_SOURCE` y orden Odoo-first en Aliare/Sudata. |
| `odoo.py` | **`build_padron_rows_from_odoo`**: últimas facturas proveedor → filas estilo padrón (rubro, cuenta, diario). |
| `excel.py` | Fuzzy padrón Excel: **`match_proveedor_excel`** (CUIT exacto → razón/fantasía), **`match_producto`** (nombre + UoM), concepto/forma de pago. |
| `sheet_loader.py` | Fetch CSV de Sheets publicado; parse CSV/XLSX (upload); mapeo de columnas a proveedores/productos. |
| `catalog_excel.py` | Arma el padrón estructurado desde config (URL + archivos subidos). |
| `padron_config_store.py` | JSON en `data/padrones/` (mapeo, URL, paths de upload). |
| `excel_store.py` | JSON de facturas cargadas en la UI Excel (`data/facturas_excel.json`). |
| `taxes.py` | Padrón fiscal; **`match_padron_taxes`**, **`apply_padron_taxes_to_row`** (solo slot 1 en UI; `_padron_other_tax_ids` para import); resolución label → tax id (IIBB por jurisdicción + alias Aliare `Perc Gananc` / `Perc IVA`); IVA por alícuota desde catálogo Odoo del perfil activo; remapeo ids padrón vía `PADRON_TAX_SOURCE_PROFILE`. |
| `__init__.py` | Marcador. |

---

## `odoo/`

| Archivo | Rol |
|---------|-----|
| `env.py` | Perfiles, URLs, DB name resolution, `build_odoo_*_config`, `get_conversion_template_id`, flags `is_odoo_aliare_profile`, `uses_odoo_padron_first`, idioma RPC `resolve_odoo_lang` (env → primer idioma instalado de `ODOO_LANG_CANDIDATES` → default por perfil). |
| `request_context.py` | `contextvars` para `odoo_profile` del request actual. |
| `api.py` | Conexión XML-RPC: `get_odoo_uid`, `odoo_search_read`, `get_active_odoo_config`, health checks, `odoo_model_field_names` / `odoo_available_fields` (campos existentes por tenant+modelo: pedir uno inexistente falla el `search_read` completo). |
| `catalog.py` | **`get_catalog`** (cache): proveedores/contactos, journals, accounts, rubros, document types; maps para resolve por nombre/CUIT; `invalidate_catalog_cache`. Perfil **aliare**: catálogo de partners sin filtrar `supplier_rank` (todos los contactos). |
| `document_types_i18n.py` | Normalización de etiquetas de tipos de comprobante latam; **`is_credit_note_doc_type_name`**. |
| `import_/` | Paquete de import a Odoo. **Documentación:** [docs/import-odoo/](../docs/import-odoo/README.md). Submódulos: `_utils`, `rows`, `purchase`, `taxes`, `planning`, `move_lines`, `sync`, `create`; `__init__.py` reexporta API pública. |
| `purchase_matching/` | Paquete (antes un solo `.py`). **`enrich_rows_with_purchase_data`**, **`search_oc_candidates_for_comprobante`**, **`apply_oc_selection`**, **`rematch_comprobante_purchase`**, **`apply_product_uom_to_row`**, **`list_uoms_for_product`**: fuzzy match factura ↔ PO + UM + aprendizaje (`company_id`). Submódulos: `_util`, `uom`, `uom_ai` (Claude), `scoring`, `oc`, `match`. Docs: [import-odoo/purchase-matching.md](import-odoo/purchase-matching.md), [purchase-matching-modulos.md](import-odoo/purchase-matching-modulos.md). |
| `__init__.py` | Marcador. |

---

## `persistence/`

| Archivo | Rol |
|---------|-----|
| `back_check.py` | **`get_process`**: lee MySQL `process` por `process_number` (+ `empresa`); **ignora bajas lógicas** (`deleted_at IS NULL`). Excepciones `MySQLUnavailableError`, `ProcessTableError`. |
| `process_conversions.py` | **`load_process_rows`**, **`save_conversion`**, **`delete_conversion`**, **`get_saved_conversion`**, **`infer_otro_impuesto_indices`**, **`_strip_empty_extra_otro_impuesto_slots`**. Tabla `process_conversions` + FK `export_templates`. |
| `product_label_memory.py` | Tabla `product_label_memory` en `PROCESS_SCHEMA` (staging/prod). **`MemoryChoice`**, **`ensure_product_label_memory_table`**, **`upsert_product_memory_choices`**, **`build_memory_index_for_company`** / **`lookup_in_index`**: última elección confirmada de producto + UM por `partner_id` + etiqueta. Seed / `fetch_recent_conversion_row_lists` **excluye** procesos con `deleted_at` (baja lógica). |
| `partner_header_memory.py` | **Sin tabla nueva.** Índice diario/cuenta/rubro por `partner_id` desde las últimas ~100 `process_conversions` vía `fetch_recent_conversion_row_lists` (también excluye bajas lógicas). `apply_learned_header_ids` en `parse_process_json` (prioridad sobre padrón; ids deben existir en el catálogo del perfil). |
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

## `facturia/`

| Archivo | Rol |
|---------|-----|
| `erp_import_webhook.py` | **`notify_erp_import_webhook`**: `POST /api/erp-imports/webhook` a FacturIA (staging/prod) con `import_id` + `token` tras import Odoo. |
| `__init__.py` | Marcador. |

---

## Grafo de imports críticos

```
parse_process_json (core/process.py)
  ├── get_process (persistence/back_check)
  ├── get_catalog (odoo/catalog)
  ├── match_proveedor (padron/postgres)
  ├── apply_padron_taxes_to_row (padron/taxes)
  ├── enrich_rows_with_purchase_data (odoo/purchase_matching/)
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
- **UM con IA**: `FACTURIA_UOM_AI_ENABLED`, `ANTHROPIC_API_KEY`, opcional `FACTURIA_UOM_AI_MODEL`

Definición en `infra/config.py` y `odoo/env.py`.
