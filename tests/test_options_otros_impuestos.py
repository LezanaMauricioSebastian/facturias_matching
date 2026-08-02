"""Tests: otros_impuestos_options = todos los account.tax del tenant."""
import unittest
from unittest.mock import patch

from facturia_matching.core.options import otros_impuestos_options_from_odoo
from facturia_matching.padron.taxes import clear_odoo_tax_catalog_cache, resolve_tax_label_to_id


class TestOtrosImpuestosOptionsFromOdoo(unittest.TestCase):
    def test_returns_none_without_odoo_catalog(self):
        with patch("facturia_matching.padron.taxes.get_tax_name_by_id", return_value={}):
            self.assertIsNone(otros_impuestos_options_from_odoo())

    def test_lists_all_taxes_alphabetically_with_es_display(self):
        name_by_id = {
            1: "P. IIBB CABA",
            29: "Perc Gananc",
            72: "Perc IVA",
            25: "Other taxes",
            26: "Internal taxes",
            65: "IVA 21%",
            55: "IVA No Gravado",
        }

        with patch("facturia_matching.padron.taxes.get_tax_name_by_id", return_value=name_by_id):
            out = otros_impuestos_options_from_odoo()

        self.assertEqual(
            out,
            sorted(
                [
                    "Impuestos internos",
                    "IVA 21%",
                    "IVA No Gravado",
                    "Otros impuestos",
                    "P. IIBB CABA",
                    "Perc Gananc",
                    "Perc IVA",
                ],
                key=str.casefold,
            ),
        )
        self.assertNotIn("Internal taxes", out)
        self.assertNotIn("Other taxes", out)

    def test_dedupes_same_display_label(self):
        name_by_id = {1: "IVA 21%", 2: "iva 21%"}
        with patch("facturia_matching.padron.taxes.get_tax_name_by_id", return_value=name_by_id):
            out = otros_impuestos_options_from_odoo()
        self.assertEqual(len(out), 1)


class TestResolveTaxLabelAliases(unittest.TestCase):
    def tearDown(self):
        clear_odoo_tax_catalog_cache()

    def test_aliare_abbreviated_percepciones(self):
        by_id = {
            29: "Perc Gananc",
            72: "Perc IVA",
            1: "P. IIBB CABA",
        }
        with patch("facturia_matching.padron.taxes.get_tax_name_by_id", return_value=by_id):
            clear_odoo_tax_catalog_cache()
            self.assertEqual(resolve_tax_label_to_id("Percepción Ganancias Sufrida"), 29)
            self.assertEqual(resolve_tax_label_to_id("Percepción IVA Sufrida"), 72)
            self.assertEqual(resolve_tax_label_to_id("Percepción IIBB CABA Sufrida"), 1)
            self.assertEqual(resolve_tax_label_to_id("Perc Gananc"), 29)

    def test_english_odoo_names_resolve_from_spanish_labels(self):
        by_id = {25: "Other taxes", 26: "Internal taxes"}
        with patch("facturia_matching.padron.taxes.get_tax_name_by_id", return_value=by_id):
            clear_odoo_tax_catalog_cache()
            self.assertEqual(resolve_tax_label_to_id("Impuesto Interno"), 26)
            self.assertEqual(resolve_tax_label_to_id("Impuestos internos"), 26)
            self.assertEqual(resolve_tax_label_to_id("Otros impuestos"), 25)
            self.assertEqual(resolve_tax_label_to_id("Internal taxes"), 26)


if __name__ == "__main__":
    unittest.main()
