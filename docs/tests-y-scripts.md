# Tests y scripts

## Tests Python

Ejecutar todo:

```bash
pip install -e .
python -m unittest discover -s tests -p 'test_*.py'
```

Integración (requieren credenciales reales):

```bash
python -m unittest discover -s tests/integration -p 'test_*.py'
```

Se omiten o fallan gracefully si no hay `.env` con BDs.

### Mapa de tests unitarios

| Archivo | Qué cubre |
|---------|-----------|
| `test_fac_amounts.py` | `core/amounts.py` — parseo montos FacturIA, híbridos `350.0,00` |
| `test_comprobante_tax.py` | `core/comprobante_tax.py` — modos, totales, JSON es-AR en `__fac_iva_montos` |
| `test_tax_pipeline.py` | Pipeline fiscal end-to-end en Python |
| `test_iva_tax_resolve.py` | Resolución IVA → tax id; remapeo padrón Dinner → Aliare |
| `test_js_python_parity.py` | Mismos escenarios que JS en fixtures |
| `test_process_conversions.py` | Guardar/cargar conversiones; `infer_otro_impuesto_indices`; strip slots otros impuestos legacy |
| `test_saved_row_remap.py` | Remap de IDs al recargar conversión |
| `test_odoo_catalog.py` | Maps de catálogo, resolve por nombre |
| `test_odoo_api.py` | Helpers XML-RPC (mock) |
| `test_odoo_import.py` | Agrupación, validación, planes de import, IIBB en primera línea, montos tax tras reconcile |
| `test_purchase_matching.py` | Matching OC, UM, fuzzy líneas |
| `test_padron_taxes_iibb.py` | Impuestos padrón, IIBB, percepciones |
| `test_options_otros_impuestos.py` | Opciones otros impuestos desde Odoo |
| `test_db_resolve.py` / `test_infra_db_resolve.py` | Resolución nombre DB Postgres/MySQL |
| `test_routes_odoo_cloud.py` | Rutas con perfil sudata / odoo_cloud |
| `test_rubro_profile.py` | Columnas rubro según perfil |

### Integración

| Archivo | Qué cubre |
|---------|-----------|
| `integration/test_padron_process.py` | Flujo padrón + proceso contra DB real |

### Fixtures compartidos

| Archivo | Uso |
|---------|-----|
| `tests/fixtures/tax_scenarios.json` | Casos IVA line/header/mixed |
| `tests/tax_fixtures.py` | Loader Python de fixtures |

---

## Tests JavaScript

```bash
npm run test:js
# equivale a: node --test tests/js/comprobante_tax.test.mjs
```

| Archivo | Qué cubre |
|---------|-----------|
| `tests/js/comprobante_tax.test.mjs` | Paridad lógica tax en browser |
| `tests/js/loadFixtures.mjs` | Carga `tax_scenarios.json` |
| `tests/js/exportTotals.mjs` | Helper para asserts de totales |

Los módulos bajo test importan desde `src/facturia_matching/static/js/...` vía rutas relativas en los tests.

---

## Scripts CLI (`scripts/`)

Requieren `pip install -e .` y `.env` configurado.

| Script | Propósito |
|--------|-----------|
| `compare_padron_views.py` | Diff entre `view_padron_facturia` y `view_padron_facturia_actualizado` |
| `consultar_odoo_catalog.py` | Inspeccionar catálogo Odoo (proveedores, cuentas, etc.) |
| `padron_proveedores_diff.py` | Comparar proveedores padrón vs Odoo |
| `build_padron_from_odoo.py` | Generar padrón desde facturas Odoo (sin vista PG) |
| `seed_aliare_proveedores.py` | Seed datos Aliare (entorno específico) |
| `seed_aliare_rubros.py` | Seed rubros Aliare |

Uso típico de diagnóstico cuando el matching falla en un proveedor o rubro.

---

## Qué test agregar según el cambio

| Cambiaste… | Agregar/actualizar |
|------------|-------------------|
| Fórmula IVA | `tax_scenarios.json` + test JS + `test_comprobante_tax.py` + `test_js_python_parity.py` |
| Nueva columna UI/CSV | `test` de `constants` o snapshot headers en export |
| Import Odoo | `test_odoo_import.py` con filas mínimas agrupadas |
| Matching OC | `test_purchase_matching.py` |
| Nueva ruta API | `test_routes_odoo_cloud.py` o test dedicado con `TestClient` |
| Remap conversión | `test_saved_row_remap.py` |

---

## CI local rápido antes de commit

```bash
pip install -e .
python -m unittest discover -s tests -p 'test_*.py'
npm run test:js
```

Si solo tocaste Python y no tax JS, el segundo paso es opcional pero recomendado si tocaste `comprobante_tax.py`.
