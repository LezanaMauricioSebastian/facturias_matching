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
| `test_fac_amounts.py` | `core/amounts.py` — parseo montos FacturIA, híbridos `350.0,00`, decimales US vs miles, `format_fac_amount_for_ui` |
| `test_comprobante_tax.py` | `core/comprobante_tax.py` — modos, totales, JSON es-AR en `__fac_iva_montos` |
| `test_tax_pipeline.py` | Pipeline fiscal end-to-end en Python |
| `test_iva_tax_resolve.py` | Resolución IVA → tax id; remapeo padrón Dinner → Aliare |
| `test_js_python_parity.py` | Mismos escenarios que JS en fixtures |
| `test_process_conversions.py` | Guardar/cargar conversiones; `infer_otro_impuesto_indices`; strip slots otros impuestos legacy |
| `test_saved_row_remap.py` | Remap de IDs al recargar conversión |
| `test_odoo_catalog.py` | Maps de catálogo, resolve por nombre |
| `test_odoo_cold_path.py` | Single-flight `get_catalog`, cache taxes por profile, uid auth cache, tope OCs en enrich |
| `test_odoo_api.py` | Helpers XML-RPC (mock) |
| `test_odoo_import_grouping.py` | Agrupación, validación, `build_move_vals`, NC → `in_refund`, due date. Ver [import-odoo/testing.md](import-odoo/testing.md). |
| `test_odoo_import_taxes.py` | tax_ids, IIBB, montos esperados, reapply tax amounts |
| `test_odoo_import_purchase.py` | Vínculo OC, reapply precio/cantidad, overwrite precio OC, batch write |
| `test_purchase_matching_uom.py` | Qty/UM, scaling, aliases, modelo Odoo 19 |
| `test_purchase_matching_oc.py` | Matching OC, búsqueda bajo demanda, enrich/select/rematch, Sin OC |
| `test_purchase_matching_match.py` | Scoring línea / fuzzy / Dinner / OCR / sugerencia producto |
| `test_purchase_matching_package.py` | Humo del paquete `odoo/purchase_matching/` (imports, caches, sin monolito) |
| `test_product_label_memory.py` | Aprendizaje producto + UM |
| `test_padron_taxes_iibb.py` | Impuestos padrón, IIBB, percepciones |
| `test_options_otros_impuestos.py` | Opciones otros impuestos desde Odoo (filtro + extras dinámicos purchase incl. IVA; alias Perc Gananc/IVA) |
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
# equivale a: node --test tests/js/*.test.mjs
```

| Archivo | Qué cubre |
|---------|-----------|
| `tests/js/comprobante_tax.test.mjs` | Paridad lógica tax en browser |
| `tests/js/solo_encabezado.test.mjs` | Flag Solo encabezado, tilde global (`applySoloEncabezadoToAll`), columnas, colapso |
| `tests/js/rows_migration.test.mjs` | Migración de filas (cuenta, proveedor) |
| `tests/js/numbers.test.mjs` | Parseo de montos |
| `tests/js/validateRows.test.mjs` | Validación pre-export (partner, journal, IVA por modo, cuenta, fechas) |
| `tests/js/loadFixtures.mjs` | Carga `tax_scenarios.json` (helper, no test) |
| `tests/js/exportTotals.mjs` | Script CLI para paridad Python/JS (`node tests/js/exportTotals.mjs`) |

Los módulos bajo test importan desde `src/facturia_matching/static/js/...` vía rutas relativas en los tests.

CI corre `npm run test:js` junto a los unit tests Python (ver `.github/workflows/test.yml`).

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
| Fórmula IVA | `tax_scenarios.json` + test JS (`comprobante_tax.test.mjs`, incl. `header footer IVA fixed when price changes`) + `test_comprobante_tax.py` + `test_js_python_parity.py` |
| Solo encabezado | `tests/js/solo_encabezado.test.mjs` (flag, tilde global aplica a todos, 1 línea sin pie, multi con pie, clasificación mixed sin bloqueo) |
| Nueva columna UI/CSV | `test` de `constants` o snapshot headers en export |
| Import Odoo | `test_odoo_import_*.py` con filas mínimas agrupadas |
| Matching OC | `test_purchase_matching_{uom,oc,match}.py` |
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
