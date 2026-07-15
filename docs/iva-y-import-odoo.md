# IVA por comprobante e import a Odoo

Guía de comportamiento de la UI, el cálculo de totales y el pipeline de importación a Odoo (`import_rows_to_odoo` / `sync_move_taxes_from_group`).

**Implementación Odoo (módulos, pipeline, API, tests):** [import-odoo/](import-odoo/README.md).

## Perfil Odoo (`odoo_profile`)

Los **ids numéricos** de `account.tax` dependen del tenant (Dinner, Aliare, Sudata). La misma alícuota puede ser id distinto en cada Odoo:

| Alícuota | Dinner (ej.) | Aliare (ej.) |
|----------|--------------|--------------|
| 21 %     | 63           | 65           |
| 10,5 %   | 61           | 63           |
| 27 %     | 65           | 67           |

**Siempre** pasar `?odoo_profile=aliare` (o `perfil=aliare`) en la URL y en el import cuando se trabaja contra Aliare. Sin perfil, la UI resuelve impuestos contra Dinner y los ids no coinciden con Odoo Aliare.

La resolución dinámica vive en `padron/taxes.py` (`resolve_iva_tax_id_for_pct`, `resolve_tax_label_to_id`, catálogo Odoo del perfil activo). El padrón Postgres guarda ids del tenant fuente; ver `PADRON_TAX_SOURCE_PROFILE` más abajo.

## Modos de IVA

Cada comprobante (grupo de filas con el mismo `__comprobante_idx` o número de documento) se clasifica en uno de tres modos:

| Modo | Cuándo | IVA editable en la tabla | IVA editable en el pie |
|------|--------|--------------------------|-------------------------|
| **`line`** | Todas las líneas tienen `iva_pct` y los montos por fila cierran con el encabezado FacturIA, o hay `iva_monto` editado en la fila | Sí (columna **IVA monto**) | No (solo lectura, resumen) |
| **`header`** | El IVA viene del encabezado (`__fac_iva_monto` / `__fac_iva_montos`) y no hay tasas por línea, o una sola línea cuyo % no cierra y el IVA no fue editado manualmente | No (columna oculta o sin uso) | Sí (pie del comprobante) |
| **`mixed`** | Hay líneas con y sin `iva_pct`, o varias alícuotas con totales que no cierran de forma uniforme | Depende de la fila | Sí (pie por alícuota y/o total) |

La clasificación vive en:

- **JS:** `classifyComprobanteTaxMode` (`static/js/comprobanteTax/totals.js`)
- **Python:** `classify_comprobante_tax_mode` (`core/comprobante_tax.py`)

Deben mantenerse alineados (tests en `tests/fixtures/tax_scenarios.json`, `tests/js/comprobante_tax.test.mjs`, `tests/test_js_python_parity.py`).

## Campos relevantes

| Campo | Origen | Uso |
|-------|--------|-----|
| `iva_pct` | FacturIA / padrón | Tasa de la línea (21, 10,5, …) |
| `iva_monto` | FacturIA o edición UI | Monto IVA de la línea; en modo `line` es autoritativo |
| `__iva_monto_manual` | Solo JS (blur de columna) | Marca edición manual; puede no llegar al servidor en autosave |
| `__fac_iva_monto` | FacturIA / pie UI | Total IVA del comprobante en encabezado |
| `__fac_iva_montos` | FacturIA / pie UI / sync | JSON `{"21": "57255,38", …}` por alícuota (puede usar formato es-AR) |
| `__fac_subtotal` | FacturIA | Subtotal del comprobante |
| `otros_impuestos` / `otros_impuestos_monto` | FacturIA / pie | Percepciones, IIBB, etc. (slots `_2`, `_3`, …) |

En **modo `line`**, los totales y el import usan `iva_monto` de cada fila.

En **modo `header` / `mixed`**, el **pie** (`__fac_iva_monto` / `__fac_iva_montos`) es la fuente de verdad al importar. Si el total editado (`__fac_iva_monto`) no coincide con la suma del JSON de desglose, se prioriza el total del pie cuando hay una sola alícuota (`fac_iva_montos` en `core/comprobante_tax.py`).

### Formato es-AR en `__fac_iva_montos`

El pie guarda montos como strings en JSON, a menudo con formato argentino (`"53.515,40"`, `"17.099,36"`). El import **debe** parsearlos con `parse_amount_loose` (`_explicit_fac_iva_montos` en `core/comprobante_tax.py`).

**Regresión corregida:** si el parser usaba `float()` directo sobre esos strings, el JSON entero fallaba en silencio → `fac_iva_montos` caía al cálculo por línea → Odoo mostraba IVA calculado aunque el pie tuviera otros valores. Test: `test_explicit_fac_iva_montos_parses_ar_format_strings`.

## Edición en la UI

- **Modo `line`:** editar **IVA monto** arriba → el pie se actualiza en vivo (readonly).
- **Modo `header` / `mixed`:** editar IVA en el **pie** del comprobante (`comprobanteView/footer.js` → `serializeFacIvaMontos`).
- Al cambiar cantidad, precio o IVA en modo `line`, JS llama `syncFacIvaMontosFromLines` para alinear `__fac_iva_montos` antes de autosave.
- Editar el campo **IVA** total (`rateKey === "_total"`) actualiza también el desglose cuando hay una sola alícuota (o asume 21 % si no hay desglose).

### IVA fijo al cambiar precio o cantidad

Si el **Monto IVA** de la línea ya está fijado (editado manualmente o viene de FacturIA y **no coincide** con `precio × cantidad × %`), cambiar **Precio** o **Cantidad** **no debe recalcular** el IVA del pie.

| Situación | Comportamiento esperado |
|-----------|-------------------------|
| Modo `line`, `iva_monto` fijo (manual o distinto del sugerido) | El pie mantiene ese monto (readonly); no se pisa con `precio × %` |
| Modo `header`, una sola alícuota, `__fac_iva_monto` sin JSON por tasa | El pie usa `__fac_iva_monto`, no el cálculo por línea |
| Modo `line`, `iva_monto` coincide con el sugerido | Al cambiar precio/cantidad, el IVA de línea y pie se recalculan juntos |

**Regresión corregida:** al editar **Precio**, JS sobrescribía `iva_monto` con el valor sugerido aunque FacturIA hubiera traído otro monto; el modo pasaba a `header` y el pie mostraba `precio × 21 %` en lugar del IVA fijo. Implementación:

- **JS:** `rows/totals.js` → `computeRowTotal` conserva `iva_monto` explícito cuando difiere del sugerido.
- **JS:** `comprobanteTax/ivaBreakdown.js` → `computeIvaBreakdown` en `header`/`mixed` usa `__fac_iva_monto` si hay una sola alícuota y no hay monto por tasa en `__fac_iva_montos` (paridad con `fac_iva_montos` en Python).
- **JS:** `table/render.js` re-renderiza la tabla si el modo tax cruza el límite `line` ↔ `header`/`mixed` al editar (evita columna IVA obsoleta).

Tests: `header footer IVA fixed when price changes` en `tests/js/comprobante_tax.test.mjs`.

## Import a Odoo (resumen del pipeline)

```
filas UI
  → _prepare_rows_for_import
       · refresh OC
       · reconcile_fac_iva_for_import   # ver reglas abajo
  → por comprobante:
       · crear account.move (borrador) o buscar duplicado por partner + ref
       · sync_move_taxes_from_group
            1. invoice_date / invoice_date_due en encabezado
            2. date_maturity en apuntes AP/AR que falten
            3. contenido de líneas de producto
            4. tax_ids en líneas de producto (ver reglas abajo)
            5. vínculos OC (purchase_line_id + product_id)
            6. re-aplicar price_unit / quantity en todas las líneas de producto
            7. _ensure_missing_tax_lines_on_move   # crea líneas tax faltantes (IVA + IIBB)
            8. montos en líneas display_type=tax   ← último paso (pisa recálculo Odoo)
```

### `reconcile_fac_iva_for_import`

Antes de importar, alinea metadata de IVA **sin pisar el pie** cuando el usuario editó abajo:

| Situación | Comportamiento |
|-----------|----------------|
| Modo `header` / `mixed` con `__fac_iva_montos` o `__fac_iva_monto` en el pie | **No recalcula** desde líneas; el pie manda al import |
| `iva_monto` editado en fila (`__iva_monto_manual`) | Regenera `__fac_iva_montos` desde las líneas |
| Modo `line` sin edición manual en pie | Sincroniza el JSON desde `iva_monto` de cada fila |
| Encabezado desincronizado (línea editada, JSON viejo) en modo `line` | Corrige `__fac_iva_montos` desde las líneas |

Sin esta distinción, un comprobante `mixed`/`header` con IVA editado en el pie podía perder los montos antes del import: el servidor reemplazaba el JSON por el cálculo por línea y **no había nada que sobreescribir en Odoo**.

### Regla de `tax_ids` en líneas de producto

- **`header`:** ninguna línea lleva IVA numérico en `tax_ids` (el total IVA va en el pie). **Excepción:** `IVA Exento` e `IVA No Gravado` sí van en la línea de producto (monto 0 en Odoo).
- **`line` / `mixed`:** IVA en la línea si esa fila tiene `iva_pct > 0` o `IVA Exento` / `IVA No Gravado`.
- **`0` / `IVA No Corresponde`:** sin tax IVA en la línea (comportamiento anterior).
- **IIBB / percepciones a nivel comprobante:** se consolidan en la **primera línea con contenido** (`_comprobante_non_iva_tax_ids`, `_merge_comprobante_non_iva_tax_ids` en `odoo/import_/taxes.py`), aunque `otros_impuestos` esté en una fila solo encabezado (`__solo_encabezado`).

La distinción vive en `iva_pct_requires_line_tax` (`padron/taxes.py`).

### Pie de comprobante (UI)

- **IVA:** con un solo producto y `IVA Exento` o `IVA No Gravado`, no se muestran filas de IVA en el pie.
- **Otros impuestos:** la fila del pie está oculta hasta que se selecciona un impuesto en alguna línea (o hay monto > 0). Al seleccionar, aparece con valor inicial `0`.

Si el modo se clasifica mal como `header` cuando el usuario editó `iva_monto` en la tabla, Odoo **quita el IVA** de la línea y el import no tiene dónde escribir el monto → el IVA “desaparece”.

### Montos de impuesto esperados

`collect_expected_tax_amounts_from_group` → `_apply_tax_line_amount_overwrites`:

- **`line`:** suma `line_iva_monto(row)` por fila, indexado por `account.tax` id del perfil activo.
- **`header` / `mixed`:** usa `fac_iva_montos(group)` y mapea cada alícuota con `_iva_tax_id_for_rate` + `_iva_tax_resolve_row` (primera línea con `iva_pct` o fila con metadata del pie).
- **IIBB / otros:** suma todos los slots `otros_impuestos_N` / `otros_impuestos_N_monto` de **cualquier fila** del comprobante; remapeo de ids padrón vía `build_csv_additional_taxes` (`padron/taxes.py`).

Si falta una línea `display_type=tax` en Odoo para un impuesto esperado, `_ensure_missing_tax_lines_on_move` refuerza `tax_ids` en la primera línea de producto (incluye IVA faltante en header) y luego se pisan los montos.

Odoo puede recalcular impuestos al actualizar `tax_ids`, al vincular `purchase_line_id` o al re-aplicar precio. Por eso la sobreescritura de montos ocurre **al final** de `sync_move_taxes_from_group`, **después** del reapply de precio/cantidad.

### Precio de línea con Orden de Compra

Cuando una fila tiene match de OC (`__oc_line_id`), el import:

1. Escribe primero `price_unit` y `quantity` desde la UI / FacturIA (`invoice_line_ids/price_unit`, `invoice_line_ids/quantity`) en el paso de contenido de líneas.
2. Vincula `purchase_line_id` + `product_id` en un write separado (`_po_link_write_vals`).
3. **Re-aplica** precio y cantidad con `plan_product_price_quantity_reapply` — Odoo puede resetear `price_unit` al vincular OC.
4. Re-aplica montos de impuesto en líneas `display_type=tax` (**último paso**) — IVA e IIBB del pie sobreescriben el recálculo de Odoo.

La UI y el matching OC (`purchase_matching.py`) **no** pisan `invoice_line_ids/price_unit`: solo asignan `product_id`, metadata de OC y, si aplica, cantidad re-escalada por UM. La fuente de verdad del precio al importar sigue siendo la columna **Precio** de la tabla (origen FacturIA o edición manual).

**Regresión corregida:** tras vincular OC, el borrador en Odoo quedaba con el precio de la línea de compra aunque FacturIA hubiera enviado otro `precio_unitario`. Tests: `test_plan_product_price_quantity_reapply_po_price_differs`, `test_plan_product_price_quantity_reapply_skips_without_po_link`, `test_plan_product_price_quantity_reapply_skips_unchanged` en `tests/test_odoo_import.py`.

### Padrón fiscal y remapeo de tax ids

El padrón Postgres (`view_padron_facturia`) almacena ids numéricos del tenant donde se generó (históricamente Dinner). En Aliare/Sudata:

- `PADRON_TAX_SOURCE_PROFILE` (default `default`) indica de qué Odoo leer la semántica de esos ids al remapear.
- IVA: id padrón → etiqueta canónica (21 %, 10,5 %, …) → id del tenant activo.
- IIBB: id padrón → nombre del impuesto en el tenant fuente → `resolve_tax_label_to_id` en el tenant activo.

Variable en `.env.example`: `PADRON_TAX_SOURCE_PROFILE=default`.

## Fecha de vencimiento vs error de Odoo

**Síntoma:**

```text
Cualquier apunte contable en una cuenta por pagar debe tener una fecha límite y viceversa.
```

**Qué significa:** Odoo valida `date_maturity` en cada **apunte contable** (`account.move.line`) con cuenta por pagar/cobrar. No alcanza con tener `invoice_date_due` en la tabla de FacturIA.

**Qué hace el import:**

1. Escribe `invoice_date_due` en el encabezado de la factura (fallback: `invoice_date` si falta vencimiento).
2. Completa `date_maturity` en apuntes AP/AR sin fecha (incluye líneas `payment_term`).
3. Al pisar montos de líneas `display_type=tax`, incluye `date_maturity` si la cuenta del impuesto es por pagar/cobrar.

**Si persiste el error** tras redeploy: revisar en Odoo el plan contable de la cuenta usada por la percepción IIBB (a veces está mal tipada como “por pagar” cuando debería ser pasivo corriente).

## Casos frecuentes de regresión

### Proceso 4 (una línea, 21 %)

- Modo esperado: **`line`**
- Columna IVA editable; pie readonly
- `iva_monto` editado debe importarse con ese monto, no con `__fac_iva_monto` viejo

### IVA del pie se mueve al cambiar Precio

- **Síntoma:** el **Monto IVA** de la línea sigue fijo (ej. 72.399,60) pero el **IVA 21 %** del pie pasa a `precio × 21 %` (ej. 777 → 163,17).
- **Causa:** al cambiar precio, JS recalculaba `iva_monto` de la línea y el desglose del pie caía al sugerido por línea en lugar de respetar el monto fijo de FacturIA (`__fac_iva_monto` / `iva_monto` explícito).
- **Solución:** deploy con `computeRowTotal` + `computeIvaBreakdown` actualizados; recargar la UI. Tests: `header footer IVA fixed when price changes` en `tests/js/comprobante_tax.test.mjs`.

### Encabezado desincronizado (línea editada, JSON viejo)

Ejemplo real: `iva_monto = 60.000` pero `__fac_iva_monto = 6000`.

- `reconcile_fac_iva_for_import` corrige el JSON en modo `line` con `__iva_monto_manual`.
- Sin eso, el servidor podía usar 6000 y clasificar mal.

### IVA editado en el pie (`mixed` / `header`, varias alícuotas)

Ejemplo: tres líneas con 21 % y 10,5 %, pero en el pie el usuario fija IVA 21 % = 15.893,38 e IVA 10,5 % = 2.832,75 (distintos al cálculo por línea).

- `__fac_iva_montos` del pie debe importarse tal cual y **sobreescribir** las líneas tax de Odoo.
- Tests: `test_reconcile_preserves_footer_iva_montos_in_mixed_mode`, `test_fac_iva_montos_prefers_edited_footer_total_over_stale_json`, `test_collect_expected_uses_edited_footer_after_reconcile`

### IIBB / percepciones (CABA, ARBA, …)

- Montos desde el pie y slots `otros_impuestos_N` en cualquier fila del comprobante.
- Primera línea de producto recibe los `tax_ids` no-IVA del comprobante en header/mixed.
- Si al **primer** import el monto en Odoo no coincide pero al **segundo** clic sí: el deploy anterior aplicaba montos tax **antes** de re-aplicar precio; Odoo recalculaba la percepción encima. Con el orden correcto (precio → montos tax) debe bastar **un** clic.
- **No** borrar `tax_ids` con `(5,)` para forzar líneas tax: en Aliare puede desaparecer la etiqueta del impuesto en el borrador.
- Tests: `test_collect_expected_iibb_from_header_only_row`, `test_plan_line_tax_updates_puts_iibb_on_first_content_line`, `test_sync_applies_tax_amounts_after_all_line_writes`

### Columnas “Otros impuestos” (slots N)

| Comportamiento | Detalle |
|----------------|---------|
| **Padrón** | `apply_padron_taxes_to_row` solo llena el slot 1 (`otros_impuestos`); los ids restantes van en `_padron_other_tax_ids` para el import, **sin** crear `otros_impuestos_2..N` en la UI |
| **Al cargar conversión** | `_strip_empty_extra_otro_impuesto_slots` elimina slots `_2..N` sin monto (legacy) |
| **Columnas visibles** | `infer_otro_impuesto_indices`: slot 1 puede tener solo etiqueta; slots `_2+` solo si tienen monto > 0 |
| **Dropdown** | `otros_impuestos_options_from_odoo`: labels canónicos que resuelven en el tenant + **extras dinámicos** (todo `account.tax` purchase no-IVA no cubierto). Alias Aliare: `Perc Gananc` / `Perc IVA` / `IVA Adic 20%`. |

Si un usuario ve ~19 columnas vacías: conversión guardada con versión antigua → **Restaurar original** o recargar tras deploy.

### Aliare sin `odoo_profile`

- Síntoma: IVA 21 % mapea a id 63 (en Aliare es 10,5 %); montos no se sobreescriben o impuesto incorrecto.
- Solución: `?odoo_profile=aliare` en URL y en POST `/api/odoo/import`.

### IVA del pie no se sobreescribe en Odoo (formato es-AR)

- Síntoma: el pie muestra montos editados (ej. IVA 21 % = 53.515,40) pero Odoo queda con el cálculo por línea.
- Causa: `__fac_iva_montos` con strings `"53.515,40"` no parseados en servidor → import ignoraba el pie.
- Solución: deploy con `_explicit_fac_iva_montos` usando `parse_amount_loose`; reimportar con autosave previo.

### Formatos numéricos híbridos

Montos tipo `350.0,00` (punto decimal + coma es-AR) se normalizan en:

- **JS:** `sanitizeNumericString` (`static/js/utils/numbers.js`)
- **Python:** `_sanitize_hybrid_amount_string` (`core/amounts.py`)

### Precio distinto al de la OC en Odoo

- **Síntoma:** la factura importada con OC vinculada muestra en Odoo el precio de la orden de compra, no el de FacturIA / la columna Precio.
- **Causa:** al escribir `purchase_line_id`, Odoo reemplazaba `price_unit` por el de la línea PO; no había un paso posterior que restaurara el precio enviado.
- **Solución:** deploy con `plan_product_price_quantity_reapply` en `sync_move_taxes_from_group`; reimportar el borrador (debe estar en `draft`).

### Re-import de factura ya rota

Si un import anterior dejó el borrador sin IVA en las líneas de producto, un re-import con el código actualizado debe:

1. Volver a poner `tax_ids` de IVA (modo `line` / `mixed`)
2. Asegurar líneas tax faltantes (`_ensure_missing_tax_lines_on_move`)
3. Escribir montos en líneas tax
4. Completar fechas límite en apuntes

## Tests útiles

```bash
# Python
PYTHONPATH=src python3 -m unittest discover -s tests

# JS (paridad con fixtures compartidos)
npm run test:js
```

Archivos clave:

- `tests/fixtures/tax_scenarios.json` — escenarios compartidos JS/Python
- `tests/test_comprobante_tax.py` — clasificación, totales, reconcile del pie, JSON es-AR en `__fac_iva_montos`
- `tests/test_process_conversions.py` — slots otros impuestos, strip legacy al cargar
- `tests/test_odoo_import.py` — import, fechas, tax_ids, IIBB, montos esperados, re-aplicar precio/cantidad tras vínculo OC
- `tests/test_iva_tax_resolve.py` — resolución IVA y remapeo padrón Aliare
- `tests/test_tax_pipeline.py` — pipeline end-to-end sobre fixtures

## Archivos de código

| Área | Archivos |
|------|----------|
| Clasificación y totales Python | `core/comprobante_tax.py` |
| Resolución y remapeo impuestos | `padron/taxes.py` |
| Import Odoo | [import-odoo/](import-odoo/README.md), `odoo/import_/` |
| UI pie comprobante | `static/js/comprobanteView/footer.js` |
| UI desglose IVA | `static/js/comprobanteTax/ivaBreakdown.js` |
| IVA fijo vs precio (línea) | `static/js/rows/totals.js` → `computeRowTotal` |
| UI tabla / blur IVA | `static/js/table/render.js` |
| Tax JS | `static/js/comprobanteTax/*.js` |
