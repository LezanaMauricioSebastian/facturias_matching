# FacturIA → Odoo (matching UI)

> ⚡ **Actualización 2026-07-20**: Se aplicaron correcciones críticas de rendimiento y estabilidad. Ver [EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md) para detalles.
> - **-40% latencia** en imports (25s → 15s para 10 facturas)
> - **Thread-safe** para multi-worker en producción
> - **6 bugs críticos** corregidos

Pantalla web para cargar un proceso de FacturIA, revisar el matching contra el padrón y Odoo, editar filas y exportar CSV para importación en Odoo. También permite importar borradores a Odoo (Dinner TEST, Aliare, Sudata según perfil).

**Perfil Odoo:** agregar `?odoo_profile_test=aliare` (o `sudata` / `odoo_cloud=1`) a la URL cuando el tenant no es Dinner. Guía operativa: [docs/guia-usuario.md](docs/guia-usuario.md). Detalle técnico: [docs/iva-y-import-odoo.md](docs/iva-y-import-odoo.md).

## Qué hace

1. Ingresás el número de proceso (MySQL `sudataco_facturia.process`).
2. Lee el JSON del proceso, matchea proveedor/rubro/diario/cuenta contra PostgreSQL y catálogos Odoo.
3. Mostrás una tabla editable por factura, con búsqueda dinámica de OCs del proveedor.
4. Podés vincular una OC, elegir Sin OC y opcionalmente marcar **Sobreescribir precio de la OC** (el precio UI también se escribe en la orden original).
5. Descargás CSV o importás a Odoo TEST.

## Requisitos

- Python 3.11+
- PostgreSQL con vistas `view_padron_facturia` y `view_padron_facturia_actualizado`
- MySQL con tabla `sudataco_facturia.process` (columnas `process_number`, `json_data`)
- Tenant Odoo con campos custom (`x_rubros`, tipos latam, etc.)

## Configuración

```bash
cp .env.example .env
# Completar credenciales en .env
```

## Correr local

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .
python main.py
```

Abrí http://localhost:8080

Variables opcionales: `PORT` (default 8080), `HOST` (default 127.0.0.1), `RELOAD=0` para desactivar autoreload.

Alternativa equivalente:

```bash
uvicorn facturia_matching.main:app --reload --port 8080
```

## Tests

```bash
pip install -e .
python -m unittest discover -s tests -p 'test_*.py'
```

Los tests de integración (requieren BD) están en `tests/integration/` y se omiten si no hay credenciales.

## Deploy (Cloud Run)

```bash
chmod +x deploy.sh
PROJECT_ID=tu-proyecto ./deploy.sh
```

Las variables de entorno y secretos de BD/Odoo se configuran en Cloud Run después del deploy.

## Scripts de diagnóstico

```bash
pip install -e .
python scripts/compare_padron_views.py
python scripts/consultar_odoo_catalog.py
python scripts/padron_proveedores_diff.py
python scripts/build_padron_from_odoo.py   # padrón desde facturas Odoo (sin vista Postgres)
```

## Estructura del proyecto

```
src/facturia_matching/   # paquete Python (API, matching, Odoo)
tests/                   # tests unitarios e integración
scripts/                 # utilidades de diagnóstico
docs/                    # documentación técnica
```

## Documentación

Índice general: **[docs/README.md](docs/README.md)** — arquitectura, módulos Python/JS, API, tests y guías por tarea.

- **[Guía de usuario](docs/guia-usuario.md)** — URL, perfil Odoo, selector OC por factura, sobreescritura opcional de precio, pie IVA, import y problemas frecuentes
- **[OC y purchase matching](docs/import-odoo/purchase-oc.md)** — botón dinámico, Sin OC, checkbox de precio, matching y pipeline
- [Arquitectura y flujo de datos](docs/arquitectura.md)
- [Módulos Python](docs/modulos-python.md)
- [Módulos frontend](docs/modulos-frontend.md)
- [API REST](docs/api.md)
- [Tests y scripts](docs/tests-y-scripts.md)
- [IVA por comprobante e import a Odoo](docs/iva-y-import-odoo.md) — modos line/header/mixed, pipeline de import y errores frecuentes
