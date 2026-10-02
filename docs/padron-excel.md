# Padrón Excel / Sheets (clientes sin Odoo)

UI admin: `/static/padron_excel.html`. API: `/api/padron-excel/*`.

Matching de proveedores/productos/conceptos/forma de pago contra un padrón del cliente (sin Odoo).

## UI principal con `?excel_user=1`

Para mostrar al cliente el matching Excel **dentro de la UI de proceso** (misma grilla que Odoo):

```
/static/?excel_user=1&proceso=123&empresa=1
```

Alias de demo (mismo modo; `company_id` del padrón fijado a `0`):

```
/static/?pepe=1&proceso=123
```

Comportamiento:

- `GET /api/proceso/{n}?excel_user=1&empresa=…` regenera filas desde `json_data` con `load_padron` (respeta TTL del Sheet; no fuerza re-lectura en cada F5). `empresa` se envía siempre que haya una activa (URL / proceso); si no viene, el backend usa la del proceso.
- `GET /api/padron-excel/data?empresa=&company_id=` también acepta `empresa` (default de `company_id` si este se omite).
- Match proveedor (CUIT / fuzzy), producto (+ UoM) y **concepto** si el Sheet trae conceptos (best-effort).
- Sin import Odoo, sin columnas/OC de purchase matching. También se ocultan Rubros, Diario y Cuenta (solo Odoo).
- Badge «Padrón Excel»; botones **Restaurar original** (descarta conversión y regenera desde FacturIA) y **Re-matchear** (vuelve a leer el Sheet).
- Los combobox **Proveedor** / **Producto** / **Concepto** listan el padrón del Sheet (no Odoo). FacturIA no trae concepto aparte: el match inicial es fuzzy sobre la descripción de línea; el desplegable sirve para corregir a mano.
- **Copiar / Descargar CSV** exportan la **grilla visible** (labels y valores de preview: proveedor/producto matcheados, Concepto, montos). No usan el CSV de import Odoo (`POST /api/csv`), que sigue siendo el de modo Odoo.
- Con **`?pepe=1`**: la **grilla** muestra las 12 columnas Gastos (editables). **Mes** / **Sucursal** / **Mes de pago** listan valores únicos de la pestaña Config del Sheet. **Estado de Deuda** default **Pagado**. Copiar/Descargar CSV usa los valores de esa grilla.
- Si el Sheet no está compartido a la SA, `excel_padron.sheet_error` en la respuesta y mensaje en status.
- La UI admin (`padron_excel.html`) sigue para configurar fuentes; no reemplaza este deep link.

## Fuentes (prioridad)

1. **Google Sheets privado + service account** (recomendado): el cliente comparte el Sheet en Viewer a la cuenta de servicio; no hace falta “Publicar en la web”.
2. Google Sheets publicado (`pub?output=csv`) — compatibilidad con el setup anterior.
3. Upload `.csv` / `.xlsx` por tipo: proveedores, productos, formas de pago, conceptos (sin auto-refresh).

Config y archivos en `data/padrones/` (JSON + `files/`). El matching en UI principal (`?excel_user=1`) **reusa el Sheet en caché** según `refresh_minutes` (default 2) para evitar HTTP 429 de Google; si el export falla y hay caché previa, se usa stale. El iframe admin / `force_refresh=1` sí puede forzar re-lectura. El export CSV de Google reintenta con backoff ante 429.

### Compartir Sheet de forma segura

1. En GCP: crear service account + JSON key.
2. En el server: `GOOGLE_SERVICE_ACCOUNT_JSON` = path al JSON **o** el JSON crudo.
3. Pedirle al cliente: **Compartir → Viewer** al mail `…@….iam.gserviceaccount.com` (sin publicar).
4. Guardar en config el `spreadsheet_id` (de la URL `/d/<id>/edit`) y opcionalmente `sheet_gid`. Si pegan la URL `/edit`, el backend extrae id/gid.

SA ya creada en proyecto `fudo-481618` (mismo que [`deploy.sh`](../deploy.sh)):

- Email: `facturia-padron@fudo-481618.iam.gserviceaccount.com`
- Key local (gitignored): `secrets/facturia-padron-sa.json`
- Env: `GOOGLE_SERVICE_ACCOUNT_JSON` apunta a esa key

Sin `GOOGLE_SERVICE_ACCOUNT_JSON`, un Sheet solo compartido (no publicado) **no** se puede leer: el `GET` anónimo falla.

Si el link es válido pero **no** está compartido a la SA, la UI muestra un error claro (`sheet_error`): *«El Sheet existe pero no está compartido como Lector a …»* (antes parecía padrón vacío).

## Iframe FacturIA (UI admin Excel)

```
/static/padron_excel.html?embed=1&proceso=123&empresa=1&company_id=0
```

- Oculta panel de fuentes/admin.
- Llama `GET /api/padron-excel/proceso/{n}` (**siempre** baja el Sheet actual salvo `force_refresh=0`).
- Muestra listas del padrón + filas de la IA con fuzzy match (scores).
- Contrato análogo al iframe Odoo (`?embed=1&proceso=`): el cambio en FacturIA es apuntar el iframe a esta URL.

## Padrones y matching

| Tipo | Columnas | Matching |
|------|----------|----------|
| Proveedores | razón social, nombre fantasía, CUIT | CUIT dígitos exactos (100) → fuzzy razón/fantasía |
| Productos | nombre, unidad de medida | Fuzzy nombre; UoM del padrón + aliases (`kg`/`kilos`, `un`/`uds`) |
| Conceptos | nombre, categoría opcional | Fuzzy; categoría por lookup (o columnas 8–9 del sheet de referencia) |
| Forma de pago | nombre | Fuzzy |

Si solo hay una columna de nombre (sheet de referencia), se mapea a razón social / concepto y CUIT/UoM quedan vacíos.

## Endpoints

Ver [api.md](api.md#padrón-excel).

- **Listar hojas** (SA): `POST /api/padron-excel/sheets` con URL `/edit` compartida al SA.
- **Primera fila (headers)**: `POST /api/padron-excel/sheets/row` (`sheet_gid` / `sheet_title`). Alias: `/sheets/column`.
- **Entrega por template**: `GET /api/padron-excel/entrega?id_cliente=&proceso=&id_template=` — columnas de `export_templates` (MySQL, `PROCESS_SCHEMA`) con `is_dropdown` y match Excel. Ver [api.md](api.md#entrega-por-template).
- **Matching proceso FacturIA** (padrón al día): `GET /api/padron-excel/proceso/{n}` (`force_refresh` default true).
- **UI principal**: `GET /api/proceso/{n}?excel_user=1` (o `?pepe=1`) — ver sección arriba.

Lógica: `padron/excel.py`, `excel_user.py`, `pepe_schema.py` (layout Gastos Pepe), `template_entrega.py` (proyección `source_value` + `is_dropdown`), `sheet_loader.py`, `google_sheets.py`, `process_to_invoice.py`, `catalog_excel.py`, `persistence/export_template_store.py`, `api/route_padron_excel.py`, path Excel en `core/process.py`.

## Export Gastos Pepe (`?pepe=1`)

Columnas fijas (mismo orden que la planilla del cliente):

`Mes | Sucursal | Proveedor | Concepto | Fecha | Monto | Fecha de pago | Mes de pago | Forma de pago | Categoría gasto | Observación | Estado de Deuda`

- UI principal: grilla editable (`pepe/gastosUi.js`) + CSV (`buildPepeGastosCsv`). Estado de Deuda default `Pagado`. **Categoría gasto**: valores únicos de la hoja Gastos (`CMV`, `Gastos Fijos`, `Gastos Var`, `Financieros`, `Impuestos`, `Retiro Socios`, …).
- Admin: `GET /api/padron-excel/facturas/export/csv` → `pepe_gastos_values`.
- Matching sigue leyendo el padrón desde la pestaña Config (`Proveedores` / `Conceptos` / `Forma de Pago`).

## Concepto + Categoría con IA (memoria = hoja Gastos)

Generalizable a cualquier cliente Excel: **un** DeepSeek genérico + historial del Sheet (no fine-tune por tenant).

| Pieza | Detalle |
|-------|---------|
| Flag | `FACTURIA_CONCEPT_AI_ENABLED=1` + `DEEPSEEK_API_KEY` (mismo key que UM) |
| Modelo | `deepseek-flash` (opcional `FACTURIA_CONCEPT_AI_MODEL`) |
| Cuándo | Solo en `excel_user` / Pepe. **Un concepto por proveedor** (así clasifican en Gastos): el más frecuente en el historial. Si no hay filas de ese proveedor, una sola elección de IA para todo el comprobante |
| Memoria | Pestaña Gastos (`gastos_sheet_gid`, default Pepe `541219037`): concepto mayoritario del proveedor + top-K ejemplos |
| Listas | Conceptos de Config; categorías = únicos de «Categoría gasto» en Gastos (no solo Fijos/Var) |
| Categoría sin map Config | Si fuzzy acierta concepto pero no hay categoría → se **infiere** del historial Gastos (mismo concepto/proveedor) |
| Batch | 1 llamada JSON por comprobante; cache `(company_id, proveedor, descripción)` |
| Validación | Respuestas fuera de las listas se descartan |

Aprendizaje sin modelo custom: el operador corrige en la UI, pega el CSV en Gastos, y la **próxima** factura ya ve esos ejemplos.

Consumo orden de magnitud (flash): ~1 llamada / comprobante, ~1.5–3k tokens → **≪ USD 0.001**; rematch/F5 con cache = 0 llamadas extra.

Código: `padron/gastos_history.py`, `padron/concept_ai.py`, hook en `core/process.py`. Tests: `tests/test_concept_ai.py`.
