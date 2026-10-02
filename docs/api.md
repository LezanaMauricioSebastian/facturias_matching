# API REST

Base URL local: `http://localhost:8080`. Router compuesto: `api/routes.py` (`route_meta` + `route_odoo` + `route_proceso` + `route_padron_excel`).

## Parámetros comunes

Muchos endpoints aceptan:

| Parámetro | Ubicación | Descripción |
|-----------|-----------|-------------|
| `odoo_profile_test` | query / body | `default`, `aliare`, `sudata` |
| `perfil` | query | Alias de `odoo_profile_test` |
| `odoo_cloud` | query / body | `1` / `true` → fuerza perfil `sudata` |
| `empresa` | query / body | Filtro `company_id` en MySQL |

El perfil activo queda en contexto via `odoo_profile_context` y afecta catálogo, padrón, resolución de tax ids e import.

**Aliare / Sudata:** sin `odoo_profile_test` correcto, los ids de IVA en la UI no coinciden con Odoo (ej. 21 % → id Dinner 63 vs Aliare 65). Usar siempre `?odoo_profile_test=aliare` en la URL de la app y en el body/query del import. El parámetro legacy `odoo_profile` se ignora.

---

## Página y configuración

### `GET /`

Sirve `static/html/index.html` con cache-bust de CSS/JS.

### `GET /api/metadata`

Metadata estática de la app (columnas, flags de perfil). Ver `build_metadata_payload()`.

**Respuesta**: JSON con headers, perfiles soportados, etc.

### `GET /api/bootstrap`

Carga inicial de la UI: metadata + opciones (sin padrón completo). Reusa el catálogo Odoo en memoria (`ODOO_CATALOG_CACHE_TTL`, default 600s) con **stale-while-revalidate**: si el cache expiró, responde con el catálogo viejo y refresca en background. Cold start (sin cache) sigue pegándole a Odoo (partners paginados + products/journals/…). Partners recién creados: búsqueda live `GET /api/partners/search` al tipear en Proveedor, o `?refresh=1` en bootstrap para forzar re-fetch.

**Temporal — matching automático:** al cargar/parsear un proceso (`GET /api/proceso`, remap de conversión guardada) se fuerza refresh del catálogo si `ODOO_CATALOG_FORCE_ON_MATCH=1` (default), para que partners/productos recién subidos a Odoo matcheen solos. Apagar con `0` cuando prioricen velocidad.

**Query**: `empresa`, `perfil`, `odoo_profile_test`, `odoo_cloud`, `refresh`

**Respuesta**:
```json
{
  "metadata": { },
  "options": { "proveedores": [], "journals": [], ... },
  "odoo_profile": "default"
}
```

### `GET /api/partners/search`

Búsqueda **live** de proveedores en Odoo (`name` / CUIT). Complementa el catálogo precargado (Central Ticket tiene decenas de miles de contactos).

**Query**: `q` (mín. 2 chars), `limit` (1–100), más los params de perfil/`empresa` habituales.

**Respuesta**:
```json
{ "query": "dan alan", "count": 1, "proveedores": [ { "id": 7, "name": "GORDON DAN ALAN", "vat": "20-41316809-1" } ] }
```

### `GET /api/options`

Opciones para comboboxes.

**Query**: `padron=true` para cargar listas grandes desde DB (lento).

---

## Odoo

### Health checks

`GET /api/odoo/health`, `…/health/import`, `…/health/credenciales_db` y `POST …/health/credenciales`: ver **[api-health.md](api-health.md)** (respuestas **sin** `uid`).

### `POST /api/odoo/import`

Importa filas a Odoo TEST.

**Body**:
```json
{
  "rows": [ { "...": "fila" } ],
  "skip_duplicates": true,
  "update_taxes_if_exists": true,
  "empresa": "optional",
  "odoo_profile": "aliare",
  "import_id": 12,
  "token": "callback_token_de_facturia"
}
```

`import_id` + `token` son opcionales: vienen del deep-link FacturIA (`?import_id=&token=`) tras `GET /api/process/{id}/erp-import/init`. Si están presentes, al terminar el import Odoo la app hace `POST` al webhook FacturIA (`/api/erp-imports/webhook`) para marcar el `process_erp_imports` como completed/failed. Ver [api.md § Callback FacturIA](#callback-facturia-erp-imports).

**Respuesta**: resumen por factura (creada, duplicada, errores, tax sync). Ver [import-odoo/](import-odoo/README.md). Puede incluir `facturia_webhook` con el resultado del callback.

---

## Callback FacturIA (erp-imports)

FacturIA avisa al matching UI cuándo abrir el iframe (init) y el matching UI avisa de vuelta cuando el usuario pudo guardar en Odoo (webhook).

| Env | Base | Webhook |
|-----|------|---------|
| Staging (`PROCESS_SCHEMA=sudataco_staging`) | `https://facturia-staging.sudata.co` | `POST /api/erp-imports/webhook` |
| Prod (`PROCESS_SCHEMA=sudataco_facturia`) | `https://facturia.sudata.co` | `POST /api/erp-imports/webhook` |

Override: `FACTURIA_BASE_URL` o `FACTURIA_ERP_WEBHOOK_URL`.

**Init (FacturIA, autenticado):** `GET /api/process/{process_id}/erp-import/init` → crea fila en `process_erp_imports` (`callback_token`) y abre el matching UI con `?import_id=&token=`.

**Webhook body** (matching UI → FacturIA):

```json
{
  "import_id": 12,
  "token": "…",
  "status": "completed",
  "comprobantes_importados": 1
}
```

Código: `facturia/erp_import_webhook.py`. El fallo del webhook **no** tumba el import Odoo.

---

## Padrón

### `GET /api/padron/schema`

Columnas detectadas en la vista Postgres y mapping a campos lógicos.

### `GET /api/padron/odoo`

Muestra filas de padrón construido desde facturas Odoo (diagnóstico).

**Query**: `limit` (1–500)

---

## Proceso FacturIA

### `GET /api/proceso/{process_number}`

Carga filas para la UI.

**Query**: `empresa`, `regenerate=true` (ignora conversión guardada), perfil Odoo, `excel_user=1` (o alias `pepe=1`).

Con `excel_user=1` (o `?pepe=1`): matching contra padrón Excel/Sheets (`force` refresh), sin Odoo/OC; siempre regenera desde `json_data`. Respuesta incluye `excel_user: true` y `excel_padron: { sheet_error, company_id }`. Deep link UI: `/static/?excel_user=1&proceso=N`. Ver [padron-excel.md](padron-excel.md).

**Respuesta** (campos principales):
```json
{
  "ok": true,
  "process_number": "123",
  "rows": [],
  "source": "saved | generated",
  "etiqueta_options": [],
  "purchase_matching": { "enabled": true, "comprobantes": [] },
  "conversion_id": 1,
  "saved_at": "...",
  "odoo_profile": "default",
  "excel_user": false
}
```

**Errores**: 503 MySQL no disponible; 400 conversión inválida o `json_data` vacío/corrupto en el proceso; 500 sin `json_data`.

### `GET /api/proceso/{process_number}/archivo`

Sirve el PDF/foto original del comprobante. La ruta sale de `json_data` (`facturas[i].json.archivo_original` o `factura.file_name`).

**Origen de bytes** (en orden):

1. **GCS** `gs://facturias-sudata/` (override `FACTURIA_GCS_BUCKET`):
   - staging (`PROCESS_SCHEMA` con `staging`): `conversion-staging/{company}/{process}/{file}` (fallback `conversion/…`)
   - prod: `conversion/{company}/{process}/{file}` (fallback `conversion-staging/…`)
   - si el basename no existe, también prueba espacio ↔ `_` (ej. `PATRICIO_ALEANDRI.pdf` ↔ `PATRICIO ALEANDRI.pdf`)
2. **HTTP** opcional vía `FACTURIA_FILE_URL_TEMPLATE` si GCS no encuentra el objeto.

**Query**: `comprobante_idx` (0-based), `empresa`

Las filas de `GET /api/proceso` incluyen `__fac_archivo` en la 1ª línea de cada comprobante cuando hay ruta.

**Auth GCS**: ADC del Cloud Run SA (`…-compute@developer.gserviceaccount.com`) con `roles/storage.objectViewer` en el bucket.

### `GET /api/proceso/{process_number}/facturia-raw`

**Solo staging/dev** (`PROCESS_SCHEMA` con `staging`, o `FACTURIA_UI_ENV=dev`). En prod responde **404**.

Devuelve el `json_data` crudo de FacturIA (sin conversión guardada), para la pestaña **FacturIA** de la UI.

**Query**: `empresa`

```json
{ "ok": true, "process_number": "89", "json_data": { }, "process_schema": "sudataco_staging" }
```

### `PUT /api/proceso/{process_number}/conversion`

Guarda ediciones (autosave de la UI).

**Body**:
```json
{
  "rows": [ ],
  "empresa": "optional",
  "odoo_profile": "optional"
}
```

### `POST /api/proceso/{process_number}/revert`

Borra conversión guardada y regenera desde `json_data` original.

### `POST /api/proceso/{process_number}/search-oc`

Busca y rankea OCs similares para un comprobante (bajo demanda desde el botón en UI). Guarda la conversión y devuelve `purchase_matching.oc_candidates_by_comprobante` poblado para ese comprobante, con `receipt_status_label` y `deliver_to`. Si la factura no tiene líneas de producto (p. ej. solo encabezado), igualmente lista las OCs del proveedor con score 0. Si el perfil no tiene Odoo configurado, responde 400 con un mensaje explícito en vez de devolver una lista vacía.

**Body**:
```json
{
  "comprobante_idx": 0,
  "rows": [ ],
  "empresa": "optional"
}
```

### `POST /api/proceso/{process_number}/select-oc`

Aplica una orden de compra elegida a un comprobante. `order_id: 0` = **Sin OC**: limpia vínculos y el flag de sobreescritura, pero conserva/reconsulta candidatos para que el selector quede disponible como «OC: Sin OC ▾». Ver [import-odoo/purchase-oc.md](import-odoo/purchase-oc.md#filtro-de-ocs-en-matching).

**Body**:
```json
{
  "comprobante_idx": 0,
  "order_id": 12345,
  "empresa": "optional"
}
```

### `POST /api/proceso/{process_number}/rematch-purchase`

Re-ejecuta matching OC sobre las filas actuales de un comprobante. Se llama al cambiar `partner_id`: limpia la selección anterior, invalida cache de purchase, consulta las OCs del nuevo proveedor y actualiza `oc_provider_has_ocs_by_comprobante`, por lo que el botón aparece/desaparece dinámicamente.

**Body**:
```json
{
  "comprobante_idx": 0,
  "rows": [ ],
  "empresa": "optional"
}
```

### `POST /api/proceso/{process_number}/rematch-uom`

Recalcula la UM al elegir o borrar `invoice_line_ids/product_id`, o al elegir otra UM a mano. Sin `uom_id` usa `uom_po_id` del producto (misma lógica que el matching automático). Con `uom_id`, re-escala desde qty/UM original de factura hacia esa UM (misma categoría).

**Body**:
```json
{
  "row_index": 0,
  "product_id": "620",
  "uom_id": "100",
  "row": { },
  "empresa": "optional"
}
```

`uom_id` es opcional.

**Respuesta**: `{ "ok": true, "row": { ...con __um_empresa_id... }, "uom": { ... }, "uoms": [ {"id": 1, "name": "Unidades"}, ... ] }`.

### `GET /api/proceso/{process_number}/product-uoms`

Lista UOMs de la categoría del producto **sin mutar** la fila (para abrir el selector con conversión ya guardada).

**Query**: `product_id` (requerido), `empresa`, `odoo_profile_test` opcionales.

**Respuesta**: `{ "ok": true, "product_id": "620", "uoms": [ {"id": 1, "name": "Unidades"}, ... ] }`.

---

## Export

### `POST /api/csv`

Genera CSV descargable formato import Odoo.

**Body**:
```json
{
  "rows": [ ]
}
```

**Respuesta**: `StreamingResponse` `text/csv`.

---

## Códigos de error frecuentes

| HTTP | Causa |
|------|-------|
| 400 | Payload inválido, `comprobante_idx` mal, conversión corrupta |
| 503 | MySQL no configurado o caído |
| 500 | `json_data` ausente o ilegible; error interno no capturado |

Detalle en JSON: `{ "detail": "mensaje" }` (FastAPI).

---

## Secuencia típica de la UI

```
GET  /api/bootstrap?odoo_profile_test=aliare
GET  /api/proceso/12345?odoo_profile_test=aliare
PUT  /api/proceso/12345/conversion        (repetido, debounced)
POST /api/odoo/import                     (o POST /api/csv)
```

---

## Padrón Excel

Página: `/static/padron_excel.html`. Detalle: [padron-excel.md](padron-excel.md).

| Método | Path | Uso |
|--------|------|-----|
| GET/PUT | `/api/padron-excel/config` | URL Sheets / `spreadsheet_id` + mapeo (`company_id`) |
| POST | `/api/padron-excel/upload` | Multipart `file` + `kind` (`proveedores` \| `productos` \| `formas_pago` \| `conceptos`) |
| GET | `/api/padron-excel/data` | Listas estructuradas del padrón |
| POST | `/api/padron-excel/preview` | Columnas y sample (URL pub o `spreadsheet_id` + SA) |
| POST | `/api/padron-excel/sheets` | URL/`spreadsheet_id` compartido al SA → lista de hojas (`title`, `gid`, `index`) |
| POST | `/api/padron-excel/sheets/row` | Primera fila (headers) de una hoja (`sheet_gid` y/o `sheet_title`). Alias: `/sheets/column` |
| GET | `/api/padron-excel/entrega` | Columnas del `export_template` para un proceso (`id_cliente`, `proceso`, `id_template`) + `is_dropdown` |
| GET | `/api/padron-excel/proceso/{n}` | FacturIA `json_data` → fuzzy match contra padrón actual (`force_refresh` default true) |
| POST | `/api/padron-excel/match` | `field`: `proveedor` \| `producto` \| `concepto` \| `forma_pago`; opcional `cuit`, `unidades_medida` |
| GET/POST | `/api/padron-excel/facturas` | CRUD de facturas con matching |
| GET | `/api/padron-excel/facturas/export/csv` | Export layout Gastos Pepe (`pepe_schema.PEPE_GASTOS_COLUMNS`) |

### `POST /api/padron-excel/sheets`

Body: `{ "url": "https://docs.google.com/spreadsheets/d/<id>/edit" }` o `{ "spreadsheet_id": "<id>" }`.

Respuesta: `{ "spreadsheet_id", "title", "sheets": [{ "title", "sheet_id", "gid", "index" }] }`.

### `POST /api/padron-excel/sheets/row`

Body: `{ "url"|"spreadsheet_id", "sheet_gid"?, "sheet_title"?, "skip_empty": true }`. Si no pasás hoja, usa la primera pestaña. Alias legacy: `/sheets/column` (misma respuesta).

Respuesta: `{ "spreadsheet_id", "sheet_title", "sheet_gid", "values": [...], "count" }` — celdas de la **fila 1** (headers).

### Entrega por template

`GET /api/padron-excel/entrega?id_cliente=&proceso=&id_template=`

Lee `export_templates` / `export_template_sheets` / `export_template_columns` del schema `PROCESS_SCHEMA` (`deleted_at` nulo; el template es de ese `company_id` o global). Matchea el proceso como `?excel_user=1` y devuelve solo las columnas del template.

`is_dropdown: true` si la columna apunta a una lista del Sheet o si el origen es un catálogo (`cabecera.proveedor.*`, `cabecera.concepto`, forma de pago, `items[].producto`, rubro, diario). `options` son los valores de `lookup_return_column`, o de `lookup_match_column` si el retorno viene vacío. La tilde `lookup_suggest` llena la celda con el matching Excel: proveedor por CUIT/nombre, y concepto + categoría con historial de Gastos e IA. Sin tilde, la lista queda para elegir y la celda no se autocompleta. Fecha, Monto, Fecha de pago y Observación se completan con la factura del proceso (fecha, total, vencimiento, observaciones).

Una hoja con alguna columna `items[]` devuelve una fila por ítem (`should_repeat=0` deja la cabecera vacía desde la segunda línea). Sin columnas de ítem, una fila por comprobante.

`sheet_error` avisa si no se pudo leer el Sheet. Para ver los templates de staging el server tiene que correr con `PROCESS_SCHEMA=sudataco_staging`.

### Matching proceso FacturIA

`GET /api/padron-excel/proceso/{n}?empresa=&company_id=&force_refresh=1` — lee el `json_data` del proceso, fuerza refresh del Sheet/Excel y devuelve facturas matcheadas + padrón.

Iframe admin: `/static/padron_excel.html?embed=1&proceso={n}&empresa={id}`.

UI principal (misma grilla): `/static/?excel_user=1&proceso={n}&empresa={id}` → `GET /api/proceso/{n}?excel_user=1`. Env: `GOOGLE_SERVICE_ACCOUNT_JSON` (path o JSON) para Sheets privados.

---

## Extender la API

1. Agregar handler en `api/route_meta.py`, `route_odoo.py` o `route_proceso.py` (facade `routes.py`).
2. Si usa Odoo: envolver con `_with_odoo_profile`.
3. Errores de dominio: `ProcessConversionError` → 400; `MySQLUnavailableError` → 503.
4. Documentar payload aquí y en el módulo de dominio que implementa la lógica.
