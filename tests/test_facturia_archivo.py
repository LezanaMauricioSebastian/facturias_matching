"""Tests de resolución de archivo original FacturIA."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from facturia_matching.facturia.archivo import (
    archivo_paths_by_comprobante,
    attach_facturia_archivo,
    build_facturia_file_url,
    guess_content_type,
    normalize_archivo_path,
    pick_archivo_raw,
)


class TestPickAndNormalize(unittest.TestCase):
    def test_pick_archivo_original(self):
        j = {"archivo_original": "conversion/5/79/a.pdf", "factura": {"file_name": "other.pdf"}}
        self.assertEqual(pick_archivo_raw(j), "conversion/5/79/a.pdf")

    def test_pick_file_name_fallback(self):
        j = {"factura": {"file_name": "Escaneado.pdf"}}
        self.assertEqual(pick_archivo_raw(j), "Escaneado.pdf")

    def test_normalize_full_path(self):
        self.assertEqual(
            normalize_archivo_path("conversion/5/79/a.pdf"),
            "conversion/5/79/a.pdf",
        )

    def test_normalize_basename(self):
        self.assertEqual(
            normalize_archivo_path(
                "Escaneado.pdf", company_id=5, process_number=79
            ),
            "conversion/5/79/Escaneado.pdf",
        )

    def test_normalize_rejects_traversal(self):
        self.assertEqual(
            normalize_archivo_path("../etc/passwd", company_id=1, process_number=1),
            "",
        )


class TestPathsByComprobante(unittest.TestCase):
    def test_map(self):
        data = {
            "facturas": [
                {
                    "json": {
                        "archivo_original": "conversion/5/79/a.pdf",
                        "factura": {},
                    }
                },
                {
                    "json": {
                        "factura": {"file_name": "solo.pdf"},
                    }
                },
            ]
        }
        paths = archivo_paths_by_comprobante(
            data, company_id=5, process_number=79
        )
        self.assertEqual(paths[0], "conversion/5/79/a.pdf")
        self.assertEqual(paths[1], "conversion/5/79/solo.pdf")


class TestBuildUrl(unittest.TestCase):
    @patch(
        "facturia_matching.facturia.archivo.resolve_file_url_template",
        return_value="",
    )
    def test_no_template(self, _t):
        self.assertIsNone(build_facturia_file_url(path="conversion/5/79/a.pdf"))

    @patch(
        "facturia_matching.facturia.archivo.resolve_facturia_base_url",
        return_value="https://facturia-staging.sudata.co",
    )
    @patch(
        "facturia_matching.facturia.archivo.resolve_file_url_template",
        return_value="{base}/files/{path_encoded}?p={process_number}&i={comprobante_idx}",
    )
    def test_template(self, _t, _b):
        url = build_facturia_file_url(
            path="conversion/5/79/a.pdf",
            process_number=79,
            company_id=5,
            comprobante_idx=0,
        )
        self.assertEqual(
            url,
            "https://facturia-staging.sudata.co/files/conversion/5/79/a.pdf?p=79&i=0",
        )


class TestGuessContentType(unittest.TestCase):
    def test_pdf(self):
        self.assertEqual(guess_content_type("a.pdf"), "application/pdf")

    def test_jpeg(self):
        self.assertEqual(guess_content_type("a.jpeg"), "image/jpeg")


class TestAttach(unittest.TestCase):
    @patch("facturia_matching.persistence.back_check.get_process")
    def test_attach_fills_first_row(self, mock_get):
        mock_get.return_value = {
            "company_id": 5,
            "process_number": 79,
            "json_data": (
                '{"facturas":[{"json":{"archivo_original":"conversion/5/79/a.pdf",'
                '"factura":{"items":[{}]}}}]}'
            ),
        }
        rows = [
            {"__comprobante_idx": 0, "invoice_line_ids/name": "a"},
            {"__comprobante_idx": 0, "invoice_line_ids/name": "b"},
        ]
        out = attach_facturia_archivo(rows, "79")
        self.assertEqual(out[0]["__fac_archivo"], "conversion/5/79/a.pdf")
        self.assertNotIn("__fac_archivo", out[1])


if __name__ == "__main__":
    unittest.main()
