"""Unit tests for Excel/Sheets padron matching and CSV/XLSX parsing."""

import io
import unittest
from pathlib import Path

from facturia_matching.padron.excel import match_producto, match_proveedor_excel, um_matches
from facturia_matching.padron.sheet_loader import parse_file_bytes, rows_to_productos, rows_to_proveedores

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestMatchProveedorExcel(unittest.TestCase):
    def setUp(self):
        self.padron = [
            {"razon_social": "Carrefour Argentina S.A.", "nombre_fantasia": "Carrefour", "cuit": "30-54668899-9"},
            {"razon_social": "Distribuidora Claudio", "nombre_fantasia": "Claudio", "cuit": "20123456789"},
            {"razon_social": "DPEC", "nombre_fantasia": "", "cuit": "30701234567"},
        ]

    def test_cuit_exact(self):
        hit = match_proveedor_excel("", "30546688999", self.padron)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["score"], 100.0)
        self.assertEqual(hit["match"], "Carrefour Argentina S.A.")
        self.assertEqual(hit["nombre_fantasia"], "Carrefour")

    def test_fuzzy_fantasia(self):
        hit = match_proveedor_excel("carrefur", "", self.padron)
        self.assertIsNotNone(hit)
        self.assertGreaterEqual(hit["score"], 72)
        self.assertIn("Carrefour", (hit["match"], hit["nombre_fantasia"]))

    def test_no_match(self):
        hit = match_proveedor_excel("xyz-no-existe-123", "", self.padron)
        self.assertIsNone(hit)


class TestMatchProducto(unittest.TestCase):
    def setUp(self):
        self.productos = [
            {"nombre": "Café tostado", "unidad_medida": "kg"},
            {"nombre": "Servicio de limpieza", "unidad_medida": "un"},
            {"nombre": "Agua mineral", "unidad_medida": "l"},
        ]

    def test_name_and_um(self):
        hit = match_producto("cafe tostado", "kilos", self.productos)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["match"], "Café tostado")
        self.assertEqual(hit["unidad_medida"], "kg")
        self.assertTrue(hit["um_match"])

    def test_um_mismatch(self):
        hit = match_producto("cafe tostado", "litro", self.productos)
        self.assertIsNotNone(hit)
        self.assertFalse(hit["um_match"])

    def test_um_aliases(self):
        self.assertTrue(um_matches("uds", "unidad"))
        self.assertTrue(um_matches("lt", "l"))
        self.assertFalse(um_matches("kg", "l"))


class TestParsePadronFiles(unittest.TestCase):
    def test_csv_proveedores_fixture(self):
        data = (FIXTURES / "padron_proveedores.csv").read_bytes()
        rows = parse_file_bytes(data, "padron_proveedores.csv")
        prov = rows_to_proveedores(rows, "razon_social", "nombre_fantasia", "cuit")
        self.assertEqual(len(prov), 3)
        self.assertEqual(prov[0]["razon_social"], "Carrefour Argentina S.A.")

    def test_csv_productos_fixture(self):
        data = (FIXTURES / "padron_productos.csv").read_bytes()
        rows = parse_file_bytes(data, "padron_productos.csv")
        prods = rows_to_productos(rows, "nombre", "unidad_medida")
        self.assertEqual(len(prods), 3)
        self.assertEqual(prods[0]["unidad_medida"], "kg")

    def test_xlsx_roundtrip(self):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(["nombre", "unidad_medida"])
        ws.append(["Pan", "kg"])
        buf = io.BytesIO()
        wb.save(buf)
        rows = parse_file_bytes(buf.getvalue(), "prod.xlsx")
        prods = rows_to_productos(rows, "nombre", "unidad_medida")
        self.assertEqual(prods, [{"nombre": "Pan", "unidad_medida": "kg"}])


if __name__ == "__main__":
    unittest.main()
