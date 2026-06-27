# FacturIA → Odoo (matching UI)

Pantalla web para cargar un proceso de FacturIA, revisar el matching contra el padrón y Odoo, editar filas y exportar CSV para importación en Odoo. También permite importar borradores a Odoo TEST.

## Qué hace

1. Ingresás el número de proceso (MySQL `sudataco_facturia.process`).
2. Lee el JSON del proceso, matchea proveedor/rubro/diario/cuenta contra PostgreSQL y catálogos Odoo.
3. Mostrás una tabla editable.
4. Descargás CSV o importás a Odoo TEST.

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
uvicorn facturia_matching.main:app --reload --port 8080
```

Abrí http://localhost:8080

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
```
