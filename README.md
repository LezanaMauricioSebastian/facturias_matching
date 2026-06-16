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
uvicorn app:app --reload --port 8080
```

Abrí http://localhost:8080

## Tests

```bash
python -m unittest discover -s . -p 'test_*.py'
```

## Deploy (Cloud Run)

```bash
chmod +x deploy.sh
PROJECT_ID=tu-proyecto ./deploy.sh
```

Las variables de entorno y secretos de BD/Odoo se configuran en Cloud Run después del deploy.

## Scripts de diagnóstico

- `compare_padron_views.py` — compara columnas y métricas entre vistas del padrón
- `consultar_odoo_catalog.py` — prueba conexión y catálogo Odoo
- `padron_proveedores_diff.py` — proveedores en vista vieja que no están en la nueva
