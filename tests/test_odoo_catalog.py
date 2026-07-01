"""Unit tests: catálogo Odoo (cuentas, tipos de documento)."""
import unittest

from facturia_matching.odoo.catalog import (
    build_account_maps,
    build_doc_type_label_map,
    resolve_account_id,
)
from facturia_matching.odoo.document_types_i18n import (
    localize_latam_document_type_name,
    prepare_document_types_for_ui,
)

MOCK_ACCOUNTS = [
    {"id": 184, "code": "5.3.1.01.110", "name": "Honorarios Administración"},
    {"id": 341, "code": "5.3.1.01.031", "name": "Gastos de Oficina"},
]


class TestResolveAccountId(unittest.TestCase):
    def setUp(self):
        self.maps = build_account_maps(MOCK_ACCOUNTS)

    def _resolve(self, raw: str) -> str:
        return resolve_account_id(raw, MOCK_ACCOUNTS, self.maps, min_score=65.0)

    def test_codigo_y_nombre_correctos(self):
        self.assertEqual(self._resolve("5.3.1.01.110 Honorarios Administración"), "184")

    def test_solo_nombre(self):
        self.assertEqual(self._resolve("Honorarios Administración"), "184")

    def test_codigo_incorrecto_nombre_correcto_riquelme(self):
        self.assertEqual(self._resolve("5.3.1.01.031 Honorarios Administración"), "184")

    def test_codigo_y_nombre_gastos_oficina(self):
        self.assertEqual(self._resolve("5.3.1.01.031 Gastos de Oficina"), "341")


class TestDocumentTypeLocalization(unittest.TestCase):
    def test_invoices_a_to_facturas_a(self):
        self.assertEqual(localize_latam_document_type_name("INVOICES A"), "FACTURAS A")

    def test_spanish_name_unchanged(self):
        self.assertEqual(localize_latam_document_type_name("FACTURAS B"), "FACTURAS B")

    def test_prepare_preserves_afip_code(self):
        rows = prepare_document_types_for_ui(
            [{"id": 1, "name": "INVOICES A", "code": "1"}]
        )
        self.assertEqual(rows[0]["name"], "FACTURAS A")
        self.assertEqual(rows[0]["code"], "1")

    def test_prepare_keeps_odoo_spanish_names(self):
        rows = prepare_document_types_for_ui(
            [{"id": 1, "name": "FACTURAS A", "code": "1"}]
        )
        self.assertEqual(rows[0]["name"], "FACTURAS A")

    def test_label_map_from_english_odoo_names(self):
        doc_types = [
            {"id": 1, "name": "FACTURAS A", "code": "1"},
            {"id": 6, "name": "FACTURAS B", "code": "6"},
            {"id": 11, "name": "FACTURAS C", "code": "11"},
            {"id": 73, "name": "OC-X", "code": "99"},
        ]
        m = build_doc_type_label_map(doc_types)
        self.assertEqual(m["FACTURAS A"], 1)
        self.assertEqual(m["FACTURAS B"], 6)
        self.assertEqual(m["FACTURAS C"], 11)
        self.assertEqual(m["OC-X"], 73)


if __name__ == "__main__":
    unittest.main()
