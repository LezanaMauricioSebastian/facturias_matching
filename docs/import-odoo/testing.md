# Tests del paquete `import_`

Cómo probar el import Odoo tras el split en subpaquete.

Mapa general de tests: [tests-y-scripts.md](../tests-y-scripts.md).

---

## Comando rápido

```bash
cd facturia-matching-ui
PYTHONPATH=src python -m pytest \
  tests/test_odoo_import_*.py \
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
| `test_odoo_import_grouping.py` | Agrupación, validación, `build_move_vals`, NC → `in_refund`, due date / maturity |
| `test_odoo_import_taxes.py` | `tax_ids`, montos esperados, IIBB, reapply de tax amounts, `ensure_missing_tax_lines` |
| `test_odoo_import_purchase.py` | Vínculo OC, sanitize/dedupe, planes product/purchase, reapply precio/cantidad, overwrite precio OC, batch write |
| `test_purchase_matching_uom.py` | Qty/UM, scaling, aliases, `TestUomOdoo19Model` |
| `test_purchase_matching_oc.py` | Candidatos OC bajo demanda (**todas** las OC del partner), enrich/select/rematch, Sin OC, score soft |
| `test_purchase_matching_match.py` | Scoring de línea / fuzzy / Dinner notes / OCR / sugerencia producto |
| `test_purchase_matching_package.py` | Humo del paquete `odoo/purchase_matching/` (imports, `__all__`, `clear_purchase_cache`, sin monolito `.py`) |
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
| `apply_purchase_order_price_overwrites` | `facturia_matching.odoo.import_.purchase.odoo_execute_kw_with_config` |
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

## `purchase_matching` (paquete)

Arquitectura: [purchase-matching.md](purchase-matching.md).

Tras el split de `purchase_matching.py` → `purchase_matching/`, los tests históricos siguen parchando el **root** del paquete:

```python
@patch("facturia_matching.odoo.purchase_matching.is_purchase_odoo_configured", return_value=True)
@patch("facturia_matching.odoo.purchase_matching.fetch_partner_po_lines")
@patch("facturia_matching.odoo.purchase_matching.get_uom_catalog")
```

Funciona porque enrich / fetch / UM resuelven esos nombres vía `_pkg()` en runtime. También:

```python
from facturia_matching.odoo import purchase_matching as pm
with patch.object(pm, "odoo_search_read", ...):
    pm._fetch_uom_catalog()
```

Humo de estructura (sin tocar reglas):

```bash
PYTHONPATH=src python3 -m unittest tests.test_purchase_matching_package -q
```

Suite matching + memoria:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_purchase_matching_uom \
  tests.test_purchase_matching_oc \
  tests.test_purchase_matching_match \
  tests.test_product_label_memory \
  tests.test_purchase_matching_package \
  -q
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
| Base no salta al poner IVA (header→mixed) | `test_mixed_mode_keeps_fac_subtotal_as_base_odoo`, `keeps fac subtotal as Base when selecting IVA flips header→mixed` | [iva-y-import-odoo.md](../iva-y-import-odoo.md) |
| IIBB en fila encabezado | `test_collect_expected_iibb_from_header_only_row` | [impuestos.md](impuestos.md) |
| Perc IVA/Interno en otras líneas, Dinner (slots 1ª fila sin label) | `test_collect_expected_otros_unlabeled_slots_map_to_line_labels` | [impuestos.md](impuestos.md) |
| Interno en 1ª fila no oculta IIBB (Dinner) | `keeps IIBB in pie when first row selects Impuesto Interno`, `test_collect_expected_interno_on_iibb_slot_does_not_steal_iibb_amount` | [iva-y-import-odoo.md](../iva-y-import-odoo.md) |
| Precio tras OC | `test_plan_product_price_quantity_reapply_po_price_differs` | [purchase-oc.md](purchase-oc.md) |
| UM tras match | `test_build_line_command_includes_matched_product_uom`, `test_plan_product_price_quantity_reapply_restores_uom`, `test_apply_uom_scaling_kg_collision_uses_target_category`, `test_apply_uom_scaling_oc_custom_pack_from_kg_invoice`, `test_match_invoice_row_oc_uses_product_purchase_uom_not_po_line` | [purchase-oc.md](purchase-oc.md#unidad-de-medida-um) |
| UM elegida a mano | `test_list_uoms_for_product_same_category`, `test_apply_product_uom_to_row_explicit_uom_id_rescales`, `test_apply_product_uom_to_row_rejects_out_of_category_uom`, `test_enrich_preserves_saved_manual_uom_on_reload`, `test_match_invoice_row_keeps_confirmed_product_and_saved_uom` | [purchase-oc.md](purchase-oc.md#unidad-de-medida-um) |
| Remap no pisa diario/rubro/cuenta válidos | `test_keeps_valid_journal_rubro_account_despite_padron` | [arquitectura.md](../arquitectura.md) |
| Reapply precio UI ≠ PO (packs) | `test_plan_product_price_quantity_reapply_salta_pack_lines_ui_vs_po`, `test_plan_product_price_quantity_reapply_shared_oc_line_falls_back_to_index` | [iva-y-import-odoo.md](../iva-y-import-odoo.md) |
| Sugerencia fuzzy sin rescale / sin falso positivo | `test_suggest_product_does_not_rescale_pack_qty_as_kg`, `test_line_match_score_rejects_tomate_seco_vs_triturado` | [purchase-oc.md](purchase-oc.md#sugerencia-de-producto-por-fuzzy-sin-vincular-oc) |
| Ranking OC por `partner_ref` / PEDIDO | `test_score_oc_candidates_boosts_matching_partner_ref`, `test_ref_match_score_exact_and_date_proximity` | [purchase-oc.md](purchase-oc.md#filtro-de-ocs-en-matching) |
| Ranking OC por % de matching (`basket_score`) | `test_score_oc_candidates_ranks_higher_basket_score_first` | [purchase-oc.md](purchase-oc.md#filtro-de-ocs-en-matching) |
| Aprendizaje producto + UM (`product_label_memory`) | `test_product_label_memory_*` (incl. pack 6 vs 8), `test_match_invoice_row_prefers_learned_over_fuzzy`, `test_match_invoice_row_learned_beats_oc`, `test_match_invoice_row_learned_links_oc_by_product_despite_label`, `test_match_invoice_row_learned_applies_uom`, `test_upsert_*`, `test_apply_oc_selection_uses_product_memory` | [purchase-oc.md](purchase-oc.md#aprendizaje-de-producto-procesos-pasados) |
| Colisión OC conserva producto | `test_oc_collision_keeps_product_id`, `test_plan_product_line_content_updates_writes_product_even_with_oc` | [purchase-oc.md](purchase-oc.md#aprendizaje-de-producto-procesos-pasados) |
| Score soft mismo producto / qty pedida (P06790) | `test_score_oc_candidates_soft_*` | [purchase-oc.md](purchase-oc.md#aprendizaje-de-producto-procesos-pasados) |
| Soft no infla Zero / C-G sobre la línea hermana | `test_score_oc_candidates_soft_skips_zero_and_gas_variants` | [purchase-oc.md](purchase-oc.md#aprendizaje-de-producto-procesos-pasados) |
| Fanta ≠ agua naranja; sin gas ≠ con gas (notas Dinner) | `test_score_oc_candidates_fanta_not_saborizada_and_gas_notes` | [purchase-oc.md](purchase-oc.md#notas-dinner-bajo-líneas-código-producto) |
| UM kg preferida vs pack (Gran Crianza) | `test_resolve_target_uom_prefers_invoice_kg` | [purchase-oc.md](purchase-oc.md#unidad-de-medida-um) |
| Diario/cuenta/rubro por partner | `test_partner_header_memory_*` | [guia-usuario.md](../guia-usuario.md) |
| Ref domain sin latam stored | `test_find_existing_move_uses_ref_domain_not_latam_field` | [pipeline.md](pipeline.md) |
| Reconcile preserva pie mixed | `test_reconcile_preserves_footer_iva_montos_in_mixed_mode` | [impuestos.md](impuestos.md) |
| IVA 21 → 10,5 en Sudata (catálogo EN) | `test_sudata_english_names_21_maps_to_65_not_63`, `test_sudata_english_zero_rate_labels`, `test_no_dinner_fallback_when_profile_is_not_default`, `test_sudata_english_percepcion_labels_resolve`, `test_saved_english_labels_resolve_against_spanish_catalog` | [iva-y-import-odoo.md](../iva-y-import-odoo.md#iva-21--llega-como-iva-105--en-sudata-nombres-en) |
| Idioma RPC por tenant (es_AR → es_419) | `test_sudata_falls_back_to_es_419`, `test_prefers_es_ar_over_es_419_when_both_installed`, `test_unreachable_tenant_keeps_previous_defaults`, `test_lang_probe_runs_once_per_tenant` en `tests/test_odoo_api.py` | [iva-y-import-odoo.md](../iva-y-import-odoo.md#idioma-del-catálogo-resolve_odoo_lang) |
| Alias UM con catálogo traducido | `test_um_aliases_resolve_with_spanish_uom_catalog`, `test_um_aliases_still_resolve_with_english_uom_catalog` | [purchase-oc.md](purchase-oc.md#unidad-de-medida-um) |
| UM en Odoo 19 (árbol `relative_uom_id`) | clase `TestUomOdoo19Model` en `tests/test_purchase_matching_uom.py`: `test_tree_root_becomes_category`, `test_archived_parents_close_the_tree`, `test_convert_qty_weight`, `test_convert_qty_units_and_packs`, `test_product_default_uom_without_uom_po_id`, `test_unknown_fields_keep_legacy_model` | [purchase-oc.md](purchase-oc.md#um-en-odoo-19-sudata) |
| Campos inexistentes vacían el catálogo | clase `TestModelFieldsByVersion` en `tests/test_odoo_catalog.py` | [purchase-oc.md](purchase-oc.md#soporte-por-tenant) |
| Cambiar alícuota en la línea re-etiqueta el pie | `test_switching_line_rate_relabels_footer_iva`, `test_switching_line_rate_persists_relabeled_footer`, `test_footer_rate_not_covered_by_lines_is_kept`, `test_switching_line_rate_sends_new_iva_tax_id`, `cambio de alícuota en la línea (Sudata 13/8/2026)` en `tests/js/comprobante_tax.test.mjs` | [iva-y-import-odoo.md](../iva-y-import-odoo.md#cambiar-la-alícuota-en-la-línea-deja-la-vieja-en-el-pie-testing-elías-1382026) |
| Monto IVA sobrevive F5 (no migración legacy) | `migrateLegacyComprobanteIva keeps modern line Monto IVA (PDF Salta reload)` en `tests/js/comprobante_tax.test.mjs` | [iva-y-import-odoo.md](../iva-y-import-odoo.md) |
| Otros del pie repartidos por fila asignada | `distributes footer amount proportional…` / `puts full amount on the only row…` en `tests/js/comprobante_tax.test.mjs` | [iva-y-import-odoo.md](../iva-y-import-odoo.md) |
| Montos otros impuestos en multi-línea | `hides otros impuestos monto columns in multi-line` en `tests/js/solo_encabezado.test.mjs` | [guia-usuario.md](../guia-usuario.md) |
| 1 línea sin pie / multi con pie; proceso sin mezcla | `renderFooterHtml` + `proceso line mode by row count` en `solo_encabezado.test.mjs`; `rejects mixed 1-line…` en `validateRows.test.mjs`; `test_validate_rejects_mixed_one_line_and_multi_line` | [guia-usuario.md](../guia-usuario.md#solo-encabezado--1-línea) |

---

## Checklist manual Dinner (TESTING_Casos / Elías)

1. **Salta Refresco:** OC con `partner_ref` PEDIDO visible/rankeada; Zero/Agua match; diario aprendido; precio manual; impuestos + montos otros por fila; import con todas las líneas y taxes.
2. **Gran Crianza:** con OC, productos aprendidos + kg en filas de peso; sin líneas vacías en Odoo.
3. **Runea / base imponible:** elegir IVA 21 no cambia Base (`__fac_subtotal`); pie IVA/otros llegan a Odoo.
4. **F5:** Rubros/Diario/Cuenta/Monto IVA/UM persisten tras autosave.

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

GitHub Actions (`.github/workflows/test.yml`) corre:

- `pip install -e . && python -m unittest discover -s tests -p 'test_*.py'`
- `npm run test:js`

---

## Frontend (JS)

Los tests JS viven en `tests/js/` y se documentan en [tests-y-scripts.md](../tests-y-scripts.md).

| Área | Cobertura actual | Huecos |
|------|------------------|--------|
| Impuestos / pie | `comprobante_tax.test.mjs` + fixtures compartidos | — |
| Solo encabezado | `solo_encabezado.test.mjs` | — |
| Validación pre-export | `validateRows.test.mjs` | combobox / OC picker UI |
| Autosave / API client | — | sin tests automatizados |

Cambios en `static/js/validation/` o `comprobanteTax/` deben actualizar fixtures o tests JS correspondientes.
