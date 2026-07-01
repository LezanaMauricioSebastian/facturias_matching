"""Tests: otros_impuestos_options filtradas por catálogo Odoo."""
import unittest
from unittest.mock import patch

from facturia_matching.core.options import otros_impuestos_options_from_odoo


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

        with patch("facturia_matching.padron.taxes.get_tax_name_by_id", return_value={1: "x", 2: "y"}):
            with patch("facturia_matching.padron.taxes.resolve_tax_label_to_id", side_effect=fake_resolve):
                out = otros_impuestos_options_from_odoo()
        self.assertEqual(
            out,
            ["Percepción IIBB CABA Sufrida", "Percepción IIBB ARBA Sufrida"],
        )


if __name__ == "__main__":
    unittest.main()
