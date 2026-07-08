# Guía de usuario — FacturIA → Odoo

Guía práctica para operadores que cargan procesos, revisan el matching y envían facturas a Odoo.

## URL y perfil Odoo

| Tenant | Parámetros en la URL |
|--------|----------------------|
| **Dinner** (default) | `?empresa=1&proceso=123` |
| **Aliare** | `?empresa=1&proceso=123&odoo_profile=aliare` |
| **Sudata** (cloud) | `?empresa=1&proceso=123&odoo_cloud=1` o `odoo_profile=sudata` |

**Regla:** si trabajás contra Odoo Aliare, la URL **siempre** debe incluir `odoo_profile=aliare`. Sin eso, los impuestos se resuelven contra Dinner y los ids no coinciden con Odoo Aliare (el IVA del pie no se sobreescribe correctamente).

Ejemplo dev Aliare:

```text
https://odoo-dev-….run.app/?empresa=1&proceso=48&odoo_profile=aliare
```

## Flujo habitual

1. Abrí la URL con empresa, proceso y perfil correctos.
2. Revisá el matching (proveedor, rubro, diario, cuenta, OC si aplica).
3. Editá lo necesario en la tabla o en el **pie del comprobante** (IVA, otros impuestos).
4. Esperá el autosave (o guardá explícitamente si la UI lo indica).
5. **Importar a Odoo** — crea o actualiza borradores y sincroniza impuestos + OC.

## Pie del comprobante (IVA y otros impuestos)

Cada factura tiene un bloque expandible con:

| Campo | Qué es |
|-------|--------|
| **Base imponible** | Subtotal (solo lectura) |
| **IVA 21 % / 10,5 % / …** | Montos de IVA por alícuota (editables en modos `header` y `mixed`) |
| **Otros impuestos** | IIBB, percepciones, etc. (editable) |
| **Total** | Base + IVA + otros (solo lectura) |

### Cuándo editar arriba vs abajo

| Modo | Dónde editar IVA | Pie IVA |
|------|------------------|---------|
| **line** | Columna **IVA monto** en cada fila | Solo lectura (resumen) |
| **header** | Pie del comprobante | Editable |
| **mixed** | Depende de la fila; totales en el pie | Editable por alícuota |

Si editás el IVA en el **pie**, esos montos son los que se envían a Odoo al importar (no el cálculo automático por línea).

### IVA fijo y cambio de Precio

Si el **Monto IVA** de una línea ya está fijado (lo editaste vos o vino así de FacturIA y no es simplemente `precio × %`), al cambiar **Precio** o **Cantidad** el IVA del **pie no se recalcula**: se mantiene el monto fijo.

Ejemplo: base 344.760 con IVA 21 % = 72.399,60. Si cambiás el precio de la línea, el pie sigue mostrando 72.399,60 — no pasa a `nuevo precio × 21 %`.

En modo **line**, el monto autoritativo es la columna **IVA monto**; el pie es solo un resumen (solo lectura). En modo **header**, el monto autoritativo es el pie (`__fac_iva_monto`).

### Formato de números

La UI acepta formato argentino: `53.515,40`, `350.000,00`, etc. Al importar, el servidor interpreta esos formatos en el pie y en otros impuestos.

## Otros impuestos (IIBB / percepciones)

- Solo deberías ver **una columna** “Otros impuestos” en la tabla (más slots extra solo si hay montos reales en `otros_impuestos_2`, `_3`, …).
- Si ves muchas columnas vacías (legacy de versiones anteriores): **Restaurar original** y volver a guardar, o recargar el proceso tras un deploy nuevo.
- El monto de **Otros impuestos** en el pie se consolida en la primera línea de producto al importar (junto con los `tax_ids` de IIBB del padrón).

## Import a Odoo — qué esperar

Al confirmar **Importar a Odoo**:

1. Se crean facturas en **borrador** (`in_invoice`) o se actualizan si ya existen (mismo proveedor + número de documento).
2. Se sincronizan líneas de producto, `tax_ids`, vínculos OC y **montos de impuesto** en las líneas `display_type=tax`.
3. Los montos del **pie** (IVA y otros) **sobreescriben** lo que Odoo calculó por línea — siempre al final del sync, después de vincular OC.
4. Si hay **Orden de Compra** vinculada, el **Precio** de la tabla (FacturIA o edición manual) se re-aplica en Odoo después del vínculo OC — no se usa el precio de la línea de compra.

Si el import dice “Actualizadas en Odoo” con “X impuestos”, los montos del pie se aplicaron. Si los montos en Odoo siguen siendo los calculados, revisá la sección [Problemas frecuentes](#problemas-frecuentes).

## Aliare vs Dinner — ids de impuesto

Los **números de id** de `account.tax` no son iguales entre tenants:

| Alícuota | Dinner | Aliare |
|----------|--------|--------|
| 21 %     | 63     | 65     |
| 10,5 %   | 61     | 63     |
| 27 %     | 65     | 67     |

No hace falta memorizarlos: la app los resuelve sola **si el perfil en la URL es correcto**.

## Variables de entorno relevantes (operaciones / deploy)

| Variable | Uso |
|----------|-----|
| `ODOO_BASE_URL_ALIARE`, `ODOO_USER_ALIARE`, `ODOO_API_KEY_ALIARE` | Credenciales import Aliare |
| `PADRON_TAX_SOURCE_PROFILE` | Tenant del que vienen los ids del padrón Postgres (default `default` = Dinner); se remapean al perfil activo |
| `FACTURIA_ODOO_PROFILE` | Perfil por defecto en deploy si la URL no trae `odoo_profile` |

Ver `.env.example` para la lista completa.

## Problemas frecuentes

### El IVA en Odoo no coincide con el pie

| Causa | Qué hacer |
|-------|-----------|
| Falta `odoo_profile=aliare` en la URL | Agregar el parámetro y recargar |
| No se guardó la edición del pie | Editar de nuevo, esperar autosave, reimportar |
| Factura no está en borrador | Solo se actualizan facturas `draft` |
| Proceso con conversión vieja corrupta | **Restaurar original** y repetir ediciones |

### El IVA del pie cambia al mover el Precio

Si el **Monto IVA** de la línea está fijo pero el **IVA %** del pie se recalcula al editar **Precio**, recargá la página con la versión actual del servidor. El pie debe respetar el monto fijo (columna IVA monto o valor de FacturIA), no `precio × alícuota`. Detalle técnico: [iva-y-import-odoo.md](iva-y-import-odoo.md#iva-fijo-al-cambiar-precio-o-cantidad).

### Muchas columnas “Otros impuestos” vacías

Versiones anteriores generaban una columna por cada impuesto del padrón. Tras actualizar: recargar proceso o restaurar original. Solo se muestran columnas con monto.

### Error “Valor numérico inválido”

Formatos híbridos raros (ej. `350.0,00`) ya se normalizan. Si persiste, reescribir el monto con formato AR estándar (`350.000,00`).

### Error de fecha límite en Odoo

```text
Cualquier apunte contable en una cuenta por pagar debe tener una fecha límite…
```

Completar **fecha de vencimiento** en FacturIA. El import propaga `invoice_date_due` y completa `date_maturity` en apuntes AP/AR. Si sigue fallando, revisar el tipo de cuenta del impuesto IIBB en Odoo.

### El precio en Odoo es el de la OC, no el de la factura

Tras importar con OC vinculada, Odoo puede mostrar el precio negociado en la orden de compra. El import debe restaurar el **Precio** de la tabla (FacturIA). Si ves el precio viejo de la OC: confirmá que el borrador está en `draft`, que la columna Precio en la UI es la correcta, y reimportá con la versión actual del servidor.

### Proceso devuelve error 400 al cargar

Algunos procesos tienen `json_data` vacío o corrupto en MySQL. Probar otro número de proceso o pedir corrección del dato en FacturIA.

## Más detalle técnico

- [iva-y-import-odoo.md](iva-y-import-odoo.md) — pipeline de import, modos IVA, regresiones conocidas
- [README.md](README.md) — índice para desarrolladores
- [api.md](api.md) — endpoints REST
