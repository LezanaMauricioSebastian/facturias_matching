"""Tests: otros_impuestos_options filtradas/extendidas por catálogo Odoo."""
import unittest
from unittest.mock import patch

from facturia_matching.core.options import otros_impuestos_options_from_odoo
from facturia_matching.padron.taxes import clear_odoo_tax_catalog_cache, resolve_tax_label_to_id


class TestOtrosImpuestosOptionsFromOdoo(unittest.TestCase):
    def test_returns_none_without_odoo_catalog(self):
        with patch("facturia_matching.padron.taxes.get_tax_name_by_id", return_value={}):
            self.assertIsNone(otros_impuestos_options_from_odoo())

    def test_filters_and_dedupes_by_tax_id_prefers_sufrida(self):
        def fake_resolve(label: str):
            mapping = {
                "Percepción IIBB CABA Sufrida": 1,
                "Percepción IIBB CABA Aplicada": 1,
                "Percepción IIBB ARBA Sufrida": 2,
                "Percepción IIBB Santa Fe Sufrida": None,
            }
            return mapping.get(label)

        with patch(
            "facturia_matching.padron.taxes.get_tax_name_by_id",
            return_value={1: "P. IIBB CABA", 2: "P. IIBB BA"},
        ):
            with patch(
                "facturia_matching.padron.taxes.resolve_tax_label_to_id",
                side_effect=fake_resolve,
            ):
                with patch("facturia_matching.padron.taxes.is_iva_tax_id", return_value=False):
                    out = otros_impuestos_options_from_odoo()
        self.assertEqual(
            out,
            ["Percepción IIBB CABA Sufrida", "Percepción IIBB ARBA Sufrida"],
        )

    def test_appends_non_iva_odoo_taxes_not_in_constant(self):
        """Impuestos purchase del tenant (p.ej. Aliare Perc Gananc) se agregan dinámicamente."""

        def fake_resolve(label: str):
            mapping = {
                "Percepción IIBB CABA Sufrida": 1,
                "Percepción IIBB CABA Aplicada": 1,
            }
            return mapping.get(label)

        name_by_id = {
            1: "P. IIBB CABA",
            29: "Perc Gananc",
            72: "Perc IVA",
            25: "Other taxes",
            65: "IVA 21%",
        }

        def fake_is_iva(tid: int) -> bool:
            return int(tid) == 65

        with patch("facturia_matching.padron.taxes.get_tax_name_by_id", return_value=name_by_id):
            with patch(
                "facturia_matching.padron.taxes.resolve_tax_label_to_id",
                side_effect=fake_resolve,
            ):
                with patch(
                    "facturia_matching.padron.taxes.is_iva_tax_id",
                    side_effect=fake_is_iva,
                ):
                    out = otros_impuestos_options_from_odoo()

        self.assertEqual(out[0], "Percepción IIBB CABA Sufrida")
        self.assertIn("Other taxes", out)
        self.assertIn("Perc Gananc", out)
        self.assertIn("Perc IVA", out)
        self.assertNotIn("IVA 21%", out)
        extras = out[1:]
        self.assertEqual(extras, sorted(extras, key=str.upper))


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


if __name__ == "__main__":
    unittest.main()
