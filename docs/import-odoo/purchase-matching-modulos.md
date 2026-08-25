# Módulos de `odoo/purchase_matching/`

Referencia archivo por archivo. Rutas relativas a `src/facturia_matching/odoo/purchase_matching/`.

Arquitectura y prioridad UM: [purchase-matching.md](purchase-matching.md). Dominio OC/UM: [purchase-oc.md](purchase-oc.md).

---

## `__init__.py`

Reexporta la API pública y los símbolos privados que tests / callers ya importaban del monolito (`_canonical_um`, `_attach_dinner_po_note_labels`, `odoo_search_read`, etc.).

Lista en `__all__`. **No** añadir lógica aquí.

También reexporta helpers RPC usados en patches: `odoo_search_read`, `odoo_available_fields`, `odoo_model_field_names`, `clear_odoo_model_fields_cache`.

---

## `_util.py`

Utilidades sin dependencias internas del paquete (salvo `_pkg` lazy).

| Símbolo | Rol |
|---------|-----|
| `_pkg()` | Lazy `from facturia_matching.odoo import purchase_matching` — lookup para `@patch` en el root |
| `_purchase_odoo_config` | Config Odoo del perfil activo |
| `is_purchase_odoo_configured` | ¿Credenciales listas? |
| `_normalize` / `_normalize_key` | Texto / mayúsculas |
| `_parse_amount` | Monto suelto (`parse_amount_loose`) |
| `_tenant_cache_key` | `base_url\|db` |
| `_is_content_row` | ¿Fila con línea de producto? (no solo encabezado) |

---

## `uom.py`

Catálogo UM, Odoo 19 (árbol `relative_uom_id`), conversión y re-escalado.

| Símbolo / grupo | Rol |
|-----------------|-----|
| `_UM_ALIASES`, `_UOM_NAME_SYNONYMS` | Alias FacturIA → nombre Odoo (+ es_419) |
| `_canonical_um`, `_resolve_invoice_qty_um` | UM/qty de factura; no tomar envase del texto si ya hay qty |
| `_fetch_uom_catalog`, `get_uom_catalog` | Catálogo + cache TTL |
| `_uom_model_is_relative`, `_relative_uom_items` | Normalización Odoo 19 → shape ≤ 18 |
| `resolve_uom`, `convert_qty`, `_find_uom_in_category` | Resolve category-aware |
| `_product_default_uom_id`, `list_uoms_for_product` | Default compra + lista misma categoría |
| `_resolve_target_uom_for_product` | Prioridad destino (manual / kg / uom_po) |
| `_apply_uom_scaling*`, `apply_product_uom_to_row` | Re-escalado + API rematch-uom |
| `_compose_match_note`, `_stamp_target_uom` | Notas / stamp `__um_empresa*` |

Caches: `_uom_cache`, `_product_uom_cache`, `_uom_model_relative_cache`.

**Depende de:** `_util`, `odoo.api`.

---

## `scoring.py`

Fuzzy etiqueta ↔ línea OC y heurísticas Dinner.

| Símbolo / grupo | Rol |
|-----------------|-----|
| `_ocr_fix_token`, `_desc_match_variants`, `_split_desc_tokens` | OCR / tokens |
| `_NOISE_MATCH_TOKENS`, `_PREFIX_MATCH_TOKENS`, conflictos SECO/TRITURADO… | Filtros |
| `_score_dinner_note`, `_agua_affinity_score` | Notas Dinner / agua |
| `_invoice_variant_conflict`, `_soft_recount_allowed` | Zero / gas en soft basket |
| `_attach_dinner_po_note_labels` | Notas qty=0 bajo `[CÓDIGO]` |
| `_line_match_score`, `_line_match_score_against_name` | Score línea |

**Depende de:** `_util`, `rapidfuzz`.

---

## `oc.py`

Fetch de PO lines y ranking de candidatos.

| Símbolo / grupo | Rol |
|-----------------|-----|
| `_po_cache` | Cache líneas por partner |
| `_resolve_po_partner_scope`, `_partner_po_search_domain` | Dominio Odoo (todas receipt_status) |
| `fetch_partner_po_lines` | RPC purchase.order + lines + notas Dinner |
| `_receipt_status_label`, `_order_deliver_to_label` | Labels UI |
| `_ref_match_score`, `_qty_fit_score`, `_oc_date_sort_value` | Desempates ranking |
| `score_oc_candidates` | Basket %, soft recount, ranking modal |

**Depende de:** `_util`, `scoring`, `uom._resolve_invoice_qty_um`, `odoo.api`.

---

## `match.py`

Orquestación por fila / comprobante.

| Símbolo | Rol |
|---------|-----|
| `match_invoice_row` | Prioridad producto: fila → memoria → OC → fuzzy; UM vía `uom` |
| `_match_comprobante_rows` | Match de un comprobante + colisiones 1:1 OC |
| `enrich_rows_with_purchase_data` | Carga proceso / refresh |
| `search_oc_candidates_for_comprobante` | CTA «Buscar OCs» |
| `apply_oc_selection` | Modal OC / Sin OC |
| `rematch_comprobante_purchase` | Cambio proveedor |
| `apply` helpers | `_empty_purchase_fields`, snapshot/restore UM guardada |
| `clear_purchase_cache` | Limpia caches de `oc` + `uom` + fields Odoo |
| `compute_show_purchase_columns`, `row_has_odoo_purchase_data` | Flags UI |

**Depende de:** `_util`, `uom`, `scoring`, `oc`, lazy `product_label_memory`.

---

## Mapa rápido función → archivo

| Si buscás… | Abrí… |
|------------|-------|
| Alias `UN`→Units / kg Gran Crianza | `uom.py` |
| Pack 12 vs Unidades de la OC | `uom._resolve_target_uom_for_product` + `match.match_invoice_row` |
| Notas `coca` / Zero / Benedictino | `scoring.py` |
| Listado modal OC / basket % | `oc.score_oc_candidates` |
| Memoria de producto | `match` + `persistence/product_label_memory.py` |
| Endpoint rematch-uom | `uom.apply_product_uom_to_row` vía `routes.py` |
