# Purchase orders (OC) en el import

Vínculo entre filas UI y `purchase.order.line` en Odoo (`purchase_line_id`).

**Código:** `purchase.py`, `planning._po_link_write_vals`, `planning.plan_product_price_quantity_reapply`

**Matching previo (enriquecer filas):** `odoo/purchase_matching.py`

---

## Filtro de OCs en matching

`fetch_partner_po_lines` (`purchase_matching.py`) trae órdenes de compra **confirmadas** del proveedor, **incluyendo recepcionadas y no recepcionadas**.

| Odoo (`purchase.order`) | UI (español) | ¿Se considera? |
|-------------------------|--------------|----------------|
| `receipt_status = pending` | Estado de entrega **No recibido** | Sí (label «No recepcionada») |
| `receipt_status = partial` | Parcialmente recibido | Sí («Parcialmente recepcionada») |
| `receipt_status = full` | Recibido | Sí («Recepcionada») |
| `receipt_status = False` | Sin recepciones / sin stock | Sí |

Dominio en `_partner_po_search_domain`:

```python
[
    ("partner_id", "child_of", scope_id),
    ("state", "in", ["purchase", "done"]),
]
```

**UI final (por comprobante):** los controles viven en una franja del **header de cada tarjeta de factura**, encima de la tabla.

- A la izquierda se muestra un botón `secondary` **«Buscar OCs similares»**. Después de buscar pasa a **«OC: {nombre} ▾»**; si se elige no vincular, queda **«OC: Sin OC ▾»** (sin anteponer el número de factura). `↻` fuerza una búsqueda nueva.
- A la derecha está el checkbox **«Sobreescribir precio de la OC»**: el texto aparece arriba y la tilde debajo. Se muestra deshabilitado mientras no haya una OC seleccionada.
- El botón y el checkbox aparecen juntos cuando el comprobante tiene proveedor y todavía no se confirmó que no tenga OCs. Tras `rematch-purchase`, se ocultan ambos si Odoo confirmó `oc_provider_has_ocs_by_comprobante[comp]=false`; si el nuevo proveedor tiene OCs, aparecen dinámicamente.
- Al abrir el selector sin candidatos en memoria, el frontend vuelve a ejecutar `search-oc` antes de abrir el modal.

Si el operador elige **«Sin OC»**, se limpian los vínculos de líneas y el checkbox queda deshabilitado, pero se conservan candidatos / flags de búsqueda: el selector queda como **«OC: Sin OC ▾»** y no desaparece.

**Carga inicial:** `enrich_rows_with_purchase_data(..., fetch_candidates=False)` no lista candidatos ni auto-elige la mejor OC; solo re-aplica una OC guardada válida (`__selected_oc_order_id` / `__selected_oc_name` en las filas de la conversión). Si hay selección válida, también marca `oc_searched_by_comprobante` para que el header muestre **«OC: {nombre} ▾»** tras reload (no el CTA «Buscar OCs similares»). Mismo criterio en facturas **solo encabezado**. Las columnas UM/OC (`show_purchase_columns`) se muestran si hay candidatos **o** si las filas ya tienen match/UM guardados (`compute_show_purchase_columns`) — sin eso, tras F5 la pastilla OC volvía pero la columna **UM** desaparecía.

**Efecto histórico (cambio):** antes se excluían OCs `receipt_status=pending`; ahora se listan con label para que el operador decida.

---

## Sugerencia de producto por fuzzy (sin vincular OC)

Diagrama de decisión (OC → memoria → fuzzy): [docs/README.md § Matching de producto](../README.md#matching-de-producto-oc--memoria--fuzzy).

No todas las líneas de factura terminan vinculadas a una línea de OC (proveedor sin OC seleccionada, o línea que no matchea la OC elegida). Para esos casos se **sugiere** el `invoice_line_ids/product_id` haciendo fuzzy de la etiqueta contra los **productos de las OC del proveedor** (`fetch_partner_po_lines`, ya en memoria: sin llamadas extra a Odoo).

**Código:** `_suggest_product_from_pool` + rama "sin match OC" de `match_invoice_row(..., suggest_pool=po_lines)`; `_match_comprobante_rows` pasa las líneas de todo el proveedor como `suggest_pool`.

**Cuándo aplica** (solo si la línea quedó sin producto propio):

- Comprobante **con OC** seleccionada pero la línea **no matcheó** ninguna línea de esa OC.
- Comprobante **sin OC** seleccionada pero el **proveedor sí tiene OCs**.

**Reglas:**

- Umbral igual al de OC (`_min_match_score`: 70 con código de ítem, 75 sin código).
- **No** setea `__oc_line_id` ni `__oc_order_id` (no vincula OC, solo sugiere producto).
- Setea `__product_suggested` (score) y `__oc_match_note = "Producto sugerido (fuzzy N%)"`.
- Si la fila ya trae `invoice_line_ids/product_id`, se respeta (no se sugiere encima).
- **No** re-escala cantidad al sugerir (solo stamp de UM): UM factura ambigua (`KG` / `UNID/KG`) + `uom_po` en packs de peso inventaba qtys (p. ej. Sal fina 20 → 0,32). El re-escalado sigue en match OC y en `rematch-uom` manual.
- Rechaza falsos positivos por modificadores incompatibles (p. ej. **TOMATE SECO** ≠ **TOMATE TRITURADO**): no alcanza un solo token de género.
- Hongos / Pasas / productos nunca comprados al proveedor quedan vacíos: la sugerencia solo busca en el pool de OCs del partner, no en todo el catálogo. **Limitación conocida** (mitigada en parte por [aprendizaje](#aprendizaje-de-producto-procesos-pasados)).

**UI:** la celda de producto sugerida se muestra **resaltada en naranja** (`combobox-suggested`) con tooltip de revisión. Al elegir/borrar el producto manualmente se limpia el flag; al elegir producto se llama `rematch-uom` para inferir UM (`combobox/attach.js` + `purchase.js`).

Tests: `test_match_invoice_row_suggests_product_from_pool_without_oc`, `test_match_invoice_row_no_suggestion_below_threshold`, `test_line_match_score_rejects_tomate_seco_vs_triturado`, `test_suggest_product_does_not_rescale_pack_qty_as_kg` en `tests/test_purchase_matching.py`.

## Aprendizaje de producto (procesos pasados)

Cuando el operador ya eligió un producto de Odoo para una etiqueta de factura (p. ej. `SPRITE` → `GASEOSAS`) en un proceso anterior del **mismo proveedor**, el matching vuelve a sugerir ese producto aunque no esté en las OCs recientes.

**Código:** `persistence/product_label_memory.py` + `match_invoice_row(..., learned_product_id=…)` vía `_match_comprobante_rows` / `enrich_rows_with_purchase_data(..., company_id=…)`. Escritura en `save_conversion`.

**Prioridad (sin producto previo en la fila):**

1. Match de línea OC (sigue ganando).
2. **Memoria** — último `invoice_line_ids/product_id` confirmado para el mismo `partner_id` + etiqueta normalizada (`invoice_line_ids/name`), scoped por `company_id` + `template_id` (perfil Odoo).
3. Fuzzy contra productos de las OCs del proveedor.

**Señales “confirmadas”:** filas con producto y **sin** `__product_suggested` (elección manual o match OC; no se aprende de fuzzy/memoria sin revisar).

**Tabla `product_label_memory`** (MySQL, schema = `PROCESS_SCHEMA`):

| Entorno | Schema |
|---------|--------|
| Staging / `odoo-dev` | `sudataco_staging` |
| Prod / `matching-ui-odoo` | `sudataco_facturia` |

Clave única: `(company_id, template_id, partner_id, label_key)`. La app crea la tabla con `CREATE TABLE IF NOT EXISTS` al primer uso; SQL de referencia en `scripts/sql/product_label_memory.sql`. Staging y prod **no comparten** filas (schemas distintos).

**Flujo:**

1. Al **guardar** conversión → `upsert_product_memory_choices` (solo elecciones confirmadas).
2. Al **cargar** proceso → `build_memory_index_for_company` lee la tabla. Si está vacía para esa empresa/perfil, hace seed lazy desde las últimas ~100 conversiones y persiste.
3. Setea `__product_suggested=memory` y nota `Producto aprendido (proceso pasado)`; misma UI naranja que fuzzy. No re-escala qty.

**Limitaciones:** etiqueta exacta (tras normalizar mayúsculas/espacios); sin match fuzzy de labels (`SPRITE` ≠ `SPRITE 2L`); rematch bajo demanda sin `company_id` no consulta memoria todavía. Si una línea OC queda descartada por “ya asignada a otra fila”, se reintenta memoria/fuzzy.

Tests: `test_product_label_memory_*`, `test_match_invoice_row_prefers_learned_over_fuzzy`, `test_match_invoice_row_oc_beats_learned` en `tests/test_product_label_memory.py`.

### Unidad de medida — envase en descripción

La descripción suele traer el **tamaño del envase** (`X 500 G`, `X 2 KG`), no la UM facturada. `_resolve_invoice_qty_um` **no** copia esa UM del texto cuando ya hay cantidad de línea o `__fac_item_cantidad` (evita tratar packs como gramos/kilos).

Tests: `test_resolve_invoice_qty_ignores_package_um_when_qty_present`, `test_resolve_invoice_qty_prefers_facturia_over_package_size`.

Tests: `test_partner_po_search_domain_includes_all_receipt_statuses`, `test_fetch_partner_po_lines_includes_receipt_and_deliver_fields`, `test_search_oc_candidates_for_comprobante`, `test_enrich_restores_saved_oc_and_marks_searched`, `test_enrich_restores_saved_oc_on_solo_encabezado`, `test_apply_oc_selection_sin_oc_clears_match` en `tests/test_purchase_matching.py`.

---

## Campos en filas UI

| Campo | Origen | Uso en import |
|-------|--------|----------------|
| `__oc_line_id` | `purchase_matching` / selección UI | `purchase_line_id` en Odoo |
| `__oc_name` | Nombre PO | `invoice_origin`, warnings |
| `__oc_order_id` | Id orden | Metadata |
| `__selected_oc_name` | Picker UI | Prioridad en `invoice_origin`; label del header tras reload |
| `__selected_oc_order_id` | Picker UI / `select-oc` | Persiste en la conversión; re-aplicada al cargar el proceso |
| `invoice_line_ids/product_id` | FacturIA / OC / **sugerencia fuzzy** / **aprendizaje** | Producto al vincular OC, sugerido desde OCs del proveedor, o última elección confirmada del mismo proveedor+etiqueta |
| `__product_suggested` | `match_invoice_row` (fuzzy o memory) | Marca producto sugerido (no confirmado); resalte naranja en UI (`memory` o score fuzzy) |
| `__overwrite_oc_price` | Checkbox UI por comprobante | Si truthy (`1`/`true`), al importar escribe `price_unit` en `purchase.order.line` |
| `__um_empresa` / `__um_empresa_id` | UM del producto (default `uom_po_id`; editable en UI). Columna **UM** | `product_uom_id` en la línea de factura al importar |
| `__um_proveedor`, `__qty_escalada`, `__um_note` | UM cruda FacturIA + escalado (interno; `__um_proveedor` no se muestra) | Matching / debug; qty re-escrita en `invoice_line_ids/quantity` si hubo re-escalado |

El **precio** y la **cantidad** de la **factura** vienen de `invoice_line_ids/price_unit` y `invoice_line_ids/quantity` — no del precio de la PO. El matching OC no pisa precio (solo producto, metadata y UM).

### Sobreescribir precio de la OC original

Por defecto el import **no** modifica la orden de compra en Odoo: solo deja el precio de FacturIA en la factura (vía reapply).

Si el operador marca el checkbox **«Sobreescribir precio de la OC»** en el header del comprobante:

1. Se persiste `__overwrite_oc_price=1` en las filas del comprobante (autosave).
2. Tras vincular OC y re-aplicar precio en la factura, `apply_purchase_order_price_overwrites` escribe `price_unit` en cada `purchase.order.line` vinculada (`__oc_line_id`), con el precio de la tabla UI.
3. Solo escribe si difiere (tolerancia 0.001). Errores de Odoo → warning, no abortan el import.
4. Al deseleccionar OC / rematch, el flag se limpia con el resto de campos purchase.

**UI:** controles OC + checkbox viven en el **header de cada tarjeta de factura** (la barra global quedó legacy/oculta). Solo se renderizan si el proveedor tiene (o puede tener) OCs; si Odoo confirma que no tiene, no se muestran. Con OCs visibles pero sin OC seleccionada, el checkbox queda deshabilitado. Su etiqueta está arriba y la tilde debajo.

Tests: `test_apply_purchase_order_price_overwrites_*`, `test_group_wants_overwrite_oc_price`.

### Unidad de medida (UM)

Flujo:

1. Detectar / asignar `invoice_line_ids/product_id` (OC, fuzzy o manual).
2. Resolver la UM de la factura contra las UOMs de la **categoría del producto** (`uom.uom` con mismo `category_id` que `uom_po_id` / `uom_id` del producto). La UM **inferida** por defecto (`__um_empresa`) es el default de compra del producto (`uom_po_id`, p.ej. `pack (12 unidades)`), **no** la UM de la línea OC (esa puede ser `Unidades` aunque el producto compre en packs). Sin `uom_ids` por producto en Dinner: la “lista” = UOMs de esa categoría (incluye custom).
3. Si hace falta, re-escalar `invoice_line_ids/quantity` a la UM destino y guardar `__um_empresa_id`.
4. Al importar, `_build_line_command` / sync escriben `product_uom_id` en `account.move.line` (create, contenido, vínculo OC y reapply final). El vínculo OC (`purchase_line_id`) es independiente de la UM elegida.

**UI — selector de UM:** la columna **UM** es un `<select>` por fila. Opciones = `list_uoms_for_product` (misma categoría). Sin producto, el select queda vacío y deshabilitado. Al cambiar producto, `POST .../rematch-uom` infiere el default y cachea las opciones (`state.uomOptionsByProductId`). Al elegir otra UM, el mismo endpoint con `uom_id` re-escala desde `__qty_original` / `__um_proveedor`. Si la fila ya tenía producto guardado, al enfocar el select se llama `GET .../product-uoms` (solo lista, sin mutar).

**Resolve category-aware:** `_apply_uom_scaling` matchea la UM de FacturIA (`KG`, `LT`, …) **dentro de la categoría del destino** (`_find_uom_in_category`), no solo por `by_name` global. El catálogo indexa colisiones de nombre como listas (`by_name[key] = […]`): en Dinner hay dos `kg` (Peso vs Conversión Crema) y dos `L` (Volumen vs LITROS); sin filtro por categoría el alias global elegía la categoría equivocada y fallaba con `Categoría UM distinta`.

**No se escribe** `product_uom_id` cuando:

- El mapeo falló (`UM sin mapeo` / `Categoría UM distinta`): la cantidad sigue en la UM de factura y Odoo usa el default del producto.
- La fila **no tiene** `invoice_line_ids/product_id` (ej. el usuario borró el producto tras el matching): una UM huérfana podría violar la restricción de categoría UOM de Odoo. La UI limpia `__um_empresa_*` al borrar el producto.
- Al **elegir producto a mano**, `POST .../rematch-uom` recalcula la UM con `uom_po_id` del producto (mismo paso 2 que el matching automático) y re-escala cantidad si aplica. Un `uom_id` fuera de la categoría del producto se ignora y se usa el default.

**Caches por tenant:** `_po_cache`, `_product_uom_cache` y `_uom_cache` se indexan por `base_url|db` — los ids de `uom.uom` / `product.product` no son portables entre perfiles Odoo (Dinner/Aliare/Sudata). `clear_purchase_cache()` limpia todo.

Tests: `test_apply_uom_scaling_sets_empresa_id`, `test_apply_uom_scaling_kg_collision_uses_target_category`, `test_apply_uom_scaling_oc_custom_pack_from_kg_invoice`, `test_apply_uom_scaling_lt_collision_uses_volume_category`, `test_match_invoice_row_oc_uses_product_purchase_uom_not_po_line`, `test_build_line_command_includes_matched_product_uom`, `test_plan_product_line_content_updates_product_uom`, `test_plan_product_price_quantity_reapply_restores_uom`, `test_uom_not_written_without_product`, `test_list_uoms_for_product_same_category`, `test_apply_product_uom_to_row_explicit_uom_id_rescales`, `test_apply_product_uom_to_row_rejects_out_of_category_uom`.

---

## Soporte por tenant

`_move_line_supports_purchase_link` (`_utils.py`):

- Hace `fields_get` en `account.move.line` una vez por `base_url|db`
- Si no existe `purchase_line_id` → todo el flujo OC se omite (ej. Odoo Cloud Sudata sin módulo purchase)

Cache: `_MOVE_LINE_PURCHASE_LINK_CACHE` — limpiar en tests.

---

## `_prepare_rows_for_import` — fase OC

### ¿Cuándo refresh?

`_should_refresh_purchase_links` → true si alguna fila con contenido tiene nombre OC pero **no** tiene `__oc_line_id`.

Evita round-trip innecesario cuando el cliente ya envió ids.

### Refresh

`_refresh_purchase_links`:

```python
clear_purchase_cache()
enrich_rows_with_purchase_data(rows)
```

Warning si `rows_matched < rows_total`.

### Sanitize

`sanitize_group_purchase_lines` — para cada `__oc_line_id`, verifica existencia en `purchase.order.line.search`. Si no existe:

- Limpia `__oc_line_id`, `__oc_line_name`, `__oc_order_id`
- Warning con nombre de línea y OC

Si hubo sanitize → **segundo** refresh + re-agrupación.

### Dedupe

`_dedupe_group_oc_line_ids` — Odoo no permite dos líneas de factura con el mismo `purchase_line_id`. La segunda fila pierde el vínculo + warning.

---

## En `sync_move_taxes_from_group`

### Plan

`plan_purchase_line_updates(product_lines, group, config=config)`:

- Empareja por **orden** (primera línea UI ↔ primera línea Odoo, etc.)
- Solo propone cambio si `expected __oc_line_id != current purchase_line_id`
- **No** propone quitar vínculo (`purchase_line_id=False`) — Odoo puede fallar con FK

### Write

`_po_link_write_vals` por línea:

```python
{
  "purchase_line_id": po_line_id,
  "price_unit": ...,      # desde UI
  "quantity": ...,        # desde UI
  "product_id": ...,      # si hay en fila
  "product_uom_id": ...,  # si hay `__um_empresa_id` matcheada
}
```

`_batch_write_move_lines_with_fallback` — si el batch falla, reintenta línea a línea (errores comunes en OC).

### Después del vínculo

1. `plan_product_price_quantity_reapply` — restaura precio/cantidad/UM UI (Odoo puede haber puesto el precio/UM de la PO)
2. `apply_purchase_order_price_overwrites` — **opcional** (`__overwrite_oc_price`): pisa `price_unit` en la OC original
3. `_apply_tax_line_amount_overwrites` — **último paso** sobre la factura: pisa montos IVA / IIBB del pie de FacturIA

**Regresión corregida (IIBB CABA):** si los montos tax se aplicaban antes del reapply de precio, Odoo recalculaba la percepción y el primer import quedaba mal; el segundo clic “arreglaba” porque el precio ya no cambiaba.

---

## `plan_product_price_quantity_reapply`

Último paso del sync de líneas de producto (si purchase soportado).

- Empareja por `purchase_line_id` si la fila UI tiene `__oc_line_id`
- Fallback por índice en filas con contenido
- Evita usar la misma línea Odoo dos veces (`used_line_ids`)
- Solo escribe `price_unit`, `quantity` y `product_uom_id` si difieren (tolerancia 0.001 en montos)

**Regresión histórica:** sin este paso, Odoo dejaba el precio de la línea PO tras vincular.

Tests:

- `test_plan_product_price_quantity_reapply_po_price_differs`
- `test_plan_product_price_quantity_reapply_skips_without_po_link`
- `test_plan_product_price_quantity_reapply_skips_unchanged`
- `test_plan_product_price_quantity_reapply_restores_uom`

---

## `invoice_origin`

`_invoice_origin_from_group` (`rows.py`):

1. Si hay `__selected_oc_name` en cualquier fila → ese valor
2. Si no, une `__oc_name` únicos de líneas con contenido

`plan_invoice_origin_update` compara con el encabezado Odoo actual.

---

## Create inicial sin OC

`_build_move_vals` crea líneas con `include_purchase_link=False` y `include_product_id=False`. Los vínculos OC se aplican solo en sync (factura ya en borrador).

Motivo: evitar fallos de FK y permitir batch de contenido + taxes antes de OC.

---

## Diagrama

```mermaid
flowchart TD
  R[Filas UI con __oc_name] --> Q{_should_refresh?}
  Q -->|sí| E[enrich_rows_with_purchase_data]
  Q -->|no| G[group + reconcile IVA]
  E --> G
  G --> S{sanitize ids}
  S -->|inválidos| E2[re-refresh]
  S --> D[dedupe OC ids]
  E2 --> D
  D --> C[create account.move]
  C --> SYNC[sync_move_taxes_from_group]
  SYNC --> PO[plan_purchase_line_updates]
  PO --> W[_po_link_write_vals]
  W --> RQ[plan_product_price_quantity_reapply]
  RQ --> OW[apply_purchase_order_price_overwrites]
  OW --> TAX[_apply_tax_line_amount_overwrites]
```

---

## Troubleshooting

| Síntoma | Causa probable | Acción |
|---------|----------------|--------|
| OC no vincula | Sin `__oc_line_id` | Refresh / rematch en UI |
| OC no aparece en picker | No se ejecutó «Buscar OCs similares», Odoo no está configurado o el proveedor no tiene OCs confirmadas | Usar el botón; verificar perfil/credenciales, partner y estado purchase/done |
| Warning id no existe | PO borrada en Odoo | Re-matchear o quitar OC |
| Warning OC duplicada | Dos filas mismo `__oc_line_id` | Dedupe quitó uno |
| Precio = PO | Sync viejo sin reapply | Redeploy + re-import draft |
| Precio OC no cambió | Checkbox sin marcar o sin `__oc_line_id` | Marcar «Sobreescribir precio de la OC» e importar |
| Warning al escribir precio OC | Odoo bloqueó write en PO confirmada | Revisar permisos / estado de la OC en Odoo |
| IIBB / CABA mal al 1.er import, bien al 2.º | Montos tax antes de reapply precio | Redeploy + re-import draft |
| Sin purchase en Sudata | `_move_line_supports_purchase_link` false | Esperado; import sin OC |

---

## Tests

`tests/test_odoo_import.py`:

- `test_sanitize_group_purchase_lines_clears_missing_ids`
- `test_prepare_rows_for_import_refreshes_oc_before_grouping`
- `test_plan_purchase_line_updates_*`
- `test_dedupe_group_oc_line_ids_keeps_first_only`
- `test_plan_product_price_quantity_reapply_*`
- `test_apply_purchase_order_price_overwrites_*`
- `test_group_wants_overwrite_oc_price`

`tests/test_purchase_matching.py`:

- `test_search_oc_candidates_for_comprobante`
- `test_score_oc_candidates_lists_ocs_without_content_rows`
- `test_enrich_keeps_saved_oc_when_po_fetch_empty`
- `test_enrich_restores_saved_oc_and_marks_searched`
- `test_enrich_restores_saved_oc_on_solo_encabezado`
- `test_apply_oc_selection_sin_oc_clears_match` (el selector sigue visible después de «Sin OC»)

Patch paths: [testing.md](testing.md#mockpatch-rutas-por-submódulo).
