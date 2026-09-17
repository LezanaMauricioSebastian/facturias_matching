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

- `GET /api/proceso/{n}?excel_user=1&empresa=…` regenera filas desde `json_data` con `load_padron(..., force=True)`. `empresa` se envía siempre que haya una activa (URL / proceso); si no viene, el backend usa la del proceso.
- `GET /api/padron-excel/data?empresa=&company_id=` también acepta `empresa` (default de `company_id` si este se omite).
- Match proveedor (CUIT / fuzzy), producto (+ UoM) y **concepto** si el Sheet trae conceptos (best-effort).
- Sin import Odoo, sin columnas/OC de purchase matching. También se ocultan Rubros, Diario y Cuenta (solo Odoo).
- Badge «Padrón Excel»; botones **Restaurar original** (descarta conversión y regenera desde FacturIA) y **Re-matchear** (vuelve a leer el Sheet).
- Los combobox **Proveedor** / **Producto** / **Concepto** listan el padrón del Sheet (no Odoo). FacturIA no trae concepto aparte: el match inicial es fuzzy sobre la descripción de línea; el desplegable sirve para corregir a mano.
- Si el Sheet no está compartido a la SA, `excel_padron.sheet_error` en la respuesta y mensaje en status.
- La UI admin (`padron_excel.html`) sigue para configurar fuentes; no reemplaza este deep link.

## Fuentes (prioridad)

1. **Google Sheets privado + service account** (recomendado): el cliente comparte el Sheet en Viewer a la cuenta de servicio; no hace falta “Publicar en la web”.
2. Google Sheets publicado (`pub?output=csv`) — compatibilidad con el setup anterior.
3. Upload `.csv` / `.xlsx` por tipo: proveedores, productos, formas de pago, conceptos (sin auto-refresh).

Config y archivos en `data/padrones/` (JSON + `files/`). El **matching** (iframe proceso, `/match`, guardar factura, carga de padrón, y `?excel_user=1` en UI principal) **relee el Sheet por defecto** (`force_refresh` / `force=true`); el TTL (`refresh_minutes`) solo aplica si pedís explícitamente no forzar.

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
- **Matching proceso FacturIA** (padrón al día): `GET /api/padron-excel/proceso/{n}` (`force_refresh` default true).
- **UI principal**: `GET /api/proceso/{n}?excel_user=1` (o `?pepe=1`) — ver sección arriba.

Lógica: `padron/excel.py`, `excel_user.py`, `sheet_loader.py`, `google_sheets.py`, `process_to_invoice.py`, `catalog_excel.py`, `api/route_padron_excel.py`, path Excel en `core/process.py`.
