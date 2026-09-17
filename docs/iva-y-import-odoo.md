# IVA por comprobante e import a Odoo

Guía de comportamiento de la UI, el cálculo de totales y el pipeline de importación a Odoo (`import_rows_to_odoo` / `sync_move_taxes_from_group`).

**Implementación Odoo (módulos, pipeline, API, tests):** [import-odoo/](import-odoo/README.md).

## Perfil Odoo (`odoo_profile`)

Los **ids numéricos** de `account.tax` dependen del tenant (Dinner, Aliare, Sudata). La misma alícuota puede ser id distinto en cada Odoo:

| Alícuota | Dinner (ej.) | Aliare (ej.) | Sudata |
|----------|--------------|--------------|--------|
| 21 %     | 63           | 65           | 65 (`VAT 21%`) |
| 10,5 %   | 61           | 63           | 63 (`VAT 10.5%`) |
| 27 %     | 65           | 67           | 67 (`VAT 27%`) |

### Idioma del catálogo (`resolve_odoo_lang`)

Los nombres de `account.tax` son **campos traducibles**: llegan en el idioma que pide el RPC. Pedir uno no instalado no falla, devuelve el texto fuente en inglés (`VAT 21%` en vez de `IVA 21%`).

`resolve_odoo_lang` elige, en orden:

1. Override por env: `ODOO_LANG_SUDATA` / `ODOO_LANG_ALIARE` / `ODOO_LANG`.
2. Primer idioma de `ODOO_LANG_CANDIDATES` **instalado** en el tenant: `es_AR`, si no `es_419` (se consulta `res.lang` una vez por tenant, cacheado).
3. Default histórico: `es_AR` en Dinner/Aliare, sin `lang` en Sudata.

| Tenant | Idioma instalado | `lang` usado | Nombres |
|--------|------------------|--------------|---------|
| Dinner / Aliare | `es_AR` | `es_AR` | `IVA 21%`, `Perc IVA` |
| Sudata Cloud | `es_419` (es_AR inactivo) | `es_419` | `IVA 21%`, `Perc IVA` |

Aun así la resolución **no depende del idioma**: se hace por `amount` (alícuota) y acepta prefijos `IVA `/`VAT ` (`_IVA_TAX_NAME_PREFIXES`) más alias EN de las alícuotas cero (`_SPECIAL_IVA_NAME_KEYS`). Los alias de percepciones son bidireccionales (`Perc IVA` ↔ `Perc VAT`) para que las conversiones guardadas con el catálogo en inglés sigan resolviendo. Ver [§ IVA 21 % llega como IVA 10,5 % en Sudata](#iva-21--llega-como-iva-105--en-sudata-nombres-en).

**Siempre** pasar `?odoo_profile=aliare` (o `perfil=aliare`) en la URL y en el import cuando se trabaja contra Aliare. Sin perfil, la UI resuelve impuestos contra Dinner y los ids no coinciden con Odoo Aliare.

La resolución dinámica vive en `padron/taxes.py` (`resolve_iva_tax_id_for_pct`, `resolve_tax_label_to_id`, catálogo Odoo del perfil activo). El padrón Postgres guarda ids del tenant fuente; ver `PADRON_TAX_SOURCE_PROFILE` más abajo.

## Modos de IVA

Cada comprobante (grupo de filas con el mismo `__comprobante_idx` o número de documento) se clasifica en uno de tres modos:

| Modo | Cuándo | IVA editable en la tabla | IVA editable en el pie |
|------|--------|--------------------------|-------------------------|
| **`line`** | Todas las líneas tienen `iva_pct` y los montos por fila cierran con el encabezado FacturIA, o hay `iva_monto` editado en la fila | No (montos solo en pie; la tabla conserva **Impuesto IVA** %) | Sí |
| **`header`** | El IVA viene del encabezado (`__fac_iva_monto` / `__fac_iva_montos`) y no hay tasas por línea, o una sola línea cuyo % no cierra y el IVA no fue editado manualmente | No | Sí |
| **`mixed`** | Hay líneas con y sin `iva_pct`, o varias alícuotas con totales que no cierran de forma uniforme | No (montos solo en pie) | Sí |

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
| `__fac_iva_monto_manual` | Pie del comprobante (modo `line`) | Marca override del total IVA desde abajo; el pie manda al import |
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

- **Un solo IVA en el pie:** al cargar, si `__fac_iva_montos` tiene una sola alícuota, se rellena **Impuesto IVA** (`iva_pct`) en todas las líneas vacías/`0` del comprobante (`propagateSingleFooterIvaToLines` / `propagate_single_footer_iva_to_lines`).
- **Montos solo en el pie:** la UI **no** muestra columnas **Monto IVA** / **Monto Otros Impuestos**. Se edita abajo (estilo Odoo). `showIvaMontoColumn` siempre false.
- **Modo `line`:** el pie sigue editable; si el usuario cambia el total abajo se marca `__fac_iva_monto_manual` y ese valor manda al import.
- **Modo `header` / `mixed`:** editar IVA en el **pie** (`comprobanteView/footer.js` → `serializeFacIvaMontos`).
- Al cambiar cantidad, precio o IVA % en modo `line` (sin override de pie), JS llama `syncFacIvaMontosFromLines` para alinear `__fac_iva_montos` antes de autosave.
- Editar el campo **IVA** total (`rateKey === "_total"`) actualiza también el desglose cuando hay una sola alícuota (o asume 21 % si no hay desglose).
- **Cambiar la alícuota de una línea** re-etiqueta el pie si ninguna de sus alícuotas sigue en las líneas (el monto se conserva): ver [Cambiar la alícuota en la línea deja la vieja en el pie](#cambiar-la-alícuota-en-la-línea-deja-la-vieja-en-el-pie-testing-elías-1382026).

### IVA fijo al cambiar precio o cantidad

Si el monto IVA del pie / línea ya está fijado (override o FacturIA ≠ `precio × cantidad × %`), cambiar **Precio** o **Cantidad** **no debe** pisar ese monto fijo sin querer.

| Situación | Comportamiento esperado |
|-----------|-------------------------|
| Pie con `__fac_iva_monto_manual` o modo `header` | Se conserva el monto del pie |
| Modo `line` sin override, `iva_monto` auto | Al editar precio/cantidad se limpia sticky y se realinea el pie |

**JS:** `table/render.js` re-renderiza si el modo tax cruza `line` ↔ `header`/`mixed`.

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
            6. re-aplicar price_unit / quantity / product_uom_id en todas las líneas de producto
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
| Modo `line` con `__fac_iva_monto_manual` | **No recalcula** desde líneas; el pie manda al import |
| Encabezado desincronizado (línea editada, JSON viejo) en modo `line` | Corrige `__fac_iva_montos` desde las líneas |

Sin esta distinción, un comprobante `mixed`/`header` con IVA editado en el pie podía perder los montos antes del import: el servidor reemplazaba el JSON por el cálculo por línea y **no había nada que sobreescribir en Odoo**.

### Regla de `tax_ids` en líneas de producto

- **`header`:** ninguna línea lleva IVA numérico en `tax_ids` (el total IVA va en el pie). **Excepción:** `IVA Exento`, `IVA No Gravado` e `IVA No Corresponde` sí van en la línea de producto (monto 0 en Odoo).
- **`line` / `mixed`:** IVA en la línea si esa fila tiene `iva_pct > 0` o `IVA Exento` / `IVA No Gravado` / `IVA No Corresponde`.
- **`"0"` (header FacturIA):** sin tax IVA en la línea (distinto de No Corresponde).
- **Otros impuestos por línea:** cada fila de producto lleva a Odoo los `otros_impuestos` de **esa** fila (`_tax_ids_for_odoo_line`). Si querés agruparlos en una sola línea, usá «agregar más» en la UI.
- **IIBB / percepciones en solo encabezado:** se agregan a la **primera línea con contenido** (`_header_only_non_iva_tax_ids`, `_merge_header_only_non_iva_tax_ids` en `odoo/import_/taxes.py`).
- Tras OC/precio el sync **re-aplica `tax_ids`** para no perder lo de cada línea.
La distinción vive en `iva_pct_requires_line_tax` (`padron/taxes.py`).

### Pie de comprobante (UI)

- **IVA:** con un solo producto y `IVA Exento`, `IVA No Gravado` o `IVA No Corresponde`, no se muestran filas de IVA en el pie (y el total no incluye 21 % residual de FacturIA). El `0` de modo header FacturIA sigue mostrando el pie.
- **Cambio de Impuesto IVA a cero explícito:** limpia `__fac_iva_montos` / `__fac_iva_monto` del comprobante para que el import no mande IVA 21 % junto con Exento/No Gravado/No Corresponde.
- **Otros impuestos:** el pie muestra **lo que trae FacturIA** (IIBB / Percepción IVA / Impuesto Interno + montos) **hasta que** asignás un impuesto Odoo **de ese mismo tipo** en el slot. Elegir **Impuesto Interno** en la 1ª línea (col Otros) es `tax_ids` de esa fila: **no** renombra el slot IIBB ni oculta IIBB, ni duplica Interno (Dinner FA-A 05215-00084885). Si agregás un impuesto con **+** **o** elegís uno extra en otra línea (p.ej. **IVA Adicional 20%**) y todavía no hay monto, el pie **igual lista la fila** (monto 0 / vacío) para editarlo abajo. El key FacturIA `otros_tributos` se etiqueta como **Impuesto Interno**. Las líneas se asignan a mano; col 2/3 solo si esa línea tiene más de un impuesto. Si faltan asignaciones en líneas → aviso `missingFacOtrosAssignments` (Interno en el slot IIBB **no** cubre IIBB). La columna **Total** de cada línea solo suma `otros_*_monto` de slots **con label** en esa fila (montos FacturIA sin asignar en la 1ª fila alimentan el pie, no inflan el Total). Código: `otrosBreakdown.js` + `footer.js` + `rows/totals.js`.

### Reload y Monto IVA (migración legacy)

`migrateLegacyComprobanteIva` solo mueve `iva_monto` de fila 0 → `__fac_iva_monto` en saves **legacy** (sin alícuotas por línea). En comprobantes modernos multi-línea con `iva_pct` / `__iva_monto_manual` **no** borra montos ni fuerza modo `header` (regresión PDF Salta: editar Monto IVA + F5 no debe ocultar la columna).

Si el modo se clasifica mal como `header` cuando el usuario editó `iva_monto` en la tabla, Odoo **quita el IVA** de la línea y el import no tiene dónde escribir el monto → el IVA “desaparece”.

### Montos de impuesto esperados

`collect_expected_tax_amounts_from_group` → `_apply_tax_line_amount_overwrites`:

- **`line`:** suma `line_iva_monto(row)` por fila, indexado por `account.tax` id del perfil activo.
- **`header` / `mixed`:** usa `fac_iva_montos(group)` y mapea cada alícuota con `_iva_tax_id_for_rate` + `_iva_tax_resolve_row` (primera línea con `iva_pct` o fila con metadata del pie).
- **IIBB / otros:** suma todos los slots `otros_impuestos_N` / `otros_impuestos_N_monto` de **cualquier fila** del comprobante. Si el monto está en la 1ª fila **sin label** (hidratación FacturIA) y el impuesto Odoo está en otra línea, se mapea por `amount_key` (`percepcion_iibb` / `percepcion_iva` / `otros_tributos`) al tax id de esa línea — no se pisa el IIBB de la 1ª fila. Remapeo de ids padrón vía `build_csv_additional_taxes` (`padron/taxes.py`).

Si falta una línea `display_type=tax` en Odoo para un impuesto esperado, `_ensure_missing_tax_lines_on_move` refuerza `tax_ids` en la primera línea de producto (incluye IVA faltante en header) y luego se pisan los montos.

Odoo puede recalcular impuestos al actualizar `tax_ids`, al vincular `purchase_line_id` o al re-aplicar precio. Por eso la sobreescritura de montos ocurre **al final** de `sync_move_taxes_from_group`, **después** del reapply de precio/cantidad.

### Precio de línea con Orden de Compra

Cuando una fila tiene match de OC (`__oc_line_id`), el import:

1. Escribe primero `price_unit` y `quantity` desde la UI / FacturIA (`invoice_line_ids/price_unit`, `invoice_line_ids/quantity`) en el paso de contenido de líneas.
2. Vincula `purchase_line_id` + `product_id` en un write separado (`_po_link_write_vals`).
3. **Re-aplica** precio y cantidad con `plan_product_price_quantity_reapply` — Odoo puede resetear `price_unit` al vincular OC.
4. Re-aplica montos de impuesto en líneas `display_type=tax` (**último paso**) — IVA e IIBB del pie sobreescriben el recálculo de Odoo.

La UI y el matching OC (`odoo/purchase_matching/`) **no** pisan `invoice_line_ids/price_unit`: solo asignan `product_id`, metadata de OC y, si aplica, cantidad re-escalada por UM. La fuente de verdad del precio al importar sigue siendo la columna **Precio** de la tabla (origen FacturIA o edición manual).

**Regresión corregida:** tras vincular OC, el borrador en Odoo quedaba con el precio de la línea de compra aunque FacturIA hubiera enviado otro `precio_unitario`. Tests: `test_plan_product_price_quantity_reapply_po_price_differs`, `test_plan_product_price_quantity_reapply_salta_pack_lines_ui_vs_po`, `test_plan_product_price_quantity_reapply_shared_oc_line_falls_back_to_index`, `test_plan_product_price_quantity_reapply_skips_unchanged` en `tests/test_odoo_import_purchase.py`. El empareje evita omitir filas cuando varias UI comparten el mismo `purchase_line_id` (cae a índice).

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
- Columna IVA editable; pie también editable (override del total)
- Sin override de pie: `iva_monto` de la línea manda al import
- Con override de pie (`__fac_iva_monto_manual`): el pie manda al import

### IVA del pie se mueve al cambiar Precio

- **Síntoma:** el **Monto IVA** de la línea sigue fijo (ej. 72.399,60) pero el **IVA 21 %** del pie pasa a `precio × 21 %` (ej. 777 → 163,17).
- **Causa:** al cambiar precio, JS recalculaba `iva_monto` de la línea y el desglose del pie caía al sugerido por línea en lugar de respetar el monto fijo de FacturIA (`__fac_iva_monto` / `iva_monto` explícito).
- **Solución:** deploy con `computeRowTotal` + `computeIvaBreakdown` actualizados; recargar la UI. Tests: `header footer IVA fixed when price changes` en `tests/js/comprobante_tax.test.mjs`.

### Base imponible salta al agregar IVA en una línea (PDF Mauri 24/7/2026)

- **Síntoma:** comprobante en modo **header** (líneas sin `iva_pct`, pie con IVA); al elegir **IVA 21 %** en una línea la **Base imponible** baja de p. ej. `$188.102` (`__fac_subtotal`) a `$78.727` (Σ qty×precio).
- **Causa:** el modo pasaba a **mixed** y `computeComprobanteTotals` / `compute_comprobante_totals` solo usaban `__fac_subtotal` en `header`; en `mixed` cambiaban a suma de líneas.
- **Solución:** en **header** y **mixed**, Base = `__fac_subtotal` cuando existe; en **line**, Base = suma de líneas. El IVA del pie sigue mandando en mixed (invariante).
- Tests: `test_mixed_mode_keeps_fac_subtotal_as_base_odoo`, `keeps fac subtotal as Base when selecting IVA flips header→mixed (PDF Mauri)`.

### IVA Exento / No Gravado / No Corresponde deja IVA 21 % residual

- **Síntoma (testing Mauri 16/7/2026):** se elige **IVA Exento**, **IVA No Gravado** o **IVA No Corresponde** en Impuesto IVA, pero el pie sigue con total que incluye 21 % y Odoo muestra **IVA 21 %** + el impuesto elegido en `$0,00`.
- **Causa:** `__fac_iva_montos` / `__fac_iva_monto` de FacturIA no se limpiaban al cambiar el selector; el import usaba esos montos y `_ensure_missing_tax_lines_on_move` re-agregaba IVA 21 % en la línea.
- **Solución:** al elegir IVA cero explícito en todas las líneas del comprobante, se limpia el pie (`clear_fac_iva_footer` / `clearFacIvaFooter`); `fac_iva_montos` / `computeIvaBreakdown` ignoran el JSON residual; `reconcile_fac_iva_for_import` limpia antes del sync. El modo **header** con `iva_pct` vacío sigue usando el pie.
- Tests: `test_meriti_exento_clears_stale_21_footer_amounts`, `clears stale 21% footer when selecting IVA Exento` en `tests/js/comprobante_tax.test.mjs`.

### Cambiar la alícuota en la línea deja la vieja en el pie (testing Elías 13/8/2026)

- **Síntoma:** comprobante Sudata en modo **header** con pie `{"21": "48306,18"}`; al cambiar **Impuesto IVA** de `21` a `10,5` el pie muestra **las dos** filas (`IVA 21 %` con el monto original + `IVA 10,5 %`) y el import sigue mandando el impuesto **21 %** (id 65 en Sudata), o sea que cambiar la alícuota no tenía ningún efecto en Odoo.
- **Causa:** el desglose unía las alícuotas de las líneas con las claves guardadas en `__fac_iva_montos` (`rateKeys = suggested ∪ stored`), y `fac_iva_montos` devolvía el JSON tal cual, así que la alícuota vieja sobrevivía al cambio.
- **Solución:** si **ninguna** alícuota del pie sigue declarada en las líneas, el pie se **re-etiqueta** a las alícuotas de las líneas conservando el monto (`_realign_footer_rates` / `realignFooterRates`). Con varias alícuotas declaradas el monto se reparte proporcional al IVA sugerido de cada una. El cambio se persiste (`_persist_realigned_footer_rates` en `reconcile_fac_iva_for_import`; `persistRealignedFooterRates` al cambiar el selector) para que el autosave no deje la clave vieja.
- **Invariantes que no se tocan** (el pie queda igual):
  - Alguna alícuota del pie **sí** está en las líneas (pie FacturIA multi-alícuota, ej. líneas 21 % + 10,5 %).
  - Alguna línea con contenido **no declara** alícuota (`iva_pct` vacío o `"0"`): modo header legítimo, el pie manda.
  - Las líneas **no cubren** `__fac_subtotal`: el pie puede tener montos de la parte no desglosada (ver `test_header_partial_fac_iva_montos_matches_footer_total`).
- Tests: `test_switching_line_rate_relabels_footer_iva`, `test_switching_line_rate_persists_relabeled_footer`, `test_footer_rate_not_covered_by_lines_is_kept`, `test_switching_line_rate_sends_new_iva_tax_id`, `cambio de alícuota en la línea (Sudata 13/8/2026)` en `tests/js/comprobante_tax.test.mjs`.

### Pie con un solo IVA y líneas sin Impuesto IVA

- **Síntoma:** el pie muestra p. ej. **IVA 21 %** con monto, pero la columna **Impuesto IVA** de las líneas está vacía (FacturIA trajo `iva_21` en encabezado sin `alicuota_iva` por ítem).
- **Comportamiento:** si `__fac_iva_montos` tiene **una sola** alícuota, se copia a `iva_pct` de **todas** las líneas del comprobante que estén vacías o en `"0"` (no pisa Exento / No Gravado / No Corresponde). Con varias alícuotas en el pie, no se propaga.
- **Dónde:** JS `propagateSingleFooterIvaToLines` al cargar proceso; Python `propagate_single_footer_iva_to_lines` al parsear / backfill de conversión.
- Tests: `propagates single footer IVA to empty line iva_pct`, `test_propagate_single_footer_iva_to_lines`.

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
- **Montos FacturIA en 1ª fila + impuestos en otras líneas (Dinner, FA-A 05215-00084885):** el pie UI muestra IIBB / Perc IVA / Interno correctos, pero Odoo Dinner dejaba Perc IVA e Interno en el % de la línea y el IIBB como **suma** IIBB+Perc IVA. No es un error de `odoo_profile` (Aliare/Sudata): el catálogo Dinner resolvía bien los nombres. Causa: slots 2/3 de la 1ª fila van sin label y el import los asignaba al tax id del slot 1. Solución: mapear esos montos al label Odoo de la línea que tiene ese `amount_key`. Tests: `test_collect_expected_otros_unlabeled_slots_map_to_line_labels`, `test_collect_expected_otros_unlabeled_slots_without_fac_percepciones`.
- **Impuesto Interno en la 1ª fila oculta IIBB y duplica Interno (Dinner, mismo comprobante):** el slot 1 FacturIA es IIBB (`9154,93`); elegir Interno ahí **no** debe renombrar esa fila del pie. Causa: `labelForFooterSlot` usaba el label de la 1ª fila y `sumAmountForFooterSlot` sumaba por nombre → dos filas «Impuesto Interno» con `9154,93`, IIBB desaparecía, el total seguía incluyendo `18962,88`, y Odoo internaba `9154,93+18962,88=28117,81`. Tests: `keeps IIBB in pie when first row selects Impuesto Interno`, `test_collect_expected_interno_on_iibb_slot_does_not_steal_iibb_amount`.
- **No** borrar `tax_ids` con `(5,)` para forzar líneas tax: en Aliare puede desaparecer la etiqueta del impuesto en el borrador.
- Tests: `test_collect_expected_iibb_from_header_only_row`, `test_plan_line_tax_updates_puts_iibb_on_first_content_line`, `test_sync_applies_tax_amounts_after_all_line_writes`

### Columnas “Otros impuestos” (slots N)

| Comportamiento | Detalle |
|----------------|---------|
| **Padrón** | `apply_padron_taxes_to_row` solo llena el slot 1 (`otros_impuestos`); los ids restantes van en `_padron_other_tax_ids` para el import, **sin** crear `otros_impuestos_2..N` en la UI |
| **Al cargar conversión** | `_strip_empty_extra_otro_impuesto_slots` elimina slots `_2..N` sin monto (legacy) |
| **Columnas visibles** | `infer_otro_impuesto_indices`: slot 1 = etiqueta o monto; slots `_2+` **solo si tienen etiqueta** (botón +). Montos FacturIA sin label alimentan el pie, **no** abren «Otros Impuestos (2/3)» |
| **Labels en col 2/3** | Solo si **esa línea** tiene más de un impuesto (botón +). No se espejan en la 1ª fila los impuestos elegidos en otras líneas; el pie usa `__fac_otros_claimed` |
| **Dropdown** | `otros_impuestos_options_from_odoo`: **todos** los `account.tax` del tenant (sin filtrar por lista canónica), orden alfabético. Nombres EN sin i18n (`Internal taxes` / `Other taxes`) → `Impuestos internos` / `Otros impuestos`. Alias de resolución: `Perc Gananc` / `Perc IVA` / `IVA Adic 20%` / `Impuesto Interno`. |

Si un usuario ve ~19 columnas vacías: conversión guardada con versión antigua → **Restaurar original** o recargar tras deploy.

### Aliare sin `odoo_profile`

- Síntoma: IVA 21 % mapea a id 63 (en Aliare es 10,5 %); montos no se sobreescriben o impuesto incorrecto.
- Solución: `?odoo_profile=aliare` en URL y en POST `/api/odoo/import`.

### IVA 21 % llega como IVA 10,5 % en Sudata (nombres EN)

- **Síntoma (testing Elías 13/8/2026, Sudata producción):** la UI muestra **Impuesto IVA 21** y el pie **IVA 21 %**, pero el borrador en Odoo queda con **IVA 10,5 %** (el monto sí es el del pie). En Central Ticket / Aliare el mismo caso llega bien.
- **Causa:** Sudata Cloud responde `account.tax` en inglés (`VAT 21%`, `VAT 10.5%`, `0% NA`, `0% NT`, `0% EXEMPT`, `Perc VAT`). El filtro de IVA exigía nombres que empiecen con `IVA ` → `get_purchase_iva_taxes()` devolvía **lista vacía** → `resolve_iva_tax_id_for_pct("21")` caía al mapa histórico **de Dinner** (`21 → 63`), y en Sudata el id 63 es `VAT 10.5%`. Todas las alícuotas quedaban corridas (10,5 → `VAT 0%`, 27 → `VAT 21%`) y Exento/No Gravado/No Corresponde también.
- **Solución:**
  1. `_is_purchase_iva_tax_name` / `_rate_matches_iva_tax_name` aceptan prefijo `VAT ` además de `IVA `.
  2. `_SPECIAL_IVA_NAME_KEYS` mapea las alícuotas cero EN: `0% NA` → No Corresponde, `0% NT` → No Gravado, `0% EXEMPT` → Exento (matcher único `_special_iva_label_from_name`).
  3. El fallback a ids fijos de Dinner (`_LEGACY_DINNER_IVA_BY_RATE`) **solo** corre con perfil `default` (`_legacy_dinner_fallback_allowed`): en otro tenant es mejor no mandar impuesto que mandar el equivocado.
  4. `_UI_TAX_NAME_ALIASES` resuelve `Perc VAT` / `Perc Profits` para percepciones IVA / Ganancias.
  5. Complemento: `resolve_odoo_lang` ahora pide `es_419` en Sudata (ver [§ Idioma del catálogo](#idioma-del-catálogo-resolve_odoo_lang)), así el catálogo llega en español como en Dinner/Aliare. El fix de resolución no depende de eso.
- **Efecto en borradores ya rotos:** reimportar alcanza mientras el borrador siga en `draft` — `plan_line_tax_updates` escribe `tax_ids` con `(6, 0, …)` y saca el 10,5 % viejo antes de que `_ensure_missing_tax_lines_on_move` agregue el 21 %.
- Tests: `test_sudata_english_names_21_maps_to_65_not_63`, `test_sudata_english_zero_rate_labels`, `test_sudata_english_names_give_iva_pct_semantics`, `test_no_dinner_fallback_when_profile_is_not_default`, `test_sudata_english_percepcion_labels_resolve` en `tests/test_iva_tax_resolve.py`.

### IVA del pie no se sobreescribe en Odoo (formato es-AR)

- Síntoma: el pie muestra montos editados (ej. IVA 21 % = 53.515,40) pero Odoo queda con el cálculo por línea.
- Causa: `__fac_iva_montos` con strings `"53.515,40"` no parseados en servidor → import ignoraba el pie.
- Solución: deploy con `_explicit_fac_iva_montos` usando `parse_amount_loose`; reimportar con autosave previo.

### Formatos numéricos híbridos

Montos tipo `350.0,00` (punto decimal + coma es-AR) se normalizan en:

- **JS:** `sanitizeNumericString` (`static/js/utils/numbers.js`)
- **Python:** `_sanitize_hybrid_amount_string` (`core/amounts.py`)

### Cantidad/precio FacturIA con 3 decimales (ej. litros)

- **Síntoma:** línea con `cantidad=15.175` y `precio_unitario=1457.256` aparece como **1** × **1,46**.
- **Causa:** `parse_amount_loose` / `toNumberLoose` interpretaban el punto con 3 dígitos como miles (`15.175`→15175, `1457.256`→1457256) y `sanitize_inflated_line_amounts` “corrija” el desborde vs `__fac_subtotal`.
- **Solución:** al ingerir, `format_fac_amount_for_ui` escribe coma decimal (`15,175` / `1457,256`); el parseo ya no colapsa decimales US cuya parte entera tiene más de 3 dígitos. Recargar el proceso (o **Restaurar original** si había conversión guardada).

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
- `tests/test_odoo_import_*.py` — import, fechas, tax_ids, IIBB, montos esperados, re-aplicar precio/cantidad tras vínculo OC
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
| UI desglose otros | `static/js/comprobanteTax/otrosBreakdown.js` |
| IVA fijo vs precio (línea) | `static/js/rows/totals.js` → `computeRowTotal`, `clearStickyLineIvaOnPriceQtyEdit` |
| UI tabla / blur IVA | `static/js/table/render.js` |
| Tax JS | `static/js/comprobanteTax/*.js` |
