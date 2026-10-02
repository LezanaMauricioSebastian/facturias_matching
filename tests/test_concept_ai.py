"""Tests: historial Gastos + sugerencia Concepto/Categoría (concept_ai)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from facturia_matching.padron import concept_ai, gastos_history
from facturia_matching.padron.concept_ai import (
    clear_concept_ai_cache,
    is_concept_ai_enabled,
    suggest_concepto_categoria_batch,
)
from facturia_matching.padron.gastos_history import (
    clear_gastos_history_cache,
    detect_gastos_header,
    parse_gastos_records,
    top_k_examples,
    unique_categorias,
)


class TestGastosHistoryParse(unittest.TestCase):
    def setUp(self) -> None:
        clear_gastos_history_cache()

    def tearDown(self) -> None:
        clear_gastos_history_cache()

    def test_detect_header_skips_title_rows(self):
        raw = [
            ["GASTOS 2026", "", "", ""],
            ["", "filtro", "", ""],
            [
                "Mes",
                "Sucursal",
                "Proveedor",
                "Concepto",
                "Fecha",
                "Monto",
                "Categoría gasto",
                "Observación",
            ],
            ["Enero", "Palermo", "TONUTTI", "Helados", "2026-01-10", "1000", "Gastos Var", "CREMOSO"],
        ]
        detected = detect_gastos_header(raw)
        self.assertIsNotNone(detected)
        idx, cols = detected  # type: ignore[misc]
        self.assertEqual(idx, 2)
        self.assertEqual(cols["proveedor"], 2)
        self.assertEqual(cols["concepto"], 3)
        self.assertEqual(cols["categoria"], 6)

    def test_parse_records_and_unique_categorias(self):
        raw = [
            ["junk"],
            [
                "Proveedor",
                "Concepto",
                "Categoría gasto",
                "Observación",
            ],
            ["TONUTTI SA", "Helados", "Gastos Var", "CREMOSO X12"],
            ["TONUTTI SA", "Helados", "Gastos Var", ""],
            ["EDESUR", "Luz", "Gastos Fijos", ""],
            ["", "", "", ""],
        ]
        records = parse_gastos_records(raw)
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["proveedor"], "TONUTTI SA")
        self.assertEqual(records[0]["concepto"], "Helados")
        self.assertEqual(unique_categorias(records), ["Gastos Var", "Gastos Fijos"])

    def test_top_k_prefers_same_proveedor(self):
        records = [
            {
                "proveedor": "Otro SA",
                "concepto": "X",
                "categoria": "Gastos Var",
                "descripcion": "",
            },
            {
                "proveedor": "TONUTTI SA",
                "concepto": "Helados",
                "categoria": "Gastos Var",
                "descripcion": "CREMOSO",
            },
            {
                "proveedor": "TONUTTI SA",
                "concepto": "Postres",
                "categoria": "Gastos Var",
                "descripcion": "FLAN",
            },
        ]
        out = top_k_examples(records, proveedor="TONUTTI SA", descripcion="cremoso kg", k=5)
        self.assertGreaterEqual(len(out), 1)
        self.assertEqual(out[0]["concepto"], "Helados")
        self.assertTrue(all("TONUTTI" in (r["proveedor"] or "").upper() for r in out[:2]))

    def test_infer_categoria_from_history(self):
        from facturia_matching.padron.gastos_history import (
            canonicalize_categoria,
            infer_categoria,
        )

        self.assertEqual(canonicalize_categoria("gastos variables"), "Gastos Var")
        self.assertEqual(canonicalize_categoria("Fijo"), "Gastos Fijos")
        records = [
            {
                "proveedor": "TONUTTI",
                "concepto": "Insumos",
                "categoria": "Gastos Var",
                "descripcion": "",
            },
            {
                "proveedor": "TONUTTI",
                "concepto": "Insumos",
                "categoria": "Gastos Var",
                "descripcion": "",
            },
            {
                "proveedor": "OTRO",
                "concepto": "Insumos",
                "categoria": "Gastos Fijos",
                "descripcion": "",
            },
        ]
        self.assertEqual(
            infer_categoria(records, concepto="Insumos", proveedor="TONUTTI"),
            "Gastos Var",
        )

    def test_dominant_concepto_majority(self):
        from facturia_matching.padron.gastos_history import dominant_concepto

        records = [
            {"proveedor": "Meso", "concepto": "Panificados", "categoria": "CMV", "descripcion": ""},
            {"proveedor": "Meso", "concepto": "Panificados", "categoria": "CMV", "descripcion": ""},
            {"proveedor": "Meso", "concepto": "Otros", "categoria": "CMV", "descripcion": ""},
            {"proveedor": "TONUTTI SA", "concepto": "Insumos", "categoria": "CMV", "descripcion": ""},
        ]
        self.assertEqual(
            dominant_concepto(records, proveedor="Meso", allowed=["Panificados", "Otros", "Insumos"]),
            "Panificados",
        )
        self.assertEqual(
            dominant_concepto(records, proveedor="TONUTTI", allowed=["Insumos", "Otros"]),
            "Insumos",
        )
        self.assertEqual(dominant_concepto(records, proveedor="NADIE"), "")


class TestConceptAi(unittest.TestCase):
    def setUp(self) -> None:
        clear_concept_ai_cache()

    def tearDown(self) -> None:
        clear_concept_ai_cache()

    def test_disabled_without_flag(self):
        with patch.dict(
            "os.environ",
            {"FACTURIA_CONCEPT_AI_ENABLED": "0", "DEEPSEEK_API_KEY": "sk-test"},
            clear=False,
        ):
            self.assertFalse(is_concept_ai_enabled())
            with patch.object(concept_ai, "_call_deepseek") as mock_call:
                out = suggest_concepto_categoria_batch(
                    company_id=0,
                    proveedor="TONUTTI",
                    lines=[{"descripcion": "CREMOSO X12"}],
                    conceptos=["Helados", "Luz"],
                    categorias=["Gastos Fijos", "Gastos Var"],
                )
            self.assertEqual(out, [None])
            mock_call.assert_not_called()

    def test_batch_validates_against_lists(self):
        with patch.dict(
            "os.environ",
            {"FACTURIA_CONCEPT_AI_ENABLED": "1", "DEEPSEEK_API_KEY": "sk-test"},
            clear=False,
        ):
            with patch.object(
                concept_ai,
                "_call_deepseek",
                return_value='[{"i":0,"concepto":"Helados","categoria":"Gastos Var"},'
                '{"i":1,"concepto":"Inventado","categoria":"Gastos Fijos"}]',
            ) as mock_call:
                out = suggest_concepto_categoria_batch(
                    company_id=0,
                    proveedor="TONUTTI",
                    lines=[
                        {"descripcion": "CREMOSO X12"},
                        {"descripcion": "ALGO RARO"},
                    ],
                    conceptos=["Helados", "Luz"],
                    categorias=["Gastos Fijos", "Gastos Var"],
                    examples=[
                        {
                            "proveedor": "TONUTTI",
                            "concepto": "Helados",
                            "categoria": "Gastos Var",
                        }
                    ],
                )
            mock_call.assert_called_once()
            self.assertEqual(
                out[0], {"concepto": "Helados", "categoria": "Gastos Var"}
            )
            # concepto inventado → descartado
            self.assertIsNone(out[1])

    def test_cache_avoids_second_call(self):
        with patch.dict(
            "os.environ",
            {"FACTURIA_CONCEPT_AI_ENABLED": "1", "DEEPSEEK_API_KEY": "sk-test"},
            clear=False,
        ):
            with patch.object(
                concept_ai,
                "_call_deepseek",
                return_value='[{"i":0,"concepto":"Luz","categoria":"Gastos Fijos"}]',
            ) as mock_call:
                a = suggest_concepto_categoria_batch(
                    company_id=1,
                    proveedor="EDESUR",
                    lines=[{"descripcion": "FACTURA LUZ ENERO"}],
                    conceptos=["Luz", "Gas"],
                    categorias=["Gastos Fijos", "Gastos Var"],
                )
                b = suggest_concepto_categoria_batch(
                    company_id=1,
                    proveedor="EDESUR",
                    lines=[{"descripcion": "FACTURA LUZ ENERO"}],
                    conceptos=["Luz", "Gas"],
                    categorias=["Gastos Fijos", "Gastos Var"],
                )
            self.assertEqual(mock_call.call_count, 1)
            self.assertEqual(a, b)
            self.assertEqual(a[0]["concepto"], "Luz")

    def test_prompt_includes_examples_and_lists(self):
        prompt = concept_ai._build_prompt(
            proveedor="TONUTTI",
            lines=[{"descripcion": "CREMOSO"}],
            conceptos=["Helados"],
            categorias=["Gastos Var"],
            examples=[
                {
                    "proveedor": "TONUTTI",
                    "concepto": "Helados",
                    "categoria": "Gastos Var",
                    "descripcion": "crema",
                }
            ],
        )
        self.assertIn("Helados", prompt)
        self.assertIn("Gastos Var", prompt)
        self.assertIn("historial", prompt.lower())
        self.assertIn("CREMOSO", prompt)


if __name__ == "__main__":
    unittest.main()
