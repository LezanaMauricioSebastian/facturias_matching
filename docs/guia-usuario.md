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
2. Revisá el matching (proveedor, rubro, diario, cuenta, OC si aplica). El **diario inicial** viene del padrón (puede no coincidir con Riccollini; ej. Salta Refrescos). Si lo corregís y esperás autosave, **F5 ya no lo revierte**. Además, la **próxima factura del mismo proveedor** (otro proceso) reusa el último diario/cuenta/rubro que guardaste en una conversión de esa empresa — no hace falta corregirlo otra vez.
3. Editá lo necesario en la tabla o en el **pie del comprobante** (IVA, otros impuestos).
4. Esperá el autosave (o guardá explícitamente si la UI lo indica).
5. **Importar a Odoo** — crea o actualiza borradores y sincroniza impuestos + OC.

## Pie del comprobante (IVA y otros impuestos)

Cada factura tiene un bloque expandible con:

| Campo | Qué es |
|-------|--------|
| **Base imponible** | Subtotal FacturIA (`__fac_subtotal`) en modos header/mixed; suma de líneas en modo line (solo lectura) |
| **IVA 21 % / 10,5 % / …** | Montos de IVA por alícuota (editables en el pie en todos los modos) |
| **Otros impuestos** | IIBB, percepciones, etc. (editable) |
| **Total** (pie) | Base + IVA + otros (solo lectura) |

### Cuándo editar arriba vs abajo

| Modo | Dónde editar IVA | Pie IVA |
|------|------------------|---------|
| **line** / **header** / **mixed** | Solo el **pie** (montos). En la tabla queda **IVA** (%) | Editable |

Los montos de IVA y de otros impuestos **no** se editan en columnas de la tabla (mismo criterio que Odoo: impuestos en la línea, importes abajo). Si hay varias líneas con la misma alícuota, el pie muestra la suma / el encabezado FacturIA.

Si corregís **IVA** en la línea (p. ej. FacturIA leyó 21 % y era 10,5 %), el pie cambia de etiqueta y **conserva el monto**: no quedan las dos alícuotas y a Odoo va la nueva. Si el monto también estaba mal, editalo en el pie.

Si editás el IVA en el **pie**, esos montos son los que se envían a Odoo al importar (no el cálculo automático por línea cuando marcás override).

### IVA fijo y cambio de Precio

Si el IVA del **pie** ya está fijado (editaste el pie o vino de FacturIA y no es simplemente `precio × %`), al cambiar **Precio** o **Cantidad** el pie **no se recalcula** solo: se mantiene el monto fijo cuando hay override / header.

En modo **line** sin override de pie, al cambiar precio/cantidad se puede realinear el pie desde las líneas (`syncFacIvaMontosFromLines`).

### Formato de números

La UI acepta formato argentino: `53.515,40`, `350.000,00`, etc. Al importar, el servidor interpreta esos formatos en el pie y en otros impuestos.

## Otros impuestos (IIBB / percepciones)

- En la tabla ves el **dropdown** “Otros impuestos” (y slots extra con +). Los **montos** se editan en el **pie**, no en columnas de monto.
- El **pie** desglosa otros impuestos **como trae FacturIA** (labels: **IIBB** / **Percepción IVA** / **Impuesto Interno** + montos) mientras no hayas elegido impuesto en las líneas. El campo FacturIA `otros_tributos` se muestra como **Impuesto Interno** (no como “Otros tributos”).
  - En las **líneas**, el usuario asigna los impuestos Odoo a mano (col 2/3 solo si esa línea tiene más de uno con el +).
  - Cuando asignás un impuesto Odoo **del mismo tipo** que el monto FacturIA de ese slot, el pie **pasa a mostrar ese nombre Odoo** (y el monto). Elegir **Impuesto Interno** en la 1ª línea no pisa la fila **IIBB** del pie ni duplica Interno.
  - Si agregás columnas con **+** **o** elegís un impuesto extra en otra línea (p.ej. IVA Adicional 20%) y todavía no hay monto, el pie **igual muestra esa fila** (monto vacío) para que lo cargues ahí.
  - Si FacturIA trajo montos y en las líneas no cubrís todos (p.ej. falta Impuesto Interno), el pie muestra un **aviso**: «No asignaste en las líneas todos los impuestos de la factura…».
- Al editar un monto del pie, se **reparte** entre las filas que tienen ese impuesto asignado (proporcional a cantidad × precio). Si nadie lo tiene, el monto queda guardado en la primera fila para el pie, pero la columna **Total** de la línea **solo suma** los “otros” cuyo impuesto está **asignado en esa fila**.
- Los montos (repartidos en las filas) al importar pisan las líneas tax de Odoo (junto con los `tax_ids` de IIBB del padrón).
- El dropdown se arma **desde Odoo del perfil activo**: **todos** los impuestos del tenant (orden alfabético).

## Solo encabezado / 1 línea

- Si un comprobante tiene **1 sola línea**, se trata como **Encabezado**: **sin pie** (no se muestra Base imponible / IVA / Total abajo). Los montos de IVA y otros van **en la fila**.
- Si tiene **varias líneas**, el **pie** queda visible (montos ahí, como Odoo).
- Un **proceso puede mezclar** comprobantes de Encabezado (1 línea) y con varias líneas. En **Lista**, si hay **≥2** comprobantes y **todos** son de 1 línea, la vista unificada (una sola tabla) se aplica **sola** — ya no hay tilde «Vista unificada».
- El tilde global **Solo encabezado** (barra superior del proceso) colapsa **todas** las facturas multi-línea a una (precio = subtotal FacturIA; IVA y otros del encabezado van a la fila). **Destildar** restaura las líneas originales de cada comprobante; **Restaurar original** sigue siendo el reset completo del proceso. Al quedar 1 línea se oculta el pie (y, con ≥2 facturas, entra la vista unificada). Ya no hay tilde por factura.

La columna **Subtotal** (cantidad × precio, sin impuestos) está **siempre** visible, justo antes de **Total**.

## Import a Odoo — qué esperar

Al confirmar **Importar a Odoo**:

1. Se crean comprobantes en **borrador**: factura (`in_invoice`) o **nota de crédito** (`in_refund`) según el **Tipo de Documento**, o se actualizan si ya existen (mismo proveedor + número).
2. Se sincronizan líneas de producto, `tax_ids`, vínculos OC y **montos de impuesto** en las líneas `display_type=tax`.
3. Los montos del **pie** (IVA y otros) **sobreescriben** lo que Odoo calculó por línea — siempre **al final** del sync, después de vincular OC **y** de re-aplicar el precio de la tabla.
4. Si hay **Orden de Compra** vinculada, el **Precio** de la tabla (FacturIA o edición manual) se re-aplica en Odoo después del vínculo OC — no se usa el precio de la línea de compra. Luego se aplican los montos de impuesto del pie.
5. En el header de cada factura, **«Buscar OCs similares»** abre las OCs del proveedor. Luego queda «OC: {nombre} ▾»; si elegís no vincular, queda «OC: Sin OC ▾». Al cambiar proveedor, el botón se recalcula dinámicamente.
6. Con producto asignado, la columna **UM** permite elegir otra unidad de la misma categoría del producto (p. ej. Unidades ↔ pack). Al cambiarla se re-escala la cantidad; al importar se envía esa UM a Odoo.
7. Opcional: con OC seleccionada, el checkbox **«Sobreescribir precio de la OC»** (texto arriba, tilde debajo) hace que al importar también se actualice el precio unitario en la orden de compra de Odoo. Sin OC seleccionada, la tilde queda deshabilitada; si el proveedor no tiene OCs, el checkbox no se muestra.

Si el import dice “Actualizadas en Odoo” con “X impuestos”, los montos del pie se aplicaron. Si los montos en Odoo siguen siendo los calculados, revisá la sección [Problemas frecuentes](#problemas-frecuentes).

## Aliare vs Dinner vs Sudata — ids de impuesto

Los **números de id** de `account.tax` no son iguales entre tenants:

| Alícuota | Dinner | Aliare | Sudata |
|----------|--------|--------|--------|
| 21 %     | 63     | 65     | 65     |
| 10,5 %   | 61     | 63     | 63     |
| 27 %     | 65     | 67     | 67     |

No hace falta memorizarlos: la app los resuelve sola **si el perfil en la URL es correcto**.

Sudata no tiene instalado el español de Argentina (`es_AR`) sino el latinoamericano (`es_419`), así que la app pide ese idioma y los impuestos se ven como en Odoo (`IVA 21%`, `Perc IVA`). `Internal taxes` es la excepción: en Odoo no tiene traducción cargada, y el desplegable lo muestra como **Impuestos internos**.

## Variables de entorno relevantes (operaciones / deploy)

| Variable | Uso |
|----------|-----|
| `ODOO_BASE_URL_ALIARE`, `ODOO_USER_ALIARE`, `ODOO_API_KEY_ALIARE` | Credenciales import Aliare |
| `ODOO_BASE_URL_SUDATA`, `ODOO_USER_SUDATA`, `ODOO_API_KEY_SUDATA` / `ODOO_PASSWORD_SUDATA` | Credenciales Odoo Cloud Sudata (`?odoo_cloud=1`). En Cloud Run las públicas van como env; password/API key en Secret Manager |
| `PADRON_TAX_SOURCE_PROFILE` | Tenant del que vienen los ids del padrón Postgres (default `default` = Dinner); se remapean al perfil activo |
| `ODOO_LANG`, `ODOO_LANG_ALIARE`, `ODOO_LANG_SUDATA` | Fuerzan el idioma RPC. Sin setear, la app usa el primer idioma instalado en el tenant: `es_AR` y si no `es_419` |
| `FACTURIA_ODOO_PROFILE` | Perfil por defecto en deploy si la URL no trae `odoo_profile_test` |
| `PROCESS_SCHEMA` | Schema MySQL (`sudataco_staging` / `sudataco_facturia`) para process, conversiones, `product_label_memory` y memoria de diario/cuenta/rubro (desde conversiones) |
| `FACTURIA_UI_ENV` | Opcional: `dev` fuerza pestaña FacturIA; `prod` la oculta. Sin setear, se infiere si `PROCESS_SCHEMA` contiene `staging` |
| `FACTURIA_BASE_URL` | Base FacturIA para el webhook erp-imports (default staging/prod según `PROCESS_SCHEMA`) |
| `FACTURIA_ERP_WEBHOOK_URL` | Override de la URL completa `POST …/api/erp-imports/webhook` |
| `FACTURIA_FILE_URL_TEMPLATE` | Plantilla para proxy de PDF/foto original (`GET /api/proceso/{n}/archivo`). Sin setear, el botón **Ver factura** muestra error |

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
| Mandás IVA 21 y en Odoo llega **IVA 10,5 %** (Sudata) | Bug corregido: el catálogo de Sudata está en inglés y la app caía a los ids de Dinner. Con el deploy actual, reimportar el borrador `draft` reemplaza el impuesto. Detalle: [iva-y-import-odoo.md](iva-y-import-odoo.md#iva-21--llega-como-iva-105--en-sudata-nombres-en) |

### El IVA del pie cambia al mover el Precio

Si el **Monto IVA** de la línea está fijo pero el **IVA %** del pie se recalcula al editar **Precio**, recargá la página con la versión actual del servidor. El pie debe respetar el monto fijo (columna IVA monto o valor de FacturIA), no `precio × alícuota`. Detalle técnico: [iva-y-import-odoo.md](iva-y-import-odoo.md#iva-fijo-al-cambiar-precio-o-cantidad).

### Muchas columnas “Otros impuestos” vacías

Versiones anteriores generaban una columna por cada impuesto del padrón. Tras actualizar: recargar proceso o restaurar original. Solo se muestran columnas con monto.

### Error “Valor numérico inválido”

Formatos híbridos raros (ej. `350.0,00`) ya se normalizan. Si persiste, reescribir el monto con formato AR estándar (`350.000,00`).

Si una cantidad tipo litros (`15,175`) o un precio (`1457,256`) aparece como `1` × `1,46`, recargá el proceso o usá **Restaurar original**: era un parseo que tomaba el punto de FacturIA como miles.

### Error “No puedes utilizar el tipo de documento credit_note en una factura”

Odoo no permite un tipo **nota de crédito** sobre un `account.move` de factura. Con la versión actual, si el tipo es NC (p. ej. **NOTAS DE CRÉDITO A**), el import crea `in_refund` (sección de notas de crédito en Odoo), no `in_invoice`. Reimportá el borrador. Si el error sigue, recargá la UI y confirmá que el tipo de documento quedó en NC.

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
| IIBB en Odoo Dinner = IIBB+Perc IVA del pie; Perc IVA e Interno quedan en el % de la línea | Varias líneas, cada impuesto en una distinta (no es falta de `odoo_profile`): reimportar el borrador `draft` |
| Pie sin IIBB y dos filas Impuesto Interno; Odoo Interno = IIBB+Interno | Elegiste Interno en la 1ª línea: recargá / reimportá el `draft` (el pie no debe pisar IIBB) |

### El precio en Odoo es el de la OC, no el de la factura

Tras importar con OC vinculada, Odoo puede mostrar el precio negociado en la orden de compra. El import debe restaurar el **Precio** de la tabla (FacturIA). Si ves el precio viejo de la OC: confirmá que el borrador está en `draft`, que la columna Precio en la UI es la correcta, y reimportá con la versión actual del servidor.

Si además necesitás que la **orden de compra** quede con el precio de la factura, marcá **«Sobreescribir precio de la OC»** en el header del comprobante e importá de nuevo. El texto está arriba y la tilde debajo; solo aparece si el proveedor tiene OCs y solo se habilita con una OC seleccionada.

Si elegís **Sin OC**, el selector no desaparece: queda **«OC: Sin OC ▾»** para poder abrirlo y elegir otra. Al cambiar proveedor, **«Buscar OCs similares»** y el checkbox **«Sobreescribir precio de la OC»** aparecen o desaparecen según las OCs del nuevo proveedor.

### La OC no aparece en el selector

Se listan **todas** las órdenes de compra **confirmadas** del proveedor (`purchase` / `done`), incluidas las ya recepcionadas y las aún sin recepción. El ranking prioriza el **% de matching** (Score de la tarjeta) y, a igualdad de %, coincidencia de **referencia de pedido** (`partner_ref` ↔ referencia FacturIA, p. ej. `PEDIDO 26.05`); no oculta OCs. Por defecto el modal filtra **Desde** ene-2026 (editable / vaciable). Si ya sabés cuál es, usá también el **buscador** (nombre, ref. proveedor, producto). Si no ves la OC correcta: verificá el filtro de fecha, que el proveedor de la factura sea el mismo partner comercial en Odoo y que la OC no esté en borrador o cancelada. Tras **Buscar OCs similares**, hay que **elegir** la OC en el modal (no se auto-selecciona).

### Proveedor con id que Odoo rechaza (`res.partner(…)` no existe)

El desplegable **solo** lista contactos del Odoo del perfil activo (`odoo_profile_test` / `odoo_cloud`). Si la conversión guardó un `partner_id` de otro tenant (Dinner vs Sudata), al recargar se **limpia** y hay que elegir el proveedor correcto del catálogo (o crearlo en ese Odoo). No uses ids viejos aunque el nombre se vea familiar.

### En Sudata no aparecen productos (ni UM) en los desplegables

Bug corregido. Sudata corre **Odoo 19**, que eliminó campos que la app pedía (`uom_po_id` en productos, `category_id` / `uom_type` en unidades de medida). Odoo no ignora un campo inexistente: rechaza la consulta entera, así que el catálogo de productos volvía **vacío** y el de UM también. Con el deploy actual ambos cargan y la columna **UM** vuelve a re-escalar cantidades (kg ↔ g, unidades ↔ packs). Detalle: [purchase-oc.md](import-odoo/purchase-oc.md#um-en-odoo-19-sudata).

### Proceso devuelve error 400 al cargar

Algunos procesos tienen `json_data` vacío o corrupto en MySQL. Probar otro número de proceso o pedir corrección del dato en FacturIA.

## Más detalle técnico

- [iva-y-import-odoo.md](iva-y-import-odoo.md) — pipeline de import, modos IVA, regresiones conocidas
- [README.md](README.md) — índice para desarrolladores
- [api.md](api.md) — endpoints REST
