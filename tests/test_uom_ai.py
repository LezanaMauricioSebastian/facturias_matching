"""Tests for Claude-backed UoM suggestion (uom_ai)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from facturia_matching.odoo.purchase_matching import uom_ai
from facturia_matching.odoo.purchase_matching.uom_ai import (
    _build_prompt,
    _parse_uom_id,
    clear_uom_ai_cache,
    is_uom_ai_enabled,
    suggest_uom,
)


class TestUomAiHelpers(unittest.TestCase):
    def setUp(self) -> None:
        clear_uom_ai_cache()

    def tearDown(self) -> None:
        clear_uom_ai_cache()

    def test_parse_uom_id_first_valid(self):
        self.assertEqual(_parse_uom_id("42", {1, 42, 7}), 42)
        self.assertEqual(_parse_uom_id("ID 7: Paquete de 6", {1, 7}), 7)
        self.assertEqual(_parse_uom_id("Elijo 99 porque ... 7", {1, 7}), 7)
        self.assertIsNone(_parse_uom_id("ninguna", {1, 7}))
        self.assertIsNone(_parse_uom_id("3", {1, 7}))

    def test_build_prompt_includes_context(self):
        prompt = _build_prompt(
            partner_name="Distribuidora Sur SA",
            product_label="ACEITE GIRASOL X 6",
            uoms=[
                {"id": 1, "name": "Unidades"},
                {"id": 7, "name": "Paquete de 6"},
            ],
        )
        self.assertIn("gastronómica", prompt)
        self.assertIn("Distribuidora Sur SA", prompt)
        self.assertIn("ACEITE GIRASOL X 6", prompt)
        self.assertIn("ID 1: Unidades", prompt)
        self.assertIn("ID 7: Paquete de 6", prompt)
        self.assertIn("SOLO con el número de ID", prompt)


class TestUomAiSuggest(unittest.TestCase):
    def setUp(self) -> None:
        clear_uom_ai_cache()

    def tearDown(self) -> None:
        clear_uom_ai_cache()

    def test_disabled_without_flag(self):
        with patch.dict(
            "os.environ",
            {"FACTURIA_UOM_AI_ENABLED": "0", "ANTHROPIC_API_KEY": "sk-test"},
            clear=False,
        ):
            self.assertFalse(is_uom_ai_enabled())
            with patch.object(uom_ai, "_call_claude") as mock_call:
                out = suggest_uom(
                    product_id=10,
                    product_label="ACEITE X 6",
                    partner_name="Prov",
                    uoms=[{"id": 1, "name": "Unidades"}, {"id": 7, "name": "Paquete de 6"}],
                )
            self.assertIsNone(out)
            mock_call.assert_not_called()

    def test_disabled_without_api_key(self):
        with patch.dict(
            "os.environ",
            {"FACTURIA_UOM_AI_ENABLED": "1", "ANTHROPIC_API_KEY": ""},
            clear=False,
        ):
            # env_strip returns "" for empty; ensure key is missing/empty
            with patch(
                "facturia_matching.odoo.purchase_matching.uom_ai.env_strip",
                side_effect=lambda k, d="": (
                    "1" if k == "FACTURIA_UOM_AI_ENABLED" else ""
                ),
            ):
                self.assertFalse(is_uom_ai_enabled())

    def test_suggest_parses_claude_response(self):
        uoms = [
            {"id": 1, "name": "Unidades"},
            {"id": 7, "name": "Paquete de 6"},
        ]
        with patch(
            "facturia_matching.odoo.purchase_matching.uom_ai.is_uom_ai_enabled",
            return_value=True,
        ), patch(
            "facturia_matching.odoo.purchase_matching.uom_ai._call_claude",
            return_value="7",
        ) as mock_call:
            out = suggest_uom(
                product_id=10,
                product_label="ACEITE GIRASOL X 6",
                partner_name="Prov SA",
                uoms=uoms,
            )
        self.assertEqual(out, 7)
        mock_call.assert_called_once()

    def test_suggest_caches_by_product_and_label(self):
        uoms = [
            {"id": 1, "name": "Unidades"},
            {"id": 7, "name": "Paquete de 6"},
        ]
        with patch(
            "facturia_matching.odoo.purchase_matching.uom_ai.is_uom_ai_enabled",
            return_value=True,
        ), patch(
            "facturia_matching.odoo.purchase_matching.uom_ai._call_claude",
            return_value="7",
        ) as mock_call:
            a = suggest_uom(
                product_id=10,
                product_label="ACEITE X 6",
                partner_name="Prov",
                uoms=uoms,
            )
            b = suggest_uom(
                product_id=10,
                product_label="aceite x 6",
                partner_name="Otro",
                uoms=uoms,
            )
        self.assertEqual(a, 7)
        self.assertEqual(b, 7)
        mock_call.assert_called_once()

    def test_suggest_fallback_on_api_error(self):
        uoms = [
            {"id": 1, "name": "Unidades"},
            {"id": 7, "name": "Paquete de 6"},
        ]
        with patch(
            "facturia_matching.odoo.purchase_matching.uom_ai.is_uom_ai_enabled",
            return_value=True,
        ), patch(
            "facturia_matching.odoo.purchase_matching.uom_ai._call_claude",
            side_effect=RuntimeError("network"),
        ):
            out = suggest_uom(
                product_id=10,
                product_label="ACEITE X 6",
                partner_name="Prov",
                uoms=uoms,
            )
        self.assertIsNone(out)

    def test_suggest_skips_single_option(self):
        with patch(
            "facturia_matching.odoo.purchase_matching.uom_ai.is_uom_ai_enabled",
            return_value=True,
        ), patch(
            "facturia_matching.odoo.purchase_matching.uom_ai._call_claude",
        ) as mock_call:
            out = suggest_uom(
                product_id=10,
                product_label="ACEITE",
                partner_name="Prov",
                uoms=[{"id": 1, "name": "Unidades"}],
            )
        self.assertIsNone(out)
        mock_call.assert_not_called()

    def test_suggest_invalid_response_returns_none(self):
        uoms = [
            {"id": 1, "name": "Unidades"},
            {"id": 7, "name": "Paquete de 6"},
        ]
        with patch(
            "facturia_matching.odoo.purchase_matching.uom_ai.is_uom_ai_enabled",
            return_value=True,
        ), patch(
            "facturia_matching.odoo.purchase_matching.uom_ai._call_claude",
            return_value="no sé",
        ):
            out = suggest_uom(
                product_id=10,
                product_label="ACEITE X 6",
                partner_name="Prov",
                uoms=uoms,
            )
        self.assertIsNone(out)


class TestResolveTargetUomAi(unittest.TestCase):
    """Integración: _resolve_target_uom_for_product consulta IA antes del default."""

    def setUp(self) -> None:
        clear_uom_ai_cache()

    def tearDown(self) -> None:
        clear_uom_ai_cache()

    def _unit_catalog(self):
        return {
            "by_id": {
                1: {
                    "id": 1,
                    "name": "Unidades",
                    "factor": 1.0,
                    "category_id": [1, "Unidad"],
                    "uom_type": "reference",
                },
                7: {
                    "id": 7,
                    "name": "Paquete de 6",
                    "factor": 0.166667,
                    "category_id": [1, "Unidad"],
                    "uom_type": "bigger",
                },
            },
            "by_name": {},
        }

    def test_ai_overrides_default_units(self):
        from facturia_matching.odoo.purchase_matching import _resolve_target_uom_for_product

        catalog = self._unit_catalog()
        ai_meta: dict = {}
        with patch(
            "facturia_matching.odoo.purchase_matching._product_default_uom_id",
            return_value=1,
        ), patch(
            "facturia_matching.odoo.purchase_matching.uom_ai.suggest_uom",
            return_value=7,
        ) as mock_ai:
            to_uom = _resolve_target_uom_for_product(
                99,
                catalog,
                invoice_um_raw="",
                product_label="ACEITE GIRASOL X 6",
                partner_name="Prov SA",
                ai_meta=ai_meta,
            )
        self.assertEqual(int(to_uom["id"]), 7)
        self.assertTrue(ai_meta.get("suggested"))
        mock_ai.assert_called_once()

    def test_manual_target_skips_ai(self):
        from facturia_matching.odoo.purchase_matching import _resolve_target_uom_for_product

        catalog = self._unit_catalog()
        with patch(
            "facturia_matching.odoo.purchase_matching._product_default_uom_id",
            return_value=1,
        ), patch(
            "facturia_matching.odoo.purchase_matching.uom_ai.suggest_uom",
        ) as mock_ai:
            to_uom = _resolve_target_uom_for_product(
                99,
                catalog,
                target_uom_id=1,
                product_label="ACEITE X 6",
                partner_name="Prov",
            )
        self.assertEqual(int(to_uom["id"]), 1)
        mock_ai.assert_not_called()

    def test_apply_scaling_stamps_ai_note(self):
        from facturia_matching.odoo.purchase_matching import _apply_uom_scaling_for_product

        catalog = self._unit_catalog()
        row = {
            "invoice_line_ids/name": "ACEITE GIRASOL X 6",
            "Nombre de Proveedor": "Prov SA",
            "invoice_line_ids/quantity": "2",
        }
        with patch(
            "facturia_matching.odoo.purchase_matching._product_default_uom_id",
            return_value=1,
        ), patch(
            "facturia_matching.odoo.purchase_matching.uom_ai.suggest_uom",
            return_value=7,
        ):
            info = _apply_uom_scaling_for_product(
                row,
                invoice_qty=2.0,
                invoice_um_raw="",
                product_id=99,
                uom_catalog=catalog,
            )
        self.assertEqual(info.get("um_empresa_id"), "7")
        self.assertIn("UM sugerida por IA", info.get("um_note") or "")


if __name__ == "__main__":
    unittest.main()
