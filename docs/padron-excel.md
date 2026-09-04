# Padrón Excel / Sheets (clientes sin Odoo)

UI: `/static/padron_excel.html`. API: `/api/padron-excel/*`.

No está enganchado al flujo `process_number` / import Odoo. Equivale al matching de proveedores/productos contra un padrón del cliente.

## Fuentes

- Google Sheets publicado (`pub?output=csv`).
- Upload `.csv` / `.xlsx` por tipo: proveedores, productos, formas de pago, conceptos.
- Config y archivos en `data/padrones/` (JSON + `files/`). Refresh en memoria con TTL (`refresh_minutes`, default 15).

## Padrones y matching

| Tipo | Columnas | Matching |
|------|----------|----------|
| Proveedores | razón social, nombre fantasía, CUIT | CUIT dígitos exactos (100) → fuzzy razón/fantasía |
| Productos | nombre, unidad de medida | Fuzzy nombre; UoM del padrón + aliases (`kg`/`kilos`, `un`/`uds`) |
| Conceptos | nombre, categoría opcional | Fuzzy; categoría por lookup (o columnas 8–9 del sheet de referencia) |
| Forma de pago | nombre | Fuzzy |

Si solo hay una columna de nombre (sheet de referencia), se mapea a razón social / concepto y CUIT/UoM quedan vacíos.

## Endpoints

Ver [api.md](api.md#padrón-excel). Lógica: `padron/excel.py`, `sheet_loader.py`, `catalog_excel.py`, `api/route_padron_excel.py`.
