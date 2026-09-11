# Padrón Excel / Sheets (clientes sin Odoo)

UI: `/static/padron_excel.html`. API: `/api/padron-excel/*`.

Matching de proveedores/productos/conceptos/forma de pago contra un padrón del cliente (sin Odoo). Desde FacturIA se puede abrir en **iframe** con el JSON del proceso (foto → IA) ya matcheado.

## Fuentes (prioridad)

1. **Google Sheets privado + service account** (recomendado): el cliente comparte el Sheet en Viewer a la cuenta de servicio; no hace falta “Publicar en la web”.
2. Google Sheets publicado (`pub?output=csv`) — compatibilidad con el setup anterior.
3. Upload `.csv` / `.xlsx` por tipo: proveedores, productos, formas de pago, conceptos (sin auto-refresh).

Config y archivos en `data/padrones/` (JSON + `files/`). Refresh en memoria con TTL (`refresh_minutes`, default 15 en docs / 2 en default de código).

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

## Iframe FacturIA

```
/static/padron_excel.html?embed=1&proceso=123&empresa=1&company_id=0
```

- Oculta panel de fuentes/admin.
- Llama `GET /api/padron-excel/proceso/{n}` (force refresh del padrón).
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

Lógica: `padron/excel.py`, `sheet_loader.py`, `google_sheets.py`, `process_to_invoice.py`, `catalog_excel.py`, `api/route_padron_excel.py`.
