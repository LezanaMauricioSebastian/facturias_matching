"""Humo del paquete `odoo/purchase_matching/` (estructura, no reglas de negocio)."""

import unittest
from unittest.mock import patch


class TestPurchaseMatchingPackage(unittest.TestCase):
    def test_package_imports_and_submodules(self):
        from facturia_matching.odoo import purchase_matching as pm
        from facturia_matching.odoo.purchase_matching import (
            match,
            oc,
            scoring,
            uom,
            _util,
        )

        self.assertTrue(hasattr(pm, "enrich_rows_with_purchase_data"))
        self.assertTrue(hasattr(pm, "match_invoice_row"))
        self.assertTrue(hasattr(pm, "apply_product_uom_to_row"))
        self.assertTrue(hasattr(pm, "score_oc_candidates"))
        self.assertIs(pm.match_invoice_row, match.match_invoice_row)
        self.assertIs(pm.get_uom_catalog, uom.get_uom_catalog)
        self.assertIs(pm.fetch_partner_po_lines, oc.fetch_partner_po_lines)
        self.assertIs(pm._line_match_score, scoring._line_match_score)
        self.assertTrue(callable(_util._pkg))

    def test_public_and_legacy_private_symbols_on_package(self):
        """Callers/tests históricos siguen importando desde el root del paquete."""
        from facturia_matching.odoo import purchase_matching as pm

        for name in (
            "enrich_rows_with_purchase_data",
            "apply_oc_selection",
            "apply_product_uom_to_row",
            "list_uoms_for_product",
            "rematch_comprobante_purchase",
            "search_oc_candidates_for_comprobante",
            "clear_purchase_cache",
            "match_invoice_row",
            "score_oc_candidates",
            "fetch_partner_po_lines",
            "convert_qty",
            "resolve_uom",
            "_canonical_um",
            "_attach_dinner_po_note_labels",
            "_product_default_uom_id",
            "_is_content_row",
            "odoo_search_read",
            "odoo_available_fields",
            "odoo_model_field_names",
        ):
            with self.subTest(name=name):
                self.assertTrue(hasattr(pm, name), f"falta {name} en el paquete")
                self.assertIn(name, pm.__all__)

    def test_clear_purchase_cache_empties_module_caches(self):
        from facturia_matching.odoo import purchase_matching as pm

        pm._po_cache["x|y"] = {1: {"lines": []}}
        pm._uom_cache["x|y"] = {"ts": 0.0, "data": {"by_name": {}, "by_id": {}}}
        pm._product_uom_cache["x|y"] = {9: 1}
        pm._uom_model_relative_cache["x|y"] = True

        with patch.object(pm, "clear_odoo_model_fields_cache") as mock_fields:
            pm.clear_purchase_cache()

        self.assertEqual(pm._po_cache, {})
        self.assertEqual(pm._uom_cache, {})
        self.assertEqual(pm._product_uom_cache, {})
        self.assertEqual(pm._uom_model_relative_cache, {})
        mock_fields.assert_called_once()

    def test_no_monolith_module_file(self):
        """El monolito `.py` no debe coexistir con el paquete (ambigüedad de import)."""
        from pathlib import Path
        import facturia_matching.odoo as odoo_pkg

        root = Path(odoo_pkg.__file__).resolve().parent
        self.assertTrue((root / "purchase_matching").is_dir())
        self.assertFalse((root / "purchase_matching.py").exists())


if __name__ == "__main__":
    unittest.main()
