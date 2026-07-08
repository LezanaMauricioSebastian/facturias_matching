# Tests del paquete `import_`

Cómo probar el import Odoo tras el split en subpaquete.

Mapa general de tests: [tests-y-scripts.md](../tests-y-scripts.md).

---

## Comando rápido

```bash
cd facturia-matching-ui
PYTHONPATH=src python -m pytest \
  tests/test_odoo_import.py \
  tests/test_iva_tax_resolve.py \
  tests/test_comprobante_tax.py \
  tests/test_tax_pipeline.py \
  tests/test_padron_taxes_iibb.py \
  -q
```

Suite unitaria completa:

```bash
pip install -e .
python -m unittest discover -s tests -p 'test_*.py'
```

---

## Archivos de test principales

| Archivo | Foco respecto a `import_` |
|---------|---------------------------|
| `test_odoo_import.py` | Agrupación, validación, planes, batch write, OC, precio reapply, duplicados |
| `test_comprobante_tax.py` | `collect_expected_*`, `_tax_ids_for_odoo_line` con modos IVA |
| `test_iva_tax_resolve.py` | Resolución tax id Dinner vs Aliare |
| `test_tax_pipeline.py` | Pipeline fiscal → montos esperados |
| `test_padron_taxes_iibb.py` | IIBB en `collect_expected_*` |

Fixtures compartidos: `tests/fixtures/tax_scenarios.json`, `tests/tax_fixtures.py`.

---

## `mock.patch` — rutas por submódulo

Tras el split, los mocks deben apuntar al **submódulo donde se usa el nombre**, no solo a `facturia_matching.odoo.import_`.

| Comportamiento bajo test | Patch target |
|--------------------------|--------------|
| `_find_existing_move` RPC | `facturia_matching.odoo.import_.create.odoo_execute_kw_with_config` |
| `_move_line_supports_purchase_link` | `facturia_matching.odoo.import_._utils.odoo_execute_kw_with_config` |
| `plan_purchase_line_updates` sin purchase field | `facturia_matching.odoo.import_._utils.odoo_execute_kw_with_config` |
| `sanitize_group_purchase_lines` | `facturia_matching.odoo.import_.purchase.odoo_execute_kw_with_config` |
| `_batch_write_move_lines` | `facturia_matching.odoo.import_.move_lines.odoo_execute_kw_with_config` |
| `_prepare_rows_for_import` (refresh OC) | `facturia_matching.odoo.import_.purchase._refresh_purchase_links` |
| mismo + sanitize | `facturia_matching.odoo.import_.purchase.sanitize_group_purchase_lines` |
| mismo + purchase link | `facturia_matching.odoo.import_.purchase._move_line_supports_purchase_link` |

**Por qué:** `patch("facturia_matching.odoo.import_.odoo_execute_kw_with_config")` ya no funciona — `odoo_execute_kw_with_config` no está bound en `__init__.py`.

### Cache purchase

```python
from facturia_matching.odoo.import_ import _MOVE_LINE_PURCHASE_LINK_CACHE

def setUp(self):
    _MOVE_LINE_PURCHASE_LINK_CACHE.clear()
```

---

## Patrones de test útiles

### Agrupación sin Odoo

```python
from facturia_matching.odoo.import_ import group_rows_into_invoices

rows = [
    {"__comprobante_idx": 0, "l10n_latam_document_number": "00001-00000001"},
    {"__comprobante_idx": 0, "l10n_latam_document_number": ""},
]
groups = group_rows_into_invoices(rows)
assert len(groups) == 1 and len(groups[0]) == 2
```

### Montos esperados sin Odoo

```python
from facturia_matching.odoo.import_ import collect_expected_tax_amounts_from_group

amounts = collect_expected_tax_amounts_from_group(group)
# amounts == {63: 12600.0, 27: 500.0}  # ids según perfil mockeado
```

### Plan sin RPC

```python
updates, warnings = plan_line_tax_updates(product_lines, content_rows)
assert updates[0]["new_tax_ids"] == [63, 27]
```

---

## Tests de regresión documentados

| Caso | Test (ejemplo) | Doc |
|------|----------------|-----|
| Pie IVA es-AR en JSON | `test_explicit_fac_iva_montos_parses_ar_format_strings` | [iva-y-import-odoo.md](../iva-y-import-odoo.md) |
| IIBB en fila encabezado | `test_collect_expected_iibb_from_header_only_row` | [impuestos.md](impuestos.md) |
| Precio tras OC | `test_plan_product_price_quantity_reapply_po_price_differs` | [purchase-oc.md](purchase-oc.md) |
| Ref domain sin latam stored | `test_find_existing_move_uses_ref_domain_not_latam_field` | [pipeline.md](pipeline.md) |
| Reconcile preserva pie mixed | `test_reconcile_preserves_footer_iva_montos_in_mixed_mode` | [impuestos.md](impuestos.md) |

---

## Añadir tests para cambios en `import_`

1. **Preferir tests sin RPC** — `plan_*`, `collect_*`, `group_*`, `validate_*`.
2. **Un test por regresión** — nombre descriptivo + referencia en doc si es caso de usuario.
3. **Mockear en el submódulo correcto** — ver tabla arriba.
4. **Limpiar caches** — `_MOVE_LINE_PURCHASE_LINK_CACHE`, caches padrón si aplica.
5. **Perfil Odoo** — en tests de resolución IVA, patch `resolve_iva_tax_id_for_pct` o catálogo del perfil.

---

## Integración (Odoo real)

No hay suite dedicada solo a `import_` en `tests/integration/`. Los tests de import son unitarios con mocks.

Para probar contra Odoo TEST:

1. Configurar `.env` con credenciales
2. `GET /api/odoo/health/import`
3. `POST /api/odoo/import` con filas de un proceso de prueba en borrador

Scripts relacionados: ver `scripts/` en [tests-y-scripts.md](../tests-y-scripts.md).

---

## CI

Si el proyecto corre pytest en CI, el job debe incluir `PYTHONPATH=src` o `pip install -e .` para resolver `facturia_matching`.
