"""Unit tests: montos IVA y percepciones a nivel comprobante (muestra proceso 216)."""
import unittest

from app import (
    _apply_fac_percepciones_to_row,
    _fac_iva_monto_str,
    _format_amount_for_odoo_csv,
    _parse_amount,
    _rows_prepared_for_odoo_csv,
)
from padron_taxes import build_csv_tax_ids_dot_id


FAC_216 = {
    "subtotal": 272644.68,
    "iva_21": 57255.38,
    "percepcion_iibb": 3344.38,
    "total": 333444.44,
}


class TestFacAmounts(unittest.TestCase):
    def test_parse_amount(self):
        self.assertAlmostEqual(_parse_amount("3344,38"), 3344.38)
        self.assertAlmostEqual(_parse_amount(57255.38), 57255.38)

    def test_fac_iva_monto_str_sums_rates(self):
        self.assertEqual(_fac_iva_monto_str(FAC_216), "57255.38")

    def test_apply_fac_percepciones_monto_only(self):
        row: dict = {"otros_impuestos": "", "otros_impuestos_monto": ""}
        _apply_fac_percepciones_to_row(FAC_216, row)
        self.assertEqual(row["otros_impuestos_monto"], "3344.38")
        self.assertEqual(row["otros_impuestos"], "")
        self.assertEqual(len(row["__fac_percepciones"]), 1)

    def test_build_csv_tax_ids_iva_only(self):
        row = {"iva_pct": "21"}
        self.assertEqual(build_csv_tax_ids_dot_id(row), "63")

    def test_format_amount_for_odoo_csv_es_ar(self):
        self.assertEqual(_format_amount_for_odoo_csv("1.000,50", money=True), "1000.50")
        self.assertEqual(_format_amount_for_odoo_csv("1.657.755"), "1657755")
        self.assertEqual(_format_amount_for_odoo_csv("45.000"), "45000")
        self.assertEqual(_format_amount_for_odoo_csv("82.000,52", money=True), "82000.52")

    def test_rows_prepared_propagate_partner(self):
        rows = [
            {"__comprobante_idx": 1, "partner_id": "99", "l10n_latam_document_number": "00001-1"},
            {"__comprobante_idx": 1, "partner_id": "", "l10n_latam_document_number": ""},
        ]
        out = _rows_prepared_for_odoo_csv(rows)
        self.assertEqual(out[1]["partner_id"], "99")

    def test_build_csv_tax_ids_iva_and_percepcion(self):
        row = {
            "iva_pct": "21",
            "otros_impuestos": "Percepción IIBB CABA Sufrida",
        }
        # ID 1 = CABA en catálogo Odoo del proyecto
        cell = build_csv_tax_ids_dot_id(row)
        self.assertIn("63", cell.split(","))
        if cell.count(",") >= 1:
            parts = cell.split(",")
            self.assertTrue(any(p == "1" for p in parts), cell)


if __name__ == "__main__":
    unittest.main()
