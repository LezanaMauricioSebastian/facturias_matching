"""Tests de tax_ids, collect_expected_*, plan_line/tax_line y sync de montos (import Odoo)."""
import unittest

from unittest.mock import patch

from facturia_matching.core.comprobante_tax import classify_comprobante_tax_mode

from facturia_matching.odoo.import_ import (
    _build_line_command,
    _tax_ids_for_odoo_line,
    collect_expected_tax_amounts_from_group,
    plan_line_tax_updates,
    plan_tax_line_amount_overwrites,
)


class TestOdooImport(unittest.TestCase):
    def test_plan_line_tax_updates_by_order(self):
        product_lines = [
            {"id": 10, "name": "Producto A", "tax_ids": [53]},
            {"id": 11, "name": "Producto B", "tax_ids": [53]},
        ]
        rows = [
            {"iva_pct": "21%", "invoice_line_ids/name": "A", "invoice_line_ids/price_unit": "100"},
            {"iva_pct": "10.5%", "invoice_line_ids/name": "B", "invoice_line_ids/price_unit": "50"},
        ]
        updates, warnings = plan_line_tax_updates(product_lines, rows)
        self.assertEqual(len(updates), 2)
        self.assertEqual(updates[0]["line_id"], 10)
        self.assertEqual(updates[0]["new_tax_ids"], [63])
        self.assertEqual(updates[1]["new_tax_ids"], [61])
        self.assertEqual(warnings, [])

    def test_plan_line_tax_updates_clears_when_iva_zero(self):
        product_lines = [
            {"id": 10, "name": "A", "tax_ids": [63]},
            {"id": 11, "name": "B", "tax_ids": [61]},
        ]
        rows = [
            {"iva_pct": "21%", "invoice_line_ids/name": "A", "invoice_line_ids/price_unit": "100"},
            {"iva_pct": "0", "invoice_line_ids/name": "B", "invoice_line_ids/price_unit": "50"},
        ]
        updates, warnings = plan_line_tax_updates(product_lines, rows)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["line_id"], 11)
        self.assertEqual(updates[0]["new_tax_ids"], [])
        self.assertEqual(warnings, [])

    def test_tax_ids_for_odoo_line_header_mode_strips_iva(self):
        group = [
            {
                "iva_pct": "0",
                "invoice_line_ids/name": "A",
                "invoice_line_ids/price_unit": "100",
                "__fac_iva_monto": "500",
            },
            {"iva_pct": "0", "invoice_line_ids/name": "B", "invoice_line_ids/price_unit": "50"},
        ]
        self.assertEqual(classify_comprobante_tax_mode(group), "header")
        self.assertEqual(_tax_ids_for_odoo_line(group[0], group), [])
        self.assertEqual(_tax_ids_for_odoo_line(group[1], group), [])

    def test_tax_ids_for_odoo_line_mixed_mode_only_lines_with_rate(self):
        group = [
            {
                "iva_pct": "21",
                "otros_impuestos": "Percepción Ganancias Sufrida",
                "_padron_other_tax_ids": ["27"],
                "invoice_line_ids/name": "A",
                "invoice_line_ids/price_unit": "100",
                "__fac_iva_monto": "500",
            },
            {"iva_pct": "0", "invoice_line_ids/name": "B", "invoice_line_ids/price_unit": "50"},
        ]
        with patch("facturia_matching.padron.taxes.resolve_tax_label_to_id", return_value=27):
            line_a = _tax_ids_for_odoo_line(group[0], group)
            line_b = _tax_ids_for_odoo_line(group[1], group)
        self.assertEqual(line_a, [63, 27])
        self.assertEqual(line_b, [])

    def test_tax_ids_otros_respected_per_line(self):
        """Cada fila conserva su propio otros_impuestos al armar tax_ids Odoo."""
        group = [
            {
                "iva_pct": "21",
                "otros_impuestos": "Percepción IIBB Chaco Sufrida",
                "invoice_line_ids/name": "COCA-COLA",
                "invoice_line_ids/price_unit": "100",
                "invoice_line_ids/quantity": "1",
            },
            {
                "iva_pct": "21",
                "otros_impuestos": "Impuesto Interno",
                "invoice_line_ids/name": "SPRITE",
                "invoice_line_ids/price_unit": "50",
                "invoice_line_ids/quantity": "1",
            },
            {
                "iva_pct": "21",
                "otros_impuestos": "Percepción IVA Sufrida",
                "invoice_line_ids/name": "FANTA",
                "invoice_line_ids/price_unit": "40",
                "invoice_line_ids/quantity": "1",
            },
        ]

        def _resolve(label):
            return {
                "Percepción IIBB Chaco Sufrida": 101,
                "Impuesto Interno": 102,
                "Percepción IVA Sufrida": 103,
            }.get(label)

        with patch("facturia_matching.padron.taxes.resolve_tax_label_to_id", side_effect=_resolve):
            first = _tax_ids_for_odoo_line(group[0], group)
            second = _tax_ids_for_odoo_line(group[1], group)
            third = _tax_ids_for_odoo_line(group[2], group)

        self.assertIn(101, first)
        self.assertNotIn(102, first)
        self.assertNotIn(103, first)
        self.assertIn(102, second)
        self.assertNotIn(101, second)
        self.assertIn(103, third)
        self.assertNotIn(101, third)

    def test_plan_line_tax_updates_salta_stomped_restores_otros_per_line(self):
        """Tras OC Odoo deja todos los tax_ids en cada línea; el plan restaura otros por fila."""
        group = [
            {
                "iva_pct": "21",
                "otros_impuestos": "Percepción IIBB Chaco Sufrida",
                "invoice_line_ids/name": "COCA-COLA",
                "invoice_line_ids/price_unit": "11658,03",
                "invoice_line_ids/quantity": "5",
            },
            {
                "iva_pct": "21",
                "otros_impuestos": "Impuesto Interno",
                "invoice_line_ids/name": "SPRITE",
                "invoice_line_ids/price_unit": "5033,29",
                "invoice_line_ids/quantity": "4",
            },
            {
                "iva_pct": "21",
                "otros_impuestos": "Percepción IVA Sufrida",
                "invoice_line_ids/name": "FANTA",
                "invoice_line_ids/price_unit": "4857,51",
                "invoice_line_ids/quantity": "5",
            },
        ]
        product_lines = [
            {"id": 101, "name": "COCA", "tax_ids": [63, 101, 102, 103]},
            {"id": 102, "name": "SPRITE", "tax_ids": [63, 101, 102, 103]},
            {"id": 103, "name": "FANTA", "tax_ids": [63, 101, 102, 103]},
        ]

        def _resolve(label):
            return {
                "Percepción IIBB Chaco Sufrida": 101,
                "Impuesto Interno": 102,
                "Percepción IVA Sufrida": 103,
            }.get(label)

        def _is_iva(tid):
            return int(tid) == 63

        with patch("facturia_matching.padron.taxes.resolve_tax_label_to_id", side_effect=_resolve), patch(
            "facturia_matching.odoo.import_.taxes.is_iva_tax_id",
            side_effect=_is_iva,
        ), patch(
            "facturia_matching.padron.taxes.is_iva_tax_id",
            side_effect=_is_iva,
        ), patch(
            "facturia_matching.padron.taxes.tax_id_for_csv_export",
            return_value="63",
        ):
            updates, warnings = plan_line_tax_updates(product_lines, group)

        self.assertEqual(warnings, [])
        by_id = {u["line_id"]: set(u["new_tax_ids"]) for u in updates}
        self.assertEqual(by_id[101], {63, 101})
        self.assertEqual(by_id[102], {63, 102})
        self.assertEqual(by_id[103], {63, 103})

    def test_tax_ids_for_odoo_line_mixed_exento_only_on_exento_line(self):
        group = [
            {
                "iva_pct": "IVA Exento",
                "invoice_line_ids/name": "A",
                "invoice_line_ids/price_unit": "100",
                "__fac_iva_monto": "500",
            },
            {"iva_pct": "0", "invoice_line_ids/name": "B", "invoice_line_ids/price_unit": "50"},
        ]
        with patch(
            "facturia_matching.padron.taxes.get_purchase_iva_taxes",
            return_value=[
                {"id": 59, "name": "IVA Exen", "amount": 0.0},
                {"id": 63, "name": "IVA 21%", "amount": 21.0},
            ],
        ):
            line_a = _tax_ids_for_odoo_line(group[0], group)
            line_b = _tax_ids_for_odoo_line(group[1], group)
        self.assertEqual(line_a, [59])
        self.assertEqual(line_b, [])

    def test_build_line_command_clears_taxes_when_iva_zero(self):
        _cmd, _zero, vals = _build_line_command(
            {
                "invoice_line_ids/name": "Sin IVA",
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "50",
                "invoice_line_ids/account_id": "10",
                "iva_pct": "0",
            }
        )
        self.assertEqual(vals["tax_ids"], [(6, 0, [])])

    def test_plan_line_tax_updates_skips_unchanged(self):
        product_lines = [{"id": 10, "name": "X", "tax_ids": [63]}]
        rows = [{"iva_pct": "21%", "invoice_line_ids/name": "X", "invoice_line_ids/price_unit": "1"}]
        updates, _ = plan_line_tax_updates(product_lines, rows)
        self.assertEqual(updates, [])

    def test_collect_expected_tax_amounts_splits_iva_by_rate(self):
        rows = [
            {
                "iva_pct": "21",
                "invoice_line_ids/name": "A",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "33019.55",
            },
            {
                "iva_pct": "10.5",
                "invoice_line_ids/name": "B",
                "invoice_line_ids/quantity": "10",
                "invoice_line_ids/price_unit": "964.37",
            },
            {
                "iva_pct": "21",
                "invoice_line_ids/name": "C",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "13489.27",
            },
        ]
        amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertIn(63, amounts)
        self.assertIn(61, amounts)
        self.assertAlmostEqual(amounts[61], 1012.59, places=2)
        self.assertAlmostEqual(amounts[63], 19533.7, places=1)

    def test_collect_expected_uses_edited_footer_after_reconcile(self):
        from facturia_matching.core.comprobante_tax import reconcile_fac_iva_for_import
        from facturia_matching.odoo.import_ import _prepare_rows_for_import
        from facturia_matching.odoo.api import get_odoo_import_config
        from unittest.mock import patch

        rows = [
            {
                "iva_pct": "21",
                "__fac_iva_montos": '{"21": "2100"}',
                "__fac_iva_monto": "8888",
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/price_unit": "10000",
            }
        ]
        with patch("facturia_matching.padron.taxes.resolve_iva_tax_id_for_pct", return_value=65):
            with patch("facturia_matching.padron.taxes.is_iva_tax_id", return_value=True):
                with patch("facturia_matching.padron.taxes.tax_id_for_csv_export", return_value="65"):
                    cfg = get_odoo_import_config()
                    groups, _ = _prepare_rows_for_import(cfg, rows)
                    amounts = collect_expected_tax_amounts_from_group(groups[0])
        self.assertEqual(amounts.get(65), 8888.0)

    def test_collect_expected_tax_amounts_header_mode(self):
        rows = [
            {
                "iva_pct": "21",
                "__fac_iva_monto": "57255,38",
                "otros_impuestos": "Percepción IIBB CABA Sufrida",
                "otros_impuestos_monto": "150,25",
                "_padron_other_tax_ids": ["1"],
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/price_unit": "10000",
            }
        ]
        amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertEqual(amounts.get(63), 57255.38)
        self.assertIn(1, amounts)
        self.assertEqual(amounts[1], 150.25)

    def test_collect_expected_iibb_from_header_only_row(self):
        rows = [
            {
                "__solo_encabezado": True,
                "iva_pct": "21",
                "__fac_iva_monto": "2100",
                "otros_impuestos": "Percepción IIBB CABA Sufrida",
                "otros_impuestos_monto": "99,50",
                "_padron_other_tax_ids": ["1"],
            },
            {
                "iva_pct": "0",
                "invoice_line_ids/name": "Producto",
                "invoice_line_ids/price_unit": "10000",
            },
        ]
        amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertEqual(amounts.get(63), 2100.0)
        self.assertEqual(amounts.get(1), 99.5)

    def test_collect_expected_otros_unlabeled_slots_map_to_line_labels(self):
        """
        Dinner FA-A 05215-00084885: montos FacturIA en 1ª fila (slots 1/2/3); IIBB /
        Perc IVA / Interno asignados en líneas distintas. Slot 2/3 sin label no deben
        sumarse al IIBB (9154.93+8901.72=18056.65 era el monto que quedaba en Odoo).
        """
        iibb_id, perc_iva_id, interno_id = 16, 20, 30
        rows = [
            {
                "iva_pct": "21",
                "__fac_iva_monto": "62312,04",
                "__fac_iva_montos": '{"21": "62312,04"}',
                "invoice_line_ids/name": "COCA-COLA 600*12",
                "invoice_line_ids/quantity": "10",
                "invoice_line_ids/price_unit": "11658,03",
                "otros_impuestos": "Percepción IIBB Chaco Sufrida",
                "otros_impuestos_monto": "9154.93",
                "otros_impuestos_2_monto": "8901.72",
                "otros_impuestos_3_monto": "18962.88",
                "__fac_percepciones": [
                    {
                        "amount_key": "percepcion_iibb",
                        "monto": "9154.93",
                        "ui_monto_key": "otros_impuestos_monto",
                    },
                    {
                        "amount_key": "percepcion_iva",
                        "monto": "8901.72",
                        "ui_monto_key": "otros_impuestos_2_monto",
                    },
                    {
                        "amount_key": "otros_tributos",
                        "monto": "18962.88",
                        "ui_monto_key": "otros_impuestos_3_monto",
                    },
                ],
            },
            {
                "iva_pct": "21",
                "invoice_line_ids/name": "SPRITE FX LS 500ML",
                "invoice_line_ids/quantity": "10",
                "invoice_line_ids/price_unit": "5033,29",
                "otros_impuestos": "Percepción IVA Sufrida",
            },
            {
                "iva_pct": "21",
                "invoice_line_ids/name": "COCA-COLA ZERO 600*06",
                "invoice_line_ids/quantity": "5",
                "invoice_line_ids/price_unit": "5829,01",
                "otros_impuestos": "Impuesto Interno",
            },
        ]

        def _resolve(label, **_kwargs):
            return {
                "Percepción IIBB Chaco Sufrida": iibb_id,
                "Percepción IVA Sufrida": perc_iva_id,
                "Impuesto Interno": interno_id,
            }.get(str(label or "").strip())

        with patch(
            "facturia_matching.odoo.import_.taxes.resolve_tax_label_to_id",
            side_effect=_resolve,
        ):
            amounts = collect_expected_tax_amounts_from_group(rows)

        self.assertEqual(amounts.get(iibb_id), 9154.93)
        self.assertEqual(amounts.get(perc_iva_id), 8901.72)
        self.assertEqual(amounts.get(interno_id), 18962.88)
        self.assertNotEqual(amounts.get(iibb_id), 18056.65)

    def test_collect_expected_otros_unlabeled_slots_without_fac_percepciones(self):
        """Sin __fac_percepciones: el slot N se mapea al amount_key default y al label del grupo."""
        iibb_id, perc_iva_id, interno_id = 16, 20, 30
        rows = [
            {
                "iva_pct": "21",
                "invoice_line_ids/name": "A",
                "invoice_line_ids/price_unit": "100",
                "otros_impuestos": "Percepción IIBB Chaco Sufrida",
                "otros_impuestos_monto": "10",
                "otros_impuestos_2_monto": "20",
                "otros_impuestos_3_monto": "30",
            },
            {
                "iva_pct": "21",
                "invoice_line_ids/name": "B",
                "invoice_line_ids/price_unit": "100",
                "otros_impuestos": "Percepción IVA Sufrida",
            },
            {
                "iva_pct": "21",
                "invoice_line_ids/name": "C",
                "invoice_line_ids/price_unit": "100",
                "otros_impuestos": "Impuesto Interno",
            },
        ]

        def _resolve(label, **_kwargs):
            return {
                "Percepción IIBB Chaco Sufrida": iibb_id,
                "Percepción IVA Sufrida": perc_iva_id,
                "Impuesto Interno": interno_id,
            }.get(str(label or "").strip())

        with patch(
            "facturia_matching.odoo.import_.taxes.resolve_tax_label_to_id",
            side_effect=_resolve,
        ):
            amounts = collect_expected_tax_amounts_from_group(rows)

        self.assertEqual(amounts.get(iibb_id), 10.0)
        self.assertEqual(amounts.get(perc_iva_id), 20.0)
        self.assertEqual(amounts.get(interno_id), 30.0)

    def test_collect_expected_interno_on_iibb_slot_does_not_steal_iibb_amount(self):
        """Dinner: Impuesto Interno en 1ª fila (slot IIBB) no suma 9154+18962 al interno."""
        iibb_id, perc_iva_id, interno_id = 16, 20, 30
        rows = [
            {
                "iva_pct": "21",
                "invoice_line_ids/name": "COCA-COLA 600*12",
                "invoice_line_ids/price_unit": "11658,03",
                "otros_impuestos": "Impuesto Interno",
                "otros_impuestos_monto": "9154.93",
                "otros_impuestos_2_monto": "8901.72",
                "otros_impuestos_3_monto": "18962.88",
                "__fac_percepciones": [
                    {
                        "amount_key": "percepcion_iibb",
                        "monto": "9154.93",
                        "ui_monto_key": "otros_impuestos_monto",
                    },
                    {
                        "amount_key": "percepcion_iva",
                        "monto": "8901.72",
                        "ui_monto_key": "otros_impuestos_2_monto",
                    },
                    {
                        "amount_key": "otros_tributos",
                        "monto": "18962.88",
                        "ui_monto_key": "otros_impuestos_3_monto",
                    },
                ],
            },
            {
                "iva_pct": "21",
                "invoice_line_ids/name": "SPRITE",
                "invoice_line_ids/price_unit": "5033,29",
                "otros_impuestos": "Percepción IVA Sufrida",
            },
            {
                "iva_pct": "21",
                "invoice_line_ids/name": "ZERO",
                "invoice_line_ids/price_unit": "5829,01",
                "otros_impuestos": "Impuesto Interno",
            },
            {
                "iva_pct": "21",
                "invoice_line_ids/name": "AQUARIUS",
                "invoice_line_ids/price_unit": "5033,29",
                "otros_impuestos": "Percepción IIBB Chaco Sufrida",
            },
        ]

        def _resolve(label, **_kwargs):
            return {
                "Percepción IIBB Chaco Sufrida": iibb_id,
                "Percepción IVA Sufrida": perc_iva_id,
                "Impuesto Interno": interno_id,
            }.get(str(label or "").strip())

        with patch(
            "facturia_matching.odoo.import_.taxes.resolve_tax_label_to_id",
            side_effect=_resolve,
        ):
            amounts = collect_expected_tax_amounts_from_group(rows)

        self.assertEqual(amounts.get(iibb_id), 9154.93)
        self.assertEqual(amounts.get(perc_iva_id), 8901.72)
        self.assertEqual(amounts.get(interno_id), 18962.88)
        self.assertNotEqual(amounts.get(interno_id), 28117.81)

    def test_tax_ids_header_mode_merges_iibb_from_header_row(self):
        group = [
            {
                "__solo_encabezado": True,
                "iva_pct": "21",
                "__fac_iva_monto": "2100",
                "otros_impuestos": "Percepción IIBB CABA Sufrida",
                "otros_impuestos_monto": "99,50",
                "_padron_other_tax_ids": ["1"],
            },
            {
                "iva_pct": "0",
                "invoice_line_ids/name": "Producto",
                "invoice_line_ids/price_unit": "10000",
            },
        ]
        with patch("facturia_matching.padron.taxes.resolve_tax_label_to_id", return_value=1):
            first_line = _tax_ids_for_odoo_line(group[1], group)
        self.assertEqual(first_line, [1])

    def test_plan_line_tax_updates_puts_iibb_on_first_content_line(self):
        rows = [
            {
                "__solo_encabezado": True,
                "iva_pct": "21",
                "__fac_iva_monto": "2100",
                "otros_impuestos": "Percepción IIBB CABA Sufrida",
                "otros_impuestos_monto": "99,50",
                "_padron_other_tax_ids": ["1"],
            },
            {
                "iva_pct": "0",
                "invoice_line_ids/name": "Producto",
                "invoice_line_ids/price_unit": "10000",
            },
        ]
        product_lines = [
            {"id": 10, "name": "Producto", "tax_ids": []},
            {"id": 11, "name": "Otro", "tax_ids": [1]},
        ]
        with patch("facturia_matching.padron.taxes.resolve_tax_label_to_id", return_value=1):
            updates, warnings = plan_line_tax_updates(product_lines, rows)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["line_id"], 10)
        self.assertEqual(updates[0]["new_tax_ids"], [1])

    def test_collect_expected_tax_amounts_line_mode(self):
        rows = [
            {
                "iva_pct": "21",
                "__fac_iva_monto": "2100",
                "invoice_line_ids/name": "A",
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "5000",
            },
            {
                "iva_pct": "21",
                "invoice_line_ids/name": "B",
                "invoice_line_ids/quantity": "1",
                "invoice_line_ids/price_unit": "5000",
            },
        ]
        amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertEqual(amounts.get(63), 2100.0)

    def test_plan_tax_line_amount_overwrites(self):
        tax_lines = [
            {
                "id": 100,
                "name": "IVA 21%",
                "tax_line_id": 63,
                "balance": 1000.0,
                "debit": 1000.0,
                "credit": 0.0,
            },
            {
                "id": 101,
                "name": "Percepción IIBB",
                "tax_line_id": 1,
                "balance": 50.0,
                "debit": 50.0,
                "credit": 0.0,
            },
        ]
        expected = {63: 2100.5, 1: 150.25}
        updates, warnings = plan_tax_line_amount_overwrites(tax_lines, expected)
        self.assertEqual(len(updates), 2)
        self.assertEqual(updates[0]["new_amount"], 2100.5)
        self.assertEqual(updates[1]["new_amount"], 150.25)
        self.assertEqual(warnings, [])

    def test_tax_ids_for_odoo_line_pure_line_mode(self):
        group = [
            {
                "iva_pct": "21",
                "invoice_line_ids/name": "A",
                "invoice_line_ids/price_unit": "1000",
                "invoice_line_ids/quantity": "1",
                "__fac_iva_monto": "315",
            },
            {
                "iva_pct": "10.5",
                "invoice_line_ids/name": "B",
                "invoice_line_ids/price_unit": "1000",
                "invoice_line_ids/quantity": "1",
            },
        ]
        self.assertEqual(classify_comprobante_tax_mode(group), "line")
        self.assertEqual(_tax_ids_for_odoo_line(group[0], group), [63])
        self.assertEqual(_tax_ids_for_odoo_line(group[1], group), [61])

    def test_collect_expected_header_mode_uses_explicit_montos(self):
        rows = [
            {
                "iva_pct": "0",
                "__fac_iva_montos": '{"21": "210"}',
                "__fac_iva_monto": "210",
                "invoice_line_ids/name": "x",
                "invoice_line_ids/price_unit": "1000",
                "invoice_line_ids/quantity": "1",
            }
        ]
        self.assertEqual(classify_comprobante_tax_mode(rows), "header")
        amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertEqual(amounts.get(63), 210.0)

    def test_collect_expected_mixed_mode_uses_explicit_json(self):
        rows = [
            {
                "iva_pct": "21",
                "__fac_iva_montos": '{"21": "500"}',
                "__fac_iva_monto": "500",
                "invoice_line_ids/name": "A",
                "invoice_line_ids/price_unit": "100",
                "invoice_line_ids/quantity": "1",
            },
            {
                "iva_pct": "0",
                "invoice_line_ids/name": "B",
                "invoice_line_ids/price_unit": "50",
                "invoice_line_ids/quantity": "1",
            },
        ]
        self.assertEqual(classify_comprobante_tax_mode(rows), "mixed")
        amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertEqual(amounts.get(63), 500.0)

    def test_collect_expected_after_reconcile_keeps_footer_montos(self):
        """Montos del pie en mixed no se reemplazan por cálculo por línea antes del import."""
        from facturia_matching.core.comprobante_tax import reconcile_fac_iva_for_import

        rows = [
            {
                "iva_pct": "21",
                "__fac_iva_montos": '{"21": "15893.38", "10.5": "2832.75"}',
                "__fac_iva_monto": "18726.13",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "33019,55",
                "invoice_line_ids/name": "A",
            },
            {
                "iva_pct": "10,5",
                "invoice_line_ids/quantity": "10",
                "invoice_line_ids/price_unit": "964,37",
                "invoice_line_ids/name": "B",
            },
            {
                "iva_pct": "21",
                "invoice_line_ids/quantity": "2",
                "invoice_line_ids/price_unit": "13489,27",
                "invoice_line_ids/name": "C",
            },
        ]
        reconcile_fac_iva_for_import(rows)
        amounts = collect_expected_tax_amounts_from_group(rows)
        self.assertAlmostEqual(amounts.get(63), 15893.38, places=2)
        self.assertAlmostEqual(amounts.get(61), 2832.75, places=2)

    def test_plan_tax_line_overwrites_multi_iva_rates(self):
        tax_lines = [
            {
                "id": 100,
                "name": "IVA 21%",
                "tax_line_id": 63,
                "balance": 100.0,
                "debit": 100.0,
                "credit": 0.0,
            },
            {
                "id": 101,
                "name": "IVA 10.5%",
                "tax_line_id": 61,
                "balance": 50.0,
                "debit": 50.0,
                "credit": 0.0,
            },
        ]
        expected = {63: 18726.13, 61: 1012.59}
        updates, warnings = plan_tax_line_amount_overwrites(tax_lines, expected)
        self.assertEqual(len(updates), 2)
        self.assertEqual(updates[0]["new_amount"], 18726.13)
        self.assertEqual(updates[1]["new_amount"], 1012.59)
        self.assertEqual(warnings, [])

    @patch("facturia_matching.odoo.import_.sync.apply_purchase_order_price_overwrites", return_value=([], []))
    @patch("facturia_matching.odoo.import_.sync._apply_tax_line_amount_overwrites")
    @patch("facturia_matching.odoo.import_.sync._batch_write_move_lines")
    @patch("facturia_matching.odoo.import_.sync.plan_product_price_quantity_reapply")
    @patch("facturia_matching.odoo.import_.sync.plan_purchase_line_updates", return_value=([], []))
    @patch("facturia_matching.odoo.import_.sync.plan_line_tax_updates")
    @patch("facturia_matching.odoo.import_.sync.plan_product_line_content_updates", return_value=([], []))
    @patch("facturia_matching.odoo.import_.sync._get_move_product_lines")
    @patch("facturia_matching.odoo.import_.sync._ensure_move_line_maturity")
    @patch("facturia_matching.odoo.import_.sync._move_line_supports_purchase_link", return_value=True)
    @patch("facturia_matching.odoo.import_.sync.odoo_execute_kw_with_config")
    def test_sync_applies_tax_amounts_after_all_line_writes(
        self,
        mock_odoo,
        _purchase_ok,
        _maturity,
        mock_product_lines,
        _content_plan,
        mock_tax_plan,
        _po_plan,
        mock_price_reapply,
        mock_batch_write,
        mock_apply_tax,
        _po_price,
    ):
        from facturia_matching.odoo.import_.sync import sync_move_taxes_from_group

        mock_odoo.return_value = [
            {
                "id": 1,
                "name": "BILL/1",
                "state": "draft",
                "l10n_latam_document_number": "00001-00000001",
                "invoice_origin": False,
                "invoice_date": "2026-04-01",
                "invoice_date_due": "2026-04-16",
            }
        ]
        mock_product_lines.return_value = [{"id": 10, "name": "Item", "tax_ids": [63, 101, 102]}]
        mock_tax_plan.side_effect = [
            ([], []),  # primer paso (contenido+tax)
            (
                [
                    {
                        "line_id": 10,
                        "line_name": "Item",
                        "old_tax_ids": [63, 101, 102],
                        "new_tax_ids": [63, 101],
                    }
                ],
                [],
            ),  # reapply post-OC/precio
        ]
        mock_price_reapply.return_value = (
            [{"line_id": 10, "line_name": "Item", "write_vals": {"price_unit": 100.0}}],
            [],
        )
        mock_batch_write.return_value = [{"line_id": 10}]
        mock_apply_tax.return_value = ([], [], {1: 150.25})

        group = [
            {
                "iva_pct": "21",
                "__fac_iva_monto": "2100",
                "otros_impuestos": "Percepción IIBB CABA Sufrida",
                "otros_impuestos_monto": "150,25",
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/price_unit": "100",
            }
        ]
        sync_move_taxes_from_group({}, 1, group)

        self.assertEqual(mock_tax_plan.call_count, 2)
        self.assertEqual(mock_apply_tax.call_count, 1)
        contexts = [c.kwargs.get("context") for c in mock_batch_write.call_args_list]
        self.assertIn("precio", contexts)
        self.assertEqual(contexts[-1], "tax_ids")

    @patch("facturia_matching.odoo.import_.taxes._trigger_product_line_tax_recompute")
    @patch("facturia_matching.odoo.import_.taxes.odoo_execute_kw_with_config")
    @patch("facturia_matching.odoo.import_.taxes._get_move_tax_lines")
    @patch("facturia_matching.odoo.import_.taxes.collect_expected_tax_amounts_from_group")
    def test_ensure_missing_tax_lines_nudges_when_tax_ids_unchanged(
        self,
        mock_expected,
        mock_tax_lines,
        mock_odoo_write,
        mock_trigger,
    ):
        from facturia_matching.odoo.import_.taxes import _ensure_missing_tax_lines_on_move

        mock_expected.return_value = {1: 150.25, 63: 2100.0}
        mock_tax_lines.return_value = [
            {"id": 100, "tax_line_id": 63, "balance": 2100.0, "debit": 2100.0, "credit": 0.0},
        ]
        group = [
            {
                "iva_pct": "21",
                "__fac_iva_monto": "2100",
                "otros_impuestos": "Percepción IIBB CABA Sufrida",
                "otros_impuestos_monto": "150,25",
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/price_unit": "100",
            }
        ]
        product_lines = [{"id": 10, "name": "Item", "tax_ids": [63, 1], "quantity": 1.0, "price_unit": 100.0}]
        with patch(
            "facturia_matching.odoo.import_.taxes._tax_ids_for_odoo_line",
            return_value=[63, 1],
        ):
            warnings = _ensure_missing_tax_lines_on_move({}, 1, group, product_lines)

        mock_odoo_write.assert_called_once()
        _args, kwargs = mock_odoo_write.call_args
        write_vals = _args[3][1]
        self.assertEqual(write_vals["quantity"], 1.0)
        self.assertEqual(write_vals["price_unit"], 100.0)
        self.assertNotIn("tax_ids", write_vals)
        self.assertTrue(any("recálculo" in w for w in warnings))
        mock_trigger.assert_called_once_with({}, 1, 10)

    @patch("facturia_matching.odoo.import_.taxes._trigger_product_line_tax_recompute")
    @patch("facturia_matching.odoo.import_.taxes.odoo_execute_kw_with_config")
    @patch("facturia_matching.odoo.import_.taxes._get_move_tax_lines")
    @patch("facturia_matching.odoo.import_.taxes.collect_expected_tax_amounts_from_group")
    def test_ensure_missing_tax_lines_links_new_tax_ids(
        self,
        mock_expected,
        mock_tax_lines,
        mock_odoo_write,
        mock_trigger,
    ):
        from facturia_matching.odoo.import_.taxes import _ensure_missing_tax_lines_on_move

        mock_expected.return_value = {1: 150.25, 63: 2100.0}
        mock_tax_lines.return_value = [
            {"id": 100, "tax_line_id": 63, "balance": 2100.0, "debit": 2100.0, "credit": 0.0},
        ]
        group = [
            {
                "iva_pct": "21",
                "__fac_iva_monto": "2100",
                "otros_impuestos": "Percepción IIBB CABA Sufrida",
                "otros_impuestos_monto": "150,25",
                "invoice_line_ids/name": "Item",
                "invoice_line_ids/price_unit": "100",
            }
        ]
        product_lines = [{"id": 10, "name": "Item", "tax_ids": [63], "quantity": 1.0, "price_unit": 100.0}]
        with patch(
            "facturia_matching.odoo.import_.taxes._tax_ids_for_odoo_line",
            return_value=[63, 1],
        ):
            warnings = _ensure_missing_tax_lines_on_move({}, 1, group, product_lines)

        mock_odoo_write.assert_called_once()
        _args, kwargs = mock_odoo_write.call_args
        write_vals = _args[3][1]
        self.assertEqual(write_vals["tax_ids"], [(4, 1)])
        self.assertTrue(any("faltante" in w for w in warnings))
        mock_trigger.assert_called_once_with({}, 1, 10)
