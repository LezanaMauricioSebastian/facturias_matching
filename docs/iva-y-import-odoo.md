# IVA por comprobante e import a Odoo

Guía de comportamiento de la UI, el cálculo de totales y el pipeline de importación a Odoo (`import_rows_to_odoo` / `sync_move_taxes_from_group`).

## Modos de IVA

Cada comprobante (grupo de filas con el mismo `__comprobante_idx` o número de documento) se clasifica en uno de tres modos:

| Modo | Cuándo | IVA editable en la tabla | IVA editable en el pie |
|------|--------|--------------------------|-------------------------|
| **`line`** | Todas las líneas tienen `iva_pct` y los montos por fila cierran con el encabezado FacturIA, o hay `iva_monto` editado en la fila | Sí (columna **IVA monto**) | No (solo lectura, resumen) |
| **`header`** | El IVA viene del encabezado (`__fac_iva_monto` / `__fac_iva_montos`) y no hay tasas por línea, o una sola línea cuyo % no cierra y el IVA no fue editado manualmente | No (columna oculta o sin uso) | Sí (pie del comprobante) |
| **`mixed`** | Hay líneas con y sin `iva_pct`, o varias alícuotas con totales que no cierran de forma uniforme | Depende de la fila | Parcial (pie para el total / JSON explícito) |

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
| `__fac_iva_monto` | FacturIA | Total IVA del comprobante en encabezado |
| `__fac_iva_montos` | FacturIA / sync | JSON `{"21": "57255.38", …}` por alícuota |
| `__fac_subtotal` | FacturIA | Subtotal del comprobante |
| `otros_impuestos_monto` | FacturIA / pie | Percepciones, IIBB, etc. |

En **modo `line`**, los totales y el import usan `iva_monto` de cada fila, no el JSON guardado en `__fac_iva_montos`, salvo que ese JSON haya sido sincronizado desde las líneas.

## Edición en la UI

- **Modo `line`:** editar **IVA monto** arriba → el pie se actualiza en vivo (readonly).
- **Modo `header` / `mixed`:** editar IVA en el **pie** del comprobante.
- Al cambiar cantidad, precio o IVA, JS llama `syncFacIvaMontosFromLines` para alinear `__fac_iva_montos` antes de autosave.

## Import a Odoo (resumen del pipeline)

```
filas UI
  → _prepare_rows_for_import
       · refresh OC
       · reconcile_fac_iva_for_import   # alinea encabezado si iva_monto ≠ __fac_iva_*
  → por comprobante:
       · crear account.move (borrador) o buscar duplicado por partner + ref
       · sync_move_taxes_from_group
            1. invoice_date / invoice_date_due en encabezado
            2. date_maturity en apuntes AP/AR que falten
            3. contenido de líneas de producto
            4. tax_ids (en header se quita IVA de líneas de producto)
            5. montos en líneas display_type=tax
            6. vínculos OC (purchase_line_id)
```

### Regla de `tax_ids` en líneas de producto

- **`header`:** ninguna línea lleva IVA en `tax_ids` (solo otros impuestos).
- **`line` / `mixed`:** IVA en la línea si esa fila tiene `iva_pct > 0`.

Si el modo se clasifica mal como `header` cuando el usuario editó `iva_monto`, Odoo **quita el IVA** de la línea y el import no tiene dónde escribir el monto → el IVA “desaparece”.

### Montos de impuesto esperados

`collect_expected_tax_amounts_from_group`:

- **`line`:** suma `line_iva_monto(row)` por fila, indexado por `account.tax` id.
- **`header` / `mixed`:** usa `__fac_iva_montos` explícito o `__fac_iva_monto`.

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

### Encabezado desincronizado

Ejemplo real: `iva_monto = 60.000` pero `__fac_iva_monto = 6000`.

- `reconcile_fac_iva_for_import` corrige el JSON antes de clasificar/importar.
- Sin eso, el servidor podía usar 6000 y clasificar mal.

### Re-import de factura ya rota

Si un import anterior dejó el borrador sin IVA en las líneas de producto, un re-import con el código actualizado debe:

1. Volver a poner `tax_ids` de IVA (modo `line`)
2. Escribir montos en líneas tax
3. Completar fechas límite en apuntes

## Tests útiles

```bash
# Python
PYTHONPATH=src python3 -m unittest discover -s tests

# JS (paridad con fixtures compartidos)
npm run test:js
```

Archivos clave:

- `tests/fixtures/tax_scenarios.json` — escenarios compartidos JS/Python
- `tests/test_comprobante_tax.py` — clasificación y totales
- `tests/test_odoo_import.py` — import, fechas, tax_ids
- `tests/test_tax_pipeline.py` — pipeline end-to-end sobre fixtures

## Archivos de código

| Área | Archivos |
|------|----------|
| Clasificación y totales Python | `core/comprobante_tax.py` |
| Import Odoo | `odoo/import_.py` |
| UI pie comprobante | `static/js/comprobanteView/footer.js` |
| UI tabla / blur IVA | `static/js/table/render.js` |
| Tax JS | `static/js/comprobanteTax/*.js` |
