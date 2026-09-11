"""Unit tests for Excel/Sheets padron matching and CSV/XLSX parsing."""

import io
import json
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


class TestGoogleSheetsHelpers(unittest.TestCase):
    def test_extract_spreadsheet_id_from_edit_url(self):
        from facturia_matching.padron.google_sheets import extract_gid, extract_spreadsheet_id

        url = "https://docs.google.com/spreadsheets/d/1klqwF-8c-xnXvHB1GJ2f8x9vOoJi4-PB-HavIh1wULA/edit?gid=1583130206#gid=1583130206"
        self.assertEqual(
            extract_spreadsheet_id(url),
            "1klqwF-8c-xnXvHB1GJ2f8x9vOoJi4-PB-HavIh1wULA",
        )
        self.assertEqual(extract_gid(url), "1583130206")

    def test_publish_url_has_no_spreadsheet_id(self):
        from facturia_matching.padron.google_sheets import extract_spreadsheet_id

        pub = (
            "https://docs.google.com/spreadsheets/d/e/"
            "2PACX-1vSJSetlpFQzy56oT9Ek3lecPKvnGKcgLLAsLwKGNUHQWEaPt5K6Qs78lFb4f5Nm0d5-vqHDnACOsUXm"
            "/pub?output=csv"
        )
        self.assertIsNone(extract_spreadsheet_id(pub))

    def test_a1_sheet_range_quotes_spaces(self):
        from facturia_matching.padron.google_sheets import _a1_sheet_range

        self.assertEqual(_a1_sheet_range("Proveedores"), "Proveedores!1:1")
        self.assertEqual(_a1_sheet_range("Forma de pago"), "'Forma de pago'!1:1")
        self.assertEqual(_a1_sheet_range("O'Brien"), "'O''Brien'!1:1")

    def test_list_spreadsheet_sheets_parses_api(self):
        from unittest.mock import patch

        from facturia_matching.padron import google_sheets as gs

        fake = {
            "properties": {"title": "Padron"},
            "sheets": [
                {"properties": {"sheetId": 10, "title": "B", "index": 1}},
                {"properties": {"sheetId": 5, "title": "A", "index": 0}},
            ],
        }
        with patch.object(gs, "service_account_configured", return_value=True), patch.object(
            gs, "_sheets_api_get", return_value=fake
        ):
            out = gs.list_spreadsheet_sheets("abc123sidxxxxxxxx")
        self.assertEqual(out["title"], "Padron")
        self.assertEqual([s["title"] for s in out["sheets"]], ["A", "B"])
        self.assertEqual(out["sheets"][0]["gid"], "5")

    def test_fetch_first_row_by_gid(self):
        from unittest.mock import patch

        from facturia_matching.padron import google_sheets as gs

        meta = {
            "spreadsheet_id": "sid",
            "title": "Padron",
            "sheets": [
                {"title": "Proveedores", "sheet_id": 99, "gid": "99", "index": 0},
            ],
        }
        values_resp = {"values": [["Mes", "Sucursal", "Proveedores", "", "CUIT"]]}
        with patch.object(gs, "service_account_configured", return_value=True), patch.object(
            gs, "list_spreadsheet_sheets", return_value=meta
        ), patch.object(gs, "_sheets_api_get", return_value=values_resp):
            out = gs.fetch_first_row("sid", sheet_gid="99")
        self.assertEqual(out["sheet_title"], "Proveedores")
        self.assertEqual(out["values"], ["Mes", "Sucursal", "Proveedores", "CUIT"])
        self.assertEqual(out["count"], 4)
    def test_map_factura(self):
        from facturia_matching.padron.process_to_invoice import (
            factura_to_invoice_input,
            invoices_from_process_row,
        )

        fac = {
            "proveedor": {"razon_social": "Carrefour", "cuit": "30-54668899-9"},
            "forma_de_pago": "Efectivo",
            "tipo_comprobante": "FACTURA A",
            "items": [
                {"descripcion": "Café", "unidad_medida": "kg"},
                {"descripcion": "Leche", "unidad_medida": "l"},
            ],
        }
        inv = factura_to_invoice_input(fac, company_id=7)
        self.assertEqual(inv["proveedor"], "Carrefour")
        self.assertEqual(inv["cuit"], "30-54668899-9")
        self.assertEqual(inv["lineas"], ["Café", "Leche"])
        self.assertEqual(inv["unidades_medida"], ["kg", "l"])
        self.assertEqual(inv["forma_pago"], "Efectivo")
        self.assertEqual(inv["company_id"], 7)

        row = {
            "company_id": 3,
            "json_data": json.dumps(
                {"facturas": [{"json": {"factura": fac}}]},
                ensure_ascii=False,
            ),
        }
        drafts = invoices_from_process_row(row)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["company_id"], 3)
        self.assertEqual(drafts[0]["lineas"], ["Café", "Leche"])


if __name__ == "__main__":
    unittest.main()
