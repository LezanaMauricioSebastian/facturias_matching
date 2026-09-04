# Paquete `odoo/purchase_matching/`

Matching factura ↔ órdenes de compra Odoo + resolución / re-escalado de UM.

**Código:** `src/facturia_matching/odoo/purchase_matching/`

**Comportamiento de negocio (OC, UM, memoria, Dinner):** [purchase-oc.md](purchase-oc.md)

**Referencia archivo por archivo:** [purchase-matching-modulos.md](purchase-matching-modulos.md)

---

## Por qué un subpaquete

Antes todo vivía en `odoo/purchase_matching.py` (~2680 líneas). Mezclaba:

- helpers de texto / normalización,
- catálogo UM (incl. Odoo 19),
- fuzzy y notas Dinner,
- fetch + ranking de OCs,
- orquestación (`match_invoice_row`, enrich, select-oc, rematch).

El subpaquete separa **por dominio**, igual que `odoo/import_/`. **No cambia reglas** de matching ni de UM: solo reorganización.

---

## Principios

1. **`__init__.py` solo reexporta** — callers y tests siguen importando `facturia_matching.odoo.purchase_matching`.
2. **Sin dependencias circulares** — grafo abajo; si hace falta, lazy import / `_pkg()`.
3. **`_pkg()` para patches** — varios puntos de entrada resuelven símbolos vía el paquete en runtime (`_pkg().get_uom_catalog()`, etc.) para que `@patch("facturia_matching.odoo.purchase_matching.…")` y `patch.object(pm, …)` sigan funcionando como con el monolito.
4. **Caches por tenant** — clave `base_url|db`; `clear_purchase_cache()` limpia PO + UM + `clear_odoo_model_fields_cache()`.

---

## Árbol

```
src/facturia_matching/odoo/purchase_matching/
├── __init__.py   # Reexporta API pública + privados usados por tests
├── _util.py      # normalize, parse_amount, config, _pkg, _is_content_row
├── uom.py        # Catálogo UM, Odoo 19, convert, apply_product_uom_to_row
├── uom_ai.py     # Sugerencia Claude antes del fallback a Unidades
├── scoring.py    # Tokens, Dinner notes, _line_match_score
├── oc.py         # fetch_partner_po_lines, score_oc_candidates
└── match.py      # match_invoice_row, enrich, select-oc, rematch, clear cache
```

---

## Grafo de dependencias

```
_util.py
    ↑
uom.py ←── uom_ai.py (lazy)
    ↑
scoring.py
    ↑
    └───── oc.py ───┘
              ↑
           match.py
              ↑
         __init__.py
```

- `oc` usa `scoring` (notas / line score) y `uom._resolve_invoice_qty_um` (contexto qty).
- `match` orquesta todo; `clear_purchase_cache` también limpia `uom_ai`.
- `_is_content_row` vive en `_util` (lo usan `oc.score_oc_candidates` y `match`).
- `uom_ai` solo se importa cuando el fallback a default está por ocurrir (lazy).

---

## Orden de prioridad de la UM destino

(`__um_empresa` / `product_uom_id` al importar). Detalle en [purchase-oc.md § Unidad de medida](purchase-oc.md#unidad-de-medida-um).

1. **UM ya guardada en la fila** (`__um_empresa_id`) — reload / autosave; no re-escala.
2. **UM de memoria** (`product_label_memory.uom_id`) — mismo proveedor + etiqueta; no re-escala qty.
3. **UM elegida a mano** (`POST rematch-uom` con `uom_id`) — misma categoría; re-escala desde qty/UM original.
4. **Excepción peso FacturIA** — `unidad_medida` `KG`/`g` y existe en la categoría del producto → preferir **kg** sobre pack/`uom_po`.
5. **Sugerencia Claude** (`uom_ai`) — si `FACTURIA_UOM_AI_ENABLED=1` + `ANTHROPIC_API_KEY`, hay descripción de ítem y **>1 UM** en la categoría del producto → Claude elige el ID; stamp `__um_note` con `UM sugerida por IA`. Reemplaza el fallback a Unidades cuando el default de compra suele ser incorrecto (packs / kg / litros en gastronomía).
6. **Default de compra del producto** (`uom_po_id` / `uom_id`) — **no** la UM de la línea OC (solo si la IA está off, falla o no hay opciones).
7. **Fallback raro** — match OC sin `product_id` → UM de la línea OC.

FacturIA (`__um_proveedor`) no elige la UM de empresa: solo sirve para re-escalar cuando hay mapeo. Sin UM de factura → stamp del destino (IA o default) con nota `Sin UM en factura` (y/o `UM sugerida por IA`).

Código: `match.match_invoice_row` + `uom._resolve_target_uom_for_product` + `uom_ai.suggest_uom`.

---

## Caches

| Cache | Módulo | Clave |
|-------|--------|-------|
| `_po_cache` | `oc.py` | tenant → partner_id → líneas OC |
| `_uom_cache` | `uom.py` | tenant → catálogo UM (TTL 600s) |
| `_product_uom_cache` | `uom.py` | tenant → product_id → uom default |
| `_uom_model_relative_cache` | `uom.py` | tenant → ¿Odoo 19 relative? |
| `_CACHE` | `uom_ai.py` | `(product_id, label_key)` → id UM sugerido |

`clear_purchase_cache()` (en `match.py`) limpia las de PO/UM + `clear_uom_ai_cache()` + `clear_odoo_model_fields_cache()`.

---

## Quién importa qué

| Caller | Símbolos típicos |
|--------|------------------|
| `api/routes.py` | `apply_oc_selection`, `apply_product_uom_to_row`, `list_uoms_for_product`, `rematch_comprobante_purchase`, `search_oc_candidates_for_comprobante` |
| `core/process.py` | `enrich_rows_with_purchase_data` |
| `import_/purchase.py` | lazy `clear_purchase_cache`, `enrich_rows_with_purchase_data` |
| `persistence/*` | enrich / group / clear comprobante |
| Tests | root del paquete (públicos y privados) |

Import preferido:

```python
from facturia_matching.odoo.purchase_matching import enrich_rows_with_purchase_data
```

Submódulos solo si hace falta (docs / patches finos):

```python
from facturia_matching.odoo.purchase_matching import uom
```

---

## Tests

| Archivo | Rol |
|---------|-----|
| `tests/test_purchase_matching_uom.py` | Qty/UM, scaling, Odoo 19 |
| `tests/test_purchase_matching_oc.py` | Candidatos OC, enrich/select/rematch |
| `tests/test_purchase_matching_match.py` | Scoring línea / Dinner / fuzzy / OCR |
| `tests/test_product_label_memory.py` | Memoria producto + UM |
| `tests/test_purchase_matching_package.py` | Humo del paquete (imports, `__all__`, caches, sin monolito `.py`) |
| `tests/test_odoo_import_purchase.py` | UM en create / reapply (import_) |

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_purchase_matching_uom \
  tests.test_purchase_matching_oc \
  tests.test_purchase_matching_match \
  tests.test_product_label_memory \
  tests.test_purchase_matching_package \
  -q
```

**Patches:** preferir el root del paquete (`facturia_matching.odoo.purchase_matching.X`) — el código usa `_pkg()` en los puntos que los tests históricos mockean. Ver [testing.md](testing.md#purchase_matching-paquete).
