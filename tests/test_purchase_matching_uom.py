"""Tests for purchase qty/UOM scaling and Odoo 19 relative UOM model."""
import unittest
from unittest.mock import patch

from facturia_matching.odoo.purchase_matching import (
    _extract_qty_um_from_description,
    _resolve_invoice_qty_um,
    convert_qty,
    resolve_uom,
)


class TestPurchaseMatching(unittest.TestCase):
    def test_extract_qty_um_from_description(self):
        qty, um = _extract_qty_um_from_description("6 kg pan líquido")
        self.assertAlmostEqual(qty, 6.0)
        self.assertEqual(um, "kg")

    def test_resolve_invoice_qty_prefers_facturia_over_package_size(self):
        row = {
            "invoice_line_ids/quantity": "1",
            "__fac_item_cantidad": "10",
            "__um_proveedor": "UN",
        }
        qty, um = _resolve_invoice_qty_um(
            row,
            "AZUCAR COMUN X 1 KG.",
            repair_row=True,
        )
        self.assertEqual(qty, 10.0)
        self.assertEqual(um, "UN")
        self.assertEqual(row["invoice_line_ids/quantity"], "10")

    def test_resolve_invoice_qty_repairs_saved_desc_pollution(self):
        row = {
            "invoice_line_ids/quantity": "2840",
            "__fac_item_cantidad": "6",
            "__um_proveedor": "UN",
        }
        qty, _ = _resolve_invoice_qty_um(
            row,
            "CHAMP. CARACAS FILETEADO X 2840 G",
            repair_row=True,
        )
        self.assertEqual(qty, 6.0)
        self.assertEqual(row["invoice_line_ids/quantity"], "6")

    def test_resolve_invoice_qty_repairs_partial_sanitize_to_one(self):
        row = {
            "invoice_line_ids/quantity": "1",
            "__fac_item_cantidad": "6",
            "__um_proveedor": "UN",
        }
        qty, _ = _resolve_invoice_qty_um(
            row,
            "CHAMP. CARACAS FILETEADO X 2840 G",
            repair_row=True,
        )
        self.assertEqual(qty, 6.0)
        self.assertEqual(row["invoice_line_ids/quantity"], "6")

    def test_resolve_invoice_qty_keeps_manual_edit(self):
        row = {
            "invoice_line_ids/quantity": "5",
            "__fac_item_cantidad": "10",
            "__um_proveedor": "UN",
        }
        qty, _ = _resolve_invoice_qty_um(
            row,
            "AZUCAR COMUN X 1 KG.",
            repair_row=True,
        )
        self.assertEqual(qty, 5.0)
        self.assertEqual(row["invoice_line_ids/quantity"], "5")

    def test_resolve_invoice_qty_ignores_package_um_when_qty_present(self):
        """«X 500 G» en descripción no debe volverse UM si ya hay cantidad de línea."""
        row = {
            "invoice_line_ids/quantity": "20",
            "__fac_item_cantidad": "20",
            "__um_proveedor": "",
        }
        qty, um = _resolve_invoice_qty_um(
            row,
            "SAL FINA CELUSAL X 500 G",
            repair_row=True,
        )
        self.assertEqual(qty, 20.0)
        self.assertEqual(um, "")

    def test_convert_qty_same_category(self):
        from_uom = {"id": 13, "factor": 1000.0, "category_id": [2, "Weight"]}
        to_uom = {"id": 12, "factor": 1.0, "category_id": [2, "Weight"]}
        self.assertAlmostEqual(convert_qty(1000.0, from_uom, to_uom), 1.0)

    def test_apply_uom_scaling_sets_empresa_id(self):
        from facturia_matching.odoo.purchase_matching import _apply_uom_scaling

        catalog = {
            "by_id": {
                12: {"id": 12, "name": "kg", "factor": 1.0, "category_id": [2, "Weight"]},
                13: {"id": 13, "name": "g", "factor": 1000.0, "category_id": [2, "Weight"]},
            },
            "by_name": {
                "KG": {"id": 12, "name": "kg", "factor": 1.0, "category_id": [2, "Weight"]},
                "G": {"id": 13, "name": "g", "factor": 1000.0, "category_id": [2, "Weight"]},
            },
        }
        out = _apply_uom_scaling(
            {},
            invoice_qty=1000.0,
            invoice_um_raw="g",
            po_uom_id=12,
            po_uom_name="kg",
            uom_catalog=catalog,
        )
        self.assertEqual(out["um_empresa_id"], "12")
        self.assertEqual(out["um_note"], "Re-escalado")
        self.assertEqual(out["qty_escalada"], "1")

    def _dinner_like_uom_catalog(self):
        """Catálogo estilo Dinner: kg/L duplicados en categorías custom + UOMs de envase."""
        weight = [2, "Peso"]
        crema = [10, "Conversión Crema de Leche"]
        volume = [6, "Volumen"]
        litros = [9, "LITROS"]
        kg_peso = {
            "id": 12,
            "name": "kg",
            "factor": 1.0,
            "category_id": weight,
            "uom_type": "reference",
        }
        kg_crema = {
            "id": 73,
            "name": "kg",
            "factor": 1.0,
            "category_id": crema,
            "uom_type": "reference",
        }
        g = {
            "id": 13,
            "name": "g",
            "factor": 1000.0,
            "category_id": weight,
            "uom_type": "smaller",
        }
        pack_2840 = {
            "id": 90,
            "name": "unidad de (2840g)",
            "factor": 0.35211267605633806,
            "category_id": weight,
            "uom_type": "bigger",
        }
        l_vol = {
            "id": 10,
            "name": "L",
            "factor": 1.0,
            "category_id": volume,
            "uom_type": "reference",
        }
        l_litros = {
            "id": 62,
            "name": "L",
            "factor": 1.0,
            "category_id": litros,
            "uom_type": "reference",
        }
        pack_5lt = {
            "id": 85,
            "name": "unidad de (5LT)",
            "factor": 0.2,
            "category_id": volume,
            "uom_type": "bigger",
        }
        return {
            "by_id": {
                12: kg_peso,
                73: kg_crema,
                13: g,
                90: pack_2840,
                10: l_vol,
                62: l_litros,
                85: pack_5lt,
            },
            # Lista = colisión; el último solo (legado) era kg_crema / L LITROS y rompía Peso/Volumen.
            "by_name": {
                "KG": [kg_crema, kg_peso],
                "G": [g],
                "L": [l_litros, l_vol],
                "LT": [l_litros, l_vol],
                "UNIDAD DE (2840G)": [pack_2840],
                "UNIDAD DE (5LT)": [pack_5lt],
            },
        }

    def test_apply_uom_scaling_kg_collision_uses_target_category(self):
        """FacturIA manda KG; by_name global apunta al kg de otra categoría → debe usar Peso."""
        from facturia_matching.odoo.purchase_matching import _apply_uom_scaling

        catalog = self._dinner_like_uom_catalog()
        out = _apply_uom_scaling(
            {},
            invoice_qty=6.0,
            invoice_um_raw="KG",
            po_uom_id=12,
            po_uom_name="kg",
            uom_catalog=catalog,
        )
        self.assertEqual(out["um_empresa_id"], "12")
        self.assertEqual(out["um_factor"], "1")
        self.assertNotEqual(out["um_note"], "Categoría UM distinta")

    def test_apply_uom_scaling_oc_custom_pack_from_kg_invoice(self):
        """OC en unidad de (2840g); factura KG debe re-escalar a packs (misma categoría Peso)."""
        from facturia_matching.odoo.purchase_matching import _apply_uom_scaling

        catalog = self._dinner_like_uom_catalog()
        out = _apply_uom_scaling(
            {},
            invoice_qty=6.0,
            invoice_um_raw="KG",
            po_uom_id=90,
            po_uom_name="unidad de (2840g)",
            uom_catalog=catalog,
        )
        self.assertEqual(out["um_empresa_id"], "90")
        self.assertEqual(out["um_note"], "Re-escalado")
        # 6 kg * (0.352... / 1) ≈ 2.11 packs de 2840g
        self.assertAlmostEqual(float(out["qty_escalada"]), 6.0 * 0.35211267605633806, places=5)

    def test_apply_uom_scaling_oc_custom_pack_from_g_invoice(self):
        from facturia_matching.odoo.purchase_matching import _apply_uom_scaling

        catalog = self._dinner_like_uom_catalog()
        out = _apply_uom_scaling(
            {},
            invoice_qty=2840.0,
            invoice_um_raw="g",
            po_uom_id=90,
            po_uom_name="unidad de (2840g)",
            uom_catalog=catalog,
        )
        self.assertEqual(out["um_empresa_id"], "90")
        self.assertEqual(out["um_note"], "Re-escalado")
        self.assertEqual(out["qty_escalada"], "1")

    def test_apply_uom_scaling_lt_collision_uses_volume_category(self):
        from facturia_matching.odoo.purchase_matching import _apply_uom_scaling

        catalog = self._dinner_like_uom_catalog()
        out = _apply_uom_scaling(
            {},
            invoice_qty=6.0,
            invoice_um_raw="LT",
            po_uom_id=85,
            po_uom_name="unidad de (5LT)",
            uom_catalog=catalog,
        )
        self.assertEqual(out["um_empresa_id"], "85")
        self.assertEqual(out["um_note"], "Re-escalado")
        self.assertEqual(out["qty_escalada"], "1.2")

    def test_find_uom_in_category_prefers_weight_kg(self):
        from facturia_matching.odoo.purchase_matching import _find_uom_in_category

        catalog = self._dinner_like_uom_catalog()
        found = _find_uom_in_category("KG", 2, catalog)
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], 12)
        crema = _find_uom_in_category("KG", 10, catalog)
        self.assertIsNotNone(crema)
        self.assertEqual(crema["id"], 73)

    def test_apply_product_uom_to_row_sets_pack_from_product(self):
        from unittest.mock import patch
        from facturia_matching.odoo.purchase_matching import apply_product_uom_to_row

        units = {
            "id": 1,
            "name": "Unidades",
            "factor": 1.0,
            "category_id": [1, "Unidad"],
            "uom_type": "reference",
        }
        pack12 = {
            "id": 100,
            "name": "pack (12 unidades)",
            "factor": 1.0 / 12.0,
            "category_id": [1, "Unidad"],
            "uom_type": "bigger",
        }
        catalog = {
            "by_id": {1: units, 100: pack12},
            "by_name": {"UN": [units], "UNIDADES": [units]},
        }
        row = {
            "invoice_line_ids/name": "COCA-COLA 600*12 PET",
            "invoice_line_ids/product_id": "620",
            "invoice_line_ids/quantity": "24",
            "__fac_item_cantidad": "24",
            "__um_proveedor": "UN",
            "__product_suggested": "80",
        }
        with patch(
            "facturia_matching.odoo.purchase_matching._product_default_uom_id",
            return_value=100,
        ), patch(
            "facturia_matching.odoo.purchase_matching.get_uom_catalog",
            return_value=catalog,
        ):
            info = apply_product_uom_to_row(row)
        self.assertEqual(row["__um_empresa"], "pack (12 unidades)")
        self.assertEqual(row["__um_empresa_id"], "100")
        self.assertEqual(row["__um_note"], "Re-escalado")
        self.assertEqual(row["__qty_escalada"], "2")
        self.assertEqual(row["invoice_line_ids/quantity"], "2")
        self.assertEqual(row["__product_suggested"], "")
        self.assertEqual(info["um_empresa_id"], "100")

    def test_apply_product_uom_to_row_clears_without_product(self):
        from facturia_matching.odoo.purchase_matching import apply_product_uom_to_row

        row = {
            "invoice_line_ids/product_id": "",
            "__um_empresa": "pack (12 unidades)",
            "__um_empresa_id": "100",
            "__um_factor": "0.5",
            "__um_note": "Re-escalado",
        }
        apply_product_uom_to_row(row, None)
        self.assertEqual(row["__um_empresa"], "")
        self.assertEqual(row["__um_empresa_id"], "")

    def test_list_uoms_for_product_same_category(self):
        from unittest.mock import patch
        from facturia_matching.odoo.purchase_matching import list_uoms_for_product

        units = {
            "id": 1,
            "name": "Unidades",
            "factor": 1.0,
            "category_id": [1, "Unidad"],
            "uom_type": "reference",
        }
        pack12 = {
            "id": 100,
            "name": "pack (12 unidades)",
            "factor": 1.0 / 12.0,
            "category_id": [1, "Unidad"],
            "uom_type": "bigger",
        }
        kg = {
            "id": 12,
            "name": "kg",
            "factor": 1.0,
            "category_id": [2, "Weight"],
            "uom_type": "reference",
        }
        catalog = {
            "by_id": {1: units, 100: pack12, 12: kg},
            "by_name": {},
        }
        with patch(
            "facturia_matching.odoo.purchase_matching._product_default_uom_id",
            return_value=100,
        ), patch(
            "facturia_matching.odoo.purchase_matching.get_uom_catalog",
            return_value=catalog,
        ):
            uoms = list_uoms_for_product(620)
        ids = {u["id"] for u in uoms}
        self.assertEqual(ids, {1, 100})
        self.assertTrue(all("name" in u for u in uoms))

    def test_apply_product_uom_to_row_explicit_uom_id_rescales(self):
        from unittest.mock import patch
        from facturia_matching.odoo.purchase_matching import apply_product_uom_to_row

        units = {
            "id": 1,
            "name": "Unidades",
            "factor": 1.0,
            "category_id": [1, "Unidad"],
            "uom_type": "reference",
        }
        pack12 = {
            "id": 100,
            "name": "pack (12 unidades)",
            "factor": 1.0 / 12.0,
            "category_id": [1, "Unidad"],
            "uom_type": "bigger",
        }
        catalog = {
            "by_id": {1: units, 100: pack12},
            "by_name": {"UN": [units], "UNIDADES": [units]},
        }
        row = {
            "invoice_line_ids/name": "COCA-COLA 600*12 PET",
            "invoice_line_ids/product_id": "620",
            "invoice_line_ids/quantity": "2",  # ya re-escalada a packs
            "__fac_item_cantidad": "24",
            "__um_proveedor": "UN",
            "__qty_original": "24",
            "__um_empresa": "pack (12 unidades)",
            "__um_empresa_id": "100",
        }
        with patch(
            "facturia_matching.odoo.purchase_matching._product_default_uom_id",
            return_value=100,
        ), patch(
            "facturia_matching.odoo.purchase_matching.get_uom_catalog",
            return_value=catalog,
        ):
            info = apply_product_uom_to_row(row, 620, uom_id=1)
        self.assertEqual(row["__um_empresa"], "Unidades")
        self.assertEqual(row["__um_empresa_id"], "1")
        self.assertEqual(float(row["invoice_line_ids/quantity"]), 24.0)
        self.assertEqual(float(row["__qty_escalada"]), 24.0)
        self.assertEqual(info["um_empresa_id"], "1")

    def test_apply_product_uom_to_row_rejects_out_of_category_uom(self):
        from unittest.mock import patch
        from facturia_matching.odoo.purchase_matching import apply_product_uom_to_row

        units = {
            "id": 1,
            "name": "Unidades",
            "factor": 1.0,
            "category_id": [1, "Unidad"],
            "uom_type": "reference",
        }
        pack12 = {
            "id": 100,
            "name": "pack (12 unidades)",
            "factor": 1.0 / 12.0,
            "category_id": [1, "Unidad"],
            "uom_type": "bigger",
        }
        kg = {
            "id": 12,
            "name": "kg",
            "factor": 1.0,
            "category_id": [2, "Weight"],
            "uom_type": "reference",
        }
        catalog = {
            "by_id": {1: units, 100: pack12, 12: kg},
            "by_name": {"UN": [units], "UNIDADES": [units]},
        }
        row = {
            "invoice_line_ids/name": "COCA-COLA",
            "invoice_line_ids/product_id": "620",
            "invoice_line_ids/quantity": "24",
            "__fac_item_cantidad": "24",
            "__um_proveedor": "UN",
            "__qty_original": "24",
        }
        with patch(
            "facturia_matching.odoo.purchase_matching._product_default_uom_id",
            return_value=100,
        ), patch(
            "facturia_matching.odoo.purchase_matching.get_uom_catalog",
            return_value=catalog,
        ):
            apply_product_uom_to_row(row, 620, uom_id=12)
        # kg fuera de categoría → cae al default pack
        self.assertEqual(row["__um_empresa"], "pack (12 unidades)")
        self.assertEqual(row["__um_empresa_id"], "100")

    def test_resolve_target_uom_prefers_invoice_kg(self):
        """FacturIA KG + producto con pack de peso → preferir kg (Gran Crianza)."""
        from facturia_matching.odoo.purchase_matching import _resolve_target_uom_for_product

        catalog = self._dinner_like_uom_catalog()
        with patch(
            "facturia_matching.odoo.purchase_matching._product_default_uom_id",
            return_value=90,  # unidad de (2840g)
        ):
            to_uom = _resolve_target_uom_for_product(
                555, catalog, invoice_um_raw="KG"
            )
        self.assertIsNotNone(to_uom)
        self.assertEqual(int(to_uom["id"]), 12)  # kg en categoría Peso

    def test_um_aliases_resolve_with_spanish_uom_catalog(self):
        """Sudata en es_419 devuelve 'Unidades' / 'Tonelada': los alias UN/MES/TN siguen mapeando."""
        es_rows = [
            {"id": 1, "name": "Unidades", "uom_type": "reference", "factor": 1.0, "category_id": [1, "Unidad"]},
            {"id": 15, "name": "kg", "uom_type": "reference", "factor": 1.0, "category_id": [2, "Peso"]},
            {"id": 16, "name": "Tonelada", "uom_type": "bigger", "factor": 0.001, "category_id": [2, "Peso"]},
        ]
        catalog = _build_uom_catalog(es_rows, relative=False)

        for raw in ("UN", "U", "UNIDAD", "UNIDADES", "PIEZA", "MES", "Units"):
            with self.subTest(raw=raw):
                uom = resolve_uom(raw, catalog)
                self.assertIsNotNone(uom, f"{raw} no resolvió con catálogo en español")
                self.assertEqual(int(uom["id"]), 1)
        self.assertEqual(int(resolve_uom("KG", catalog)["id"]), 15)
        self.assertEqual(int(resolve_uom("TN", catalog)["id"]), 16)

    def test_um_aliases_still_resolve_with_english_uom_catalog(self):
        en_rows = [
            {"id": 1, "name": "Units", "uom_type": "reference", "factor": 1.0, "category_id": [1, "Unit"]},
            {"id": 16, "name": "Ton", "uom_type": "bigger", "factor": 0.001, "category_id": [2, "Weight"]},
        ]
        catalog = _build_uom_catalog(en_rows, relative=False)

        self.assertEqual(int(resolve_uom("UNIDAD", catalog)["id"]), 1)
        self.assertEqual(int(resolve_uom("TONELADA", catalog)["id"]), 16)


# uom.uom tal como responde Sudata (Odoo 19): árbol relative_uom_id, factor = razón a la raíz.
ODOO19_UOM_ROWS = [
    {"id": 1, "name": "Unidades", "factor": 1.0, "relative_factor": 1.0, "relative_uom_id": False},
    {"id": 2, "name": "Paquete de 6", "factor": 6.0, "relative_factor": 6.0, "relative_uom_id": [1, "Unidades"]},
    {"id": 8, "name": "m", "factor": 1000.0, "relative_factor": 100.0, "relative_uom_id": [7, "cm"]},
    {"id": 11, "name": "ml", "factor": 1.0, "relative_factor": 1.0, "relative_uom_id": False},
    {"id": 12, "name": "L", "factor": 1000.0, "relative_factor": 1000.0, "relative_uom_id": [11, "ml"]},
    {"id": 14, "name": "g", "factor": 1.0, "relative_factor": 1.0, "relative_uom_id": False},
    {"id": 15, "name": "kg", "factor": 1000.0, "relative_factor": 1000.0, "relative_uom_id": [14, "g"]},
    {"id": 16, "name": "Tonelada", "factor": 1000000.0, "relative_factor": 1000.0, "relative_uom_id": [15, "kg"]},
]
# 'mm' y 'cm' archivados: search_read no los trae, cierran el árbol de 'm'.
ODOO19_ARCHIVED_UOMS = [
    {"id": 6, "name": "mm", "factor": 1.0, "relative_factor": 1.0, "relative_uom_id": False},
    {"id": 7, "name": "cm", "factor": 10.0, "relative_factor": 10.0, "relative_uom_id": [6, "mm"]},
]


def _build_uom_catalog(rows, *, relative, archived=None):
    """Arma el catálogo como en producción, con el modelo uom.uom indicado."""
    from facturia_matching.odoo import purchase_matching as pm

    def fake_search_read(model, domain=None, fields=None, limit=500, **kwargs):
        wanted = None
        for term in domain or []:
            if isinstance(term, (list, tuple)) and len(term) == 3 and term[0] == "id":
                wanted = set(term[2])
        if wanted is not None:
            return [r for r in (archived or []) if int(r["id"]) in wanted]
        return list(rows)

    with patch.object(pm, "odoo_search_read", side_effect=fake_search_read), patch.object(
        pm, "_purchase_odoo_config", return_value={"base_url": "x", "db": "y"}
    ), patch.object(pm, "_uom_model_is_relative", return_value=relative):
        return pm._fetch_uom_catalog()


class TestUomOdoo19Model(unittest.TestCase):
    """Odoo 19: uom.uom sin category_id/uom_type (Sudata)."""

    def setUp(self):
        from facturia_matching.odoo.purchase_matching import clear_purchase_cache

        clear_purchase_cache()
        self.catalog = _build_uom_catalog(
            ODOO19_UOM_ROWS, relative=True, archived=ODOO19_ARCHIVED_UOMS
        )

    def _uom(self, name_or_alias):
        from facturia_matching.odoo.purchase_matching import resolve_uom

        return resolve_uom(name_or_alias, self.catalog)

    def test_detects_relative_model_by_fields(self):
        from facturia_matching.odoo import purchase_matching as pm

        with patch.object(
            pm, "_purchase_odoo_config", return_value={"base_url": "x", "db": "y"}
        ), patch.object(
            pm,
            "odoo_model_field_names",
            return_value=frozenset({"name", "relative_factor", "relative_uom_id"}),
        ):
            self.assertTrue(pm._uom_model_is_relative())
        pm.clear_purchase_cache()
        with patch.object(
            pm, "_purchase_odoo_config", return_value={"base_url": "x", "db": "y"}
        ), patch.object(
            pm,
            "odoo_model_field_names",
            return_value=frozenset({"name", "category_id", "uom_type", "factor"}),
        ):
            self.assertFalse(pm._uom_model_is_relative())

    def test_unknown_fields_keep_legacy_model(self):
        """Si el fields_get falla no se asume Odoo 19: se sigue con el catálogo histórico."""
        from facturia_matching.odoo import purchase_matching as pm

        with patch.object(
            pm, "_purchase_odoo_config", return_value={"base_url": "x", "db": "y"}
        ), patch.object(pm, "odoo_model_field_names", return_value=frozenset()):
            self.assertFalse(pm._uom_model_is_relative())

    def test_tree_root_becomes_category(self):
        from facturia_matching.odoo.purchase_matching import _category_id

        weight = {self._uom(n)["id"]: _category_id(self._uom(n)) for n in ("g", "kg", "Tonelada")}
        self.assertEqual(set(weight.values()), {14})  # raíz g
        self.assertEqual(_category_id(self._uom("L")), 11)  # raíz ml
        self.assertEqual(_category_id(self._uom("Paquete de 6")), 1)  # raíz Unidades

    def test_archived_parents_close_the_tree(self):
        """'m' cuelga de cm (archivado): su categoría debe ser la raíz mm, no él mismo."""
        from facturia_matching.odoo.purchase_matching import _category_id

        self.assertEqual(_category_id(self._uom("m")), 6)

    def test_convert_qty_weight(self):
        from facturia_matching.odoo.purchase_matching import convert_qty

        self.assertAlmostEqual(convert_qty(1000.0, self._uom("g"), self._uom("kg")), 1.0)
        self.assertAlmostEqual(convert_qty(1.0, self._uom("kg"), self._uom("g")), 1000.0)
        self.assertAlmostEqual(convert_qty(2.0, self._uom("Tonelada"), self._uom("kg")), 2000.0)

    def test_convert_qty_units_and_packs(self):
        from facturia_matching.odoo.purchase_matching import convert_qty

        self.assertAlmostEqual(
            convert_qty(12.0, self._uom("Unidades"), self._uom("Paquete de 6")), 2.0
        )
        self.assertAlmostEqual(
            convert_qty(2.0, self._uom("Paquete de 6"), self._uom("Unidades")), 12.0
        )

    def test_convert_qty_across_trees_is_none(self):
        from facturia_matching.odoo.purchase_matching import convert_qty

        self.assertIsNone(convert_qty(1.0, self._uom("kg"), self._uom("L")))

    def test_aliases_resolve_in_relative_model(self):
        self.assertEqual(int(self._uom("UN")["id"]), 1)
        self.assertEqual(int(self._uom("KG")["id"]), 15)
        self.assertEqual(int(self._uom("LT")["id"]), 12)
        self.assertEqual(int(self._uom("TN")["id"]), 16)

    def test_scaling_uses_relative_catalog(self):
        from facturia_matching.odoo.purchase_matching import _apply_uom_scaling

        out = _apply_uom_scaling(
            {},
            invoice_qty=1000.0,
            invoice_um_raw="g",
            po_uom_id=15,
            po_uom_name="kg",
            uom_catalog=self.catalog,
        )
        self.assertEqual(out["um_empresa_id"], "15")
        self.assertEqual(out["um_note"], "Re-escalado")
        self.assertEqual(out["qty_escalada"], "1")

    def test_product_default_uom_without_uom_po_id(self):
        """Odoo 19 no tiene uom_po_id: pedirlo hacía fallar el search_read completo."""
        from facturia_matching.odoo import purchase_matching as pm

        captured = {}

        def fake_search_read(model, domain=None, fields=None, limit=500, **kwargs):
            captured["fields"] = list(fields or [])
            return [{"id": 5, "uom_id": [15, "kg"]}]

        with patch.object(pm, "odoo_search_read", side_effect=fake_search_read), patch.object(
            pm, "_purchase_odoo_config", return_value={"base_url": "x", "db": "y"}
        ), patch.object(pm, "is_purchase_odoo_configured", return_value=True), patch.object(
            pm, "odoo_available_fields", return_value=["uom_id"]
        ):
            self.assertEqual(pm._product_default_uom_id(5), 15)
        self.assertEqual(captured["fields"], ["uom_id"])

    def test_list_uoms_for_product_uses_tree(self):
        from facturia_matching.odoo import purchase_matching as pm

        with patch.object(pm, "_product_default_uom_id", return_value=15), patch.object(
            pm, "get_uom_catalog", return_value=self.catalog
        ):
            names = [u["name"] for u in pm.list_uoms_for_product(5)]
        self.assertEqual(names, ["g", "kg", "Tonelada"])
