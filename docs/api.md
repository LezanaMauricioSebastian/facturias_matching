# API REST

Base URL local: `http://localhost:8080`. Router: `api/routes.py`.

## Parámetros comunes

Muchos endpoints aceptan:

| Parámetro | Ubicación | Descripción |
|-----------|-----------|-------------|
| `odoo_profile` | query / body | `default`, `aliare`, `sudata` |
| `perfil` | query | Alias de `odoo_profile` |
| `odoo_cloud` | query / body | `1` / `true` → fuerza perfil `sudata` |
| `empresa` | query / body | Filtro `company_id` en MySQL |

El perfil activo queda en contexto via `odoo_profile_context` y afecta catálogo, padrón, resolución de tax ids e import.

**Aliare / Sudata:** sin `odoo_profile` correcto, los ids de IVA en la UI no coinciden con Odoo (ej. 21 % → id Dinner 63 vs Aliare 65). Usar siempre `?odoo_profile=aliare` en la URL de la app y en el body/query del import.

---

## Página y configuración

### `GET /`

Sirve `static/html/index.html` con cache-bust de CSS/JS.

### `GET /api/metadata`

Metadata estática de la app (columnas, flags de perfil). Ver `build_metadata_payload()`.

**Respuesta**: JSON con headers, perfiles soportados, etc.

### `GET /api/bootstrap`

Carga inicial de la UI: metadata + opciones ligeras (sin padrón completo).

**Query**: `empresa`, `perfil`, `odoo_profile`, `odoo_cloud`

**Respuesta**:
```json
{
  "metadata": { },
  "options": { "proveedores": [], "journals": [], ... },
  "odoo_profile": "default"
}
```

### `GET /api/options`

Opciones para comboboxes.

**Query**: `padron=true` para cargar listas grandes desde DB (lento).

---

## Odoo

### `GET /api/odoo/health`

Conexión al tenant principal del perfil (uid, db, version).

### `GET /api/odoo/health/import`

Conexión al tenant de **import** (puede coincidir o no con el principal según perfil).

### `POST /api/odoo/import`

Importa filas a Odoo TEST.

**Body**:
```json
{
  "rows": [ { "...": "fila" } ],
  "skip_duplicates": true,
  "update_taxes_if_exists": true,
  "empresa": "optional",
  "odoo_profile": "aliare"
}
```

**Respuesta**: resumen por factura (creada, duplicada, errores, tax sync). Ver [import-odoo/](import-odoo/README.md).

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

**Query**: `empresa`, `regenerate=true` (ignora conversión guardada), perfil Odoo.

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
  "odoo_profile": "default"
}
```

**Errores**: 503 MySQL no disponible; 400 conversión inválida o `json_data` vacío/corrupto en el proceso; 500 sin `json_data`.

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

### `POST /api/proceso/{process_number}/select-oc`

Aplica una orden de compra elegida a un comprobante.

**Body**:
```json
{
  "comprobante_idx": 0,
  "order_id": 12345,
  "empresa": "optional"
}
```

### `POST /api/proceso/{process_number}/rematch-purchase`

Re-ejecuta matching OC sobre filas actuales de un comprobante.

**Body**:
```json
{
  "comprobante_idx": 0,
  "rows": [ ],
  "empresa": "optional"
}
```

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
GET  /api/bootstrap?odoo_profile=aliare
GET  /api/proceso/12345?odoo_profile=aliare
PUT  /api/proceso/12345/conversion        (repetido, debounced)
POST /api/odoo/import                     (o POST /api/csv)
```

---

## Extender la API

1. Agregar handler en `api/routes.py`.
2. Si usa Odoo: envolver con `_with_odoo_profile`.
3. Errores de dominio: `ProcessConversionError` → 400; `MySQLUnavailableError` → 503.
4. Documentar payload aquí y en el módulo de dominio que implementa la lógica.
