# Arquitectura del paquete `import_`

Decisiones de estructura y reglas para mantener el código legible sin cambiar comportamiento.

---

## Por qué un subpaquete y no un solo archivo

Antes todo vivía en `odoo/import_.py` (~1.817 líneas, ~70 funciones). Mezclaba:

- utilidades de parsing,
- agrupación de filas,
- lógica de OC,
- resolución de impuestos,
- planificación de writes,
- orquestación RPC,
- y el entrypoint `import_rows_to_odoo`.

El subpaquete separa **por etapa del pipeline** y por **tipo de operación** (planificar vs ejecutar vs RPC), alineado con cómo están documentados otros lados del repo (`modulos-frontend.md` por carpeta JS, `odoo/purchase_matching.py` aparte del import).

---

## Principios

1. **`__init__.py` solo reexporta** — no contiene lógica de negocio. Callers y tests siguen importando `facturia_matching.odoo.import_`.
2. **Planificar antes de escribir** — funciones `plan_*` devuelven listas de updates + warnings; `sync.py` y `taxes.py` aplican vía `_batch_write_move_lines`.
3. **Un write batch por concern cuando se puede** — contenido + `tax_ids` se fusionan en un solo batch; OC va aparte (puede fallar por FK); montos tax después de OC; precio/cantidad al final.
4. **Sin dependencias circulares** — orden de import entre submódulos es acíclico (ver grafo abajo).
5. **Paridad con documentación fiscal** — reglas de IVA/header/mixed viven en `core/comprobante_tax.py` y `padron/taxes.py`; `import_/taxes.py` solo traduce filas UI → Odoo.

---

## Grafo de dependencias entre submódulos

```
_utils.py          (sin deps internas)
    ↑
rows.py            (usa _utils, taxes._tax_ids_for_odoo_line)
    ↑
purchase.py        (usa _utils, rows; lazy import purchase_matching)
taxes.py           (usa _utils, core, padron; lazy import move_lines en apply)
    ↑
planning.py        (usa _utils, rows, purchase, taxes)
move_lines.py      (usa _utils, odoo.api)
    ↑
sync.py            (usa planning, purchase, taxes, move_lines)
    ↑
create.py          (usa rows, purchase, sync, odoo.api)
    ↑
__init__.py        (reexporta)
```

**Nota:** `taxes._apply_tax_line_amount_overwrites` importa `move_lines` dentro de la función para evitar ciclo `move_lines → taxes`.

---

## Convenciones de nombres

| Prefijo / patrón | Significado |
|------------------|-------------|
| `_normalize`, `_int_id`, … en `_utils.py` | Helpers privados compartidos |
| `plan_*` | Calcula diff entre filas UI y líneas Odoo; no llama RPC (salvo que el caller lo haga después) |
| `_build_line_command` | Tupla Odoo `(0, 0, vals)` para create; también fuente de vals esperados en updates |
| `_prepare_rows_for_import` | Pre-procesamiento **una vez** por request de import (OC + reconcile IVA) |
| `sync_move_taxes_from_group` | Post-create/post-duplicate: alinea un `move_id` con un grupo de filas |
| `group` | `List[Dict]` de filas de **un** comprobante (mismo `__comprobante_idx` o doc number) |

---

## Modelo de datos: fila UI

Cada fila es un `dict` con claves estilo export Odoo más metadata `__*`. El import asume que `propagate_invoice_headers` ya corrió dentro de `_prepare_rows_for_import`.

### Agrupación

| Clave | Uso |
|-------|-----|
| `__comprobante_idx` | Agrupa filas del mismo comprobante (preferido) |
| `l10n_latam_document_number` | Fallback de agrupación |
| `partner_id`, `journal_id`, `invoice_date` | Cabecera (primera fila o propagada) |
| `invoice_line_ids/name`, `…/price_unit`, `…/quantity`, `…/account_id` | Línea de producto |
| `__um_empresa_id` | UM matcheada → `product_uom_id` en Odoo |
| `__oc_line_id`, `__oc_name`, `__selected_oc_name` | Purchase matching |
| `iva_pct`, `iva_monto`, `__fac_iva_monto`, `__fac_iva_montos` | IVA (ver [impuestos.md](impuestos.md)) |
| `otros_impuestos`, `otros_impuestos_monto`, slots `_N` | Percepciones / IIBB |

### Línea con contenido

`_line_has_content`: tiene nombre, precio o cantidad parseable. Filas solo-encabezado pueden llevar `otros_impuestos` para IIBB a nivel comprobante.

---

## Interacción con perfiles Odoo

- `get_odoo_import_config()` / `get_odoo_uid_from_config()` respetan el perfil del request (`odoo/request_context.py`).
- Los **ids de `account.tax` no son portables** entre Dinner, Aliare y Sudata.
- `_move_line_supports_purchase_link` cachea por `base_url|db` si `account.move.line` expone `purchase_line_id` (Sudata sin purchase → false).

---

## Caching en memoria

| Cache | Módulo | Clave |
|-------|--------|-------|
| `_MOVE_LINE_PURCHASE_LINK_CACHE` | `_utils.py` | `base_url\|db` |

Invalidar en tests con `_MOVE_LINE_PURCHASE_LINK_CACHE.clear()` cuando se mockea `fields_get`.

---

## Extender el paquete

### Añadir un paso a `sync_move_taxes_from_group`

1. Si solo calcula diff → nueva `plan_*` en `planning.py` (o `taxes.py` si es solo impuestos).
2. Si escribe en Odoo → usar `_batch_write_move_lines` o `odoo_execute_kw_with_config` en `move_lines.py` / `taxes.py`.
3. Documentar orden respecto a OC y re-aplicación de precio (Odoo recalcula al vincular OC).
4. Añadir test en `tests/test_odoo_import.py`.
5. Actualizar [pipeline.md](pipeline.md).

### Exportar un símbolo nuevo a callers externos

1. Exportar desde el submódulo correspondiente.
2. Añadir a `__init__.py` y `__all__` si es API pública.
3. Documentar en [api-publica.md](api-publica.md).

---

## Relación con otros documentos

| Documento | Rol |
|---------|-----|
| [pipeline.md](pipeline.md) | Secuencia temporal detallada |
| [iva-y-import-odoo.md](../iva-y-import-odoo.md) | Dominio IVA, modos, regresiones frecuentes |
| [arquitectura.md](../arquitectura.md) | Capas globales del proyecto |
| [modulos-python.md](../modulos-python.md) | Índice de todo el backend Python |
