# Guía de usuario — FacturIA → Odoo

Guía práctica para operadores que cargan procesos, revisan el matching y envían facturas a Odoo.

## URL y perfil Odoo

| Tenant | Parámetros en la URL |
|--------|----------------------|
| **Dinner** (default) | `?empresa=1&proceso=123` |
| **Aliare** | `?empresa=1&proceso=123&odoo_profile_test=aliare` |
| **Sudata** (cloud) | `?empresa=1&proceso=123&odoo_cloud=1` o `odoo_profile_test=sudata` |

**Regla:** si trabajás contra Odoo Aliare, la URL **siempre** debe incluir `odoo_profile_test=aliare`. Sin eso, los impuestos se resuelven contra Dinner y los ids no coinciden con Odoo Aliare (el IVA del pie no se sobreescribe correctamente). El parámetro `odoo_profile` (sin `_test`) ya no tiene efecto.

Ejemplo dev Aliare:

```text
https://odoo-dev-….run.app/?empresa=1&proceso=48&odoo_profile_test=aliare
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
| **IVA 21 % / 10,5 % / …** | Montos de IVA por alícuota (editables en el pie en todos los modos) |
| **Otros impuestos** | IIBB, percepciones, etc. (editable) |
| **Total** | Base + IVA + otros (solo lectura) |

### Cuándo editar arriba vs abajo

| Modo | Dónde editar IVA | Pie IVA |
|------|------------------|---------|
| **line** | Columna **IVA monto** en cada fila **o** el pie | Editable (si editás abajo un monto distinto al de las líneas, el comprobante puede pasar a modo **header** y el pie manda) |
| **header** | Pie del comprobante | Editable |
| **mixed** | Depende de la fila; totales en el pie | Editable por alícuota |

Si editás el IVA en el **pie**, esos montos son los que se envían a Odoo al importar (no el cálculo automático por línea).

### IVA fijo y cambio de Precio

Si el **Monto IVA** de una línea ya está fijado (lo editaste vos o vino así de FacturIA y no es simplemente `precio × %`), al cambiar **Precio** o **Cantidad** el IVA del **pie no se recalcula**: se mantiene el monto fijo.

Ejemplo: base 344.760 con IVA 21 % = 72.399,60. Si cambiás el precio de la línea, el pie sigue mostrando 72.399,60 — no pasa a `nuevo precio × 21 %`.

En modo **line**, por defecto el monto autoritativo es la columna **IVA monto**. Si editás el IVA en el **pie** con un valor distinto al de las líneas, el modo puede pasar a **header**: la columna se oculta y el pie queda como fuente de verdad para el import. En modo **header**, el monto autoritativo es siempre el pie (`__fac_iva_monto`).

### Formato de números

La UI acepta formato argentino: `53.515,40`, `350.000,00`, etc. Al importar, el servidor interpreta esos formatos en el pie y en otros impuestos.

## Otros impuestos (IIBB / percepciones)

- Solo deberías ver **una columna** “Otros impuestos” en la tabla (más slots extra solo si hay montos reales en `otros_impuestos_2`, `_3`, …).
- Si ves muchas columnas vacías (legacy de versiones anteriores): **Restaurar original** y volver a guardar, o recargar el proceso tras un deploy nuevo.
- El monto de **Otros impuestos** en el pie se consolida en la primera línea de producto al importar (junto con los `tax_ids` de IIBB del padrón).
- El dropdown se arma **desde Odoo del perfil activo**: IIBB/percepciones conocidos + el resto de impuestos purchase del tenant (**incluidos los IVA**, p.ej. IVA 21 %, Perc Gananc). No es una lista fija incompleta.

## Solo encabezado

Con el tilde **Solo encabezado** en la primera fila del comprobante:

1. Si hay varias líneas, se colapsan a una sola (para deshacer: **Restaurar original**).
2. Aparece la columna calculada **Subtotal** (monto sin impuestos: `__fac_subtotal` o cantidad × precio).
3. Aparecen en la fila **Monto IVA** y **Monto Otros Impuestos** (editables; se copian desde el encabezado FacturIA si venían vacíos).
4. Se **oculta el pie** del comprobante (base / IVA / otros / total).

Sin el tilde, la tabla y el pie se comportan como siempre. La lista de **Otros impuestos** (con IVAs) no depende de este tilde.

## Import a Odoo — qué esperar

Al confirmar **Importar a Odoo**:

1. Se crean facturas en **borrador** (`in_invoice`) o se actualizan si ya existen (mismo proveedor + número de documento).
2. Se sincronizan líneas de producto, `tax_ids`, vínculos OC y **montos de impuesto** en las líneas `display_type=tax`.
3. Los montos del **pie** (IVA y otros) **sobreescriben** lo que Odoo calculó por línea — siempre **al final** del sync, después de vincular OC **y** de re-aplicar el precio de la tabla.
4. Si hay **Orden de Compra** vinculada, el **Precio** de la tabla (FacturIA o edición manual) se re-aplica en Odoo después del vínculo OC — no se usa el precio de la línea de compra. Luego se aplican los montos de impuesto del pie.
5. En el header de cada factura, **«Buscar OCs similares»** abre las OCs del proveedor. Luego queda «OC: {nombre} ▾»; si elegís no vincular, queda «OC: Sin OC ▾». Al cambiar proveedor, el botón se recalcula dinámicamente.
6. Opcional: con OC seleccionada, el checkbox **«Sobreescribir precio de la OC»** (texto arriba, tilde debajo) hace que al importar también se actualice el precio unitario en la orden de compra de Odoo. Sin OC, la tilde queda deshabilitada.

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
| `FACTURIA_ODOO_PROFILE` | Perfil por defecto en deploy si la URL no trae `odoo_profile_test` |

Ver `.env.example` para la lista completa.

## Problemas frecuentes

### El IVA en Odoo no coincide con el pie

| Causa | Qué hacer |
|-------|-----------|
| Falta `odoo_profile_test=aliare` en la URL | Agregar el parámetro y recargar |
| No se guardó la edición del pie | Editar de nuevo, esperar autosave, reimportar |
| Factura no está en borrador | Solo se actualizan facturas `draft` |
| Proceso con conversión vieja corrupta | **Restaurar original** y repetir ediciones |
| Elegiste Exento / No Gravado / No Corresponde pero Odoo sigue con IVA 21 % | Con la versión actual el pie se limpia solo; reimportá el borrador `draft`. Si el total en la UI aún incluye 21 %, recargá la página |

### El IVA del pie cambia al mover el Precio

Si el **Monto IVA** de la línea está fijo pero el **IVA %** del pie se recalcula al editar **Precio**, recargá la página con la versión actual del servidor. El pie debe respetar el monto fijo (columna IVA monto o valor de FacturIA), no `precio × alícuota`. Detalle técnico: [iva-y-import-odoo.md](iva-y-import-odoo.md#iva-fijo-al-cambiar-precio-o-cantidad).

### Muchas columnas “Otros impuestos” vacías

Versiones anteriores generaban una columna por cada impuesto del padrón. Tras actualizar: recargar proceso o restaurar original. Solo se muestran columnas con monto.

### Error “Valor numérico inválido”

Formatos híbridos raros (ej. `350.0,00`) ya se normalizan. Si persiste, reescribir el monto con formato AR estándar (`350.000,00`).

Si una cantidad tipo litros (`15,175`) o un precio (`1457,256`) aparece como `1` × `1,46`, recargá el proceso o usá **Restaurar original**: era un parseo que tomaba el punto de FacturIA como miles.

### Error de fecha límite en Odoo

```text
Cualquier apunte contable en una cuenta por pagar debe tener una fecha límite…
```

Completar **fecha de vencimiento** en FacturIA. El import propaga `invoice_date_due` y completa `date_maturity` en apuntes AP/AR. Si sigue fallando, revisar el tipo de cuenta del impuesto IIBB en Odoo.

### Percepción IIBB (CABA, ARBA, …) no coincide al primer import

| Causa | Qué hacer |
|-------|-----------|
| Falta `odoo_profile_test=aliare` en la URL | Agregar el parámetro y recargar |
| Deploy viejo (montos tax antes de re-aplicar precio) | Actualizar servidor y reimportar borrador `draft` |
| No hay línea tax en Odoo (sin etiqueta del impuesto) | Reimportar con versión actual; no debería borrarse el nombre del impuesto |
| Monto solo en pie, sin selección en columna Otros impuestos | Seleccionar el impuesto en la tabla o verificar `otros_impuestos_monto` en el pie |

### El precio en Odoo es el de la OC, no el de la factura

Tras importar con OC vinculada, Odoo puede mostrar el precio negociado en la orden de compra. El import debe restaurar el **Precio** de la tabla (FacturIA). Si ves el precio viejo de la OC: confirmá que el borrador está en `draft`, que la columna Precio en la UI es la correcta, y reimportá con la versión actual del servidor.

Si además necesitás que la **orden de compra** quede con el precio de la factura, marcá **«Sobreescribir precio de la OC»** en el header del comprobante e importá de nuevo. El texto está arriba y la tilde debajo; solo se habilita con una OC seleccionada.

Si elegís **Sin OC**, el selector no desaparece: queda **«OC: Sin OC ▾»** para poder abrirlo y elegir otra. Al cambiar proveedor, **«Buscar OCs similares»** aparece o desaparece según las OCs del nuevo proveedor.

### La OC no aparece en el selector

Solo se consideran órdenes de compra con **recepción iniciada** en Odoo (estado de entrega distinto de **No recibido**). Si la OC está confirmada pero aún no se registró ninguna recepción de mercadería, no aparecerá en el picker ni en el auto-match hasta que Odoo marque al menos una recepción parcial o total.

### Proceso devuelve error 400 al cargar

Algunos procesos tienen `json_data` vacío o corrupto en MySQL. Probar otro número de proceso o pedir corrección del dato en FacturIA.

## Más detalle técnico

- [iva-y-import-odoo.md](iva-y-import-odoo.md) — pipeline de import, modos IVA, regresiones conocidas
- [README.md](README.md) — índice para desarrolladores
- [api.md](api.md) — endpoints REST
