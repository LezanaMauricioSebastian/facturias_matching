"""Unit tests: resolución de cuenta contable padrón → Odoo account_id."""
import unittest

from odoo_catalog import build_account_maps, resolve_account_id

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


if __name__ == "__main__":
    unittest.main()
