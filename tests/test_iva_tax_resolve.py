"""Tests: resolución dinámica de IVA por tenant Odoo (Dinner vs Aliare vs Sudata)."""
import unittest
from unittest.mock import patch

from facturia_matching.odoo.import_ import (
    _tax_ids_for_odoo_line,
    collect_expected_tax_amounts_from_group,
    propagate_invoice_headers,
    group_rows_into_invoices,
)
from facturia_matching.odoo.request_context import odoo_profile_context
from facturia_matching.padron.taxes import (
    build_csv_tax_ids_dot_id,
    clear_tax_padron_cache,
    _build_iva_semantics_from_taxes,
    iva_pct_from_tax_id,
    resolve_iva_tax_id_for_pct,
    resolve_tax_label_to_id,
    tax_id_for_csv_export,
)

DINNER_IVA_TAXES = [
    {"id": 55, "name": "IVA No Corresp", "amount": 0.0},
    {"id": 57, "name": "IVA No Grav", "amount": 0.0},
    {"id": 59, "name": "IVA Exen", "amount": 0.0},
    {"id": 61, "name": "IVA 10.5%", "amount": 10.5},
    {"id": 63, "name": "IVA 21%", "amount": 21.0},
    {"id": 65, "name": "IVA 27%", "amount": 27.0},
]

ALIARE_IVA_TAXES = [
    {"id": 55, "name": "IVA No Corresp", "amount": 0.0},
    {"id": 57, "name": "IVA No Grav", "amount": 0.0},
    {"id": 59, "name": "IVA Exen", "amount": 0.0},
    {"id": 61, "name": "IVA 0%", "amount": 0.0},
    {"id": 63, "name": "IVA 10.5%", "amount": 10.5},
    {"id": 65, "name": "IVA 21%", "amount": 21.0},
    {"id": 67, "name": "IVA 27%", "amount": 27.0},
]

# Sudata Cloud responde account.tax en inglés (sin es_AR): nombres reales del tenant.
SUDATA_IVA_TAXES = [
    {"id": 55, "name": "0% NA", "amount": 0.0},
    {"id": 57, "name": "0% NT", "amount": 0.0},
    {"id": 59, "name": "0% EXEMPT", "amount": 0.0},
    {"id": 61, "name": "VAT 0%", "amount": 0.0},
    {"id": 63, "name": "VAT 10.5%", "amount": 10.5},
    {"id": 65, "name": "VAT 21%", "amount": 21.0},
    {"id": 67, "name": "VAT 27%", "amount": 27.0},
    {"id": 73, "name": "VAT 20%", "amount": 20.0},
]

SUDATA_TAX_NAMES = {
    1: "P. IIBB CABA",
    25: "Other taxes",
    26: "Internal taxes",
    29: "Perc Profits",
    72: "Perc VAT",
    **{int(t["id"]): t["name"] for t in SUDATA_IVA_TAXES},
}

# Mismo tenant pedido con lang=es_419 (ids idénticos, nombres traducidos).
SUDATA_TAX_NAMES_ES = {
    1: "P. IIBB CABA",
    25: "Other taxes",
    26: "Internal taxes",
    29: "Perc Gananc",
    72: "Perc IVA",
    55: "IVA No Corresp",
    57: "IVA No Grav",
    59: "IVA Exen",
    61: "IVA 0%",
    63: "IVA 10.5%",
    65: "IVA 21%",
    73: "IVA Adic 20%",
}


class TestIvaTaxResolve(unittest.TestCase):
    def setUp(self):
        clear_tax_padron_cache()

    def tearDown(self):
        clear_tax_padron_cache()

    def test_dinner_21_maps_to_63(self):
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=DINNER_IVA_TAXES):
            self.assertEqual(resolve_iva_tax_id_for_pct("21"), 63)
            self.assertEqual(tax_id_for_csv_export({"iva_pct": "21"}), "63")

    def test_aliare_21_maps_to_65_not_63(self):
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES):
            self.assertEqual(resolve_iva_tax_id_for_pct("21"), 65)
            self.assertEqual(tax_id_for_csv_export({"iva_pct": "21"}), "65")

    def test_aliare_10_5_maps_to_63(self):
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES):
            self.assertEqual(resolve_iva_tax_id_for_pct("10,5"), 63)
            self.assertEqual(resolve_iva_tax_id_for_pct("10.5"), 63)

    def test_legacy_fallback_without_odoo(self):
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=[]):
            self.assertEqual(resolve_iva_tax_id_for_pct("21"), 63)
            self.assertEqual(resolve_iva_tax_id_for_pct("10,5"), 61)

    def test_sudata_english_names_21_maps_to_65_not_63(self):
        """Testing Elias 13/8: Sudata devuelve 'VAT 21%' y llegaba IVA 10,5% (id 63 Dinner)."""
        with patch(
            "facturia_matching.padron.taxes.get_purchase_iva_taxes",
            return_value=SUDATA_IVA_TAXES,
        ):
            self.assertEqual(resolve_iva_tax_id_for_pct("21"), 65)
            self.assertEqual(resolve_iva_tax_id_for_pct("10,5"), 63)
            self.assertEqual(resolve_iva_tax_id_for_pct("27"), 67)
            self.assertEqual(tax_id_for_csv_export({"iva_pct": "21"}), "65")

    def test_sudata_english_zero_rate_labels(self):
        with patch(
            "facturia_matching.padron.taxes.get_purchase_iva_taxes",
            return_value=SUDATA_IVA_TAXES,
        ):
            self.assertEqual(resolve_iva_tax_id_for_pct("IVA Exento"), 59)
            self.assertEqual(resolve_iva_tax_id_for_pct("IVA No Gravado"), 57)
            self.assertEqual(resolve_iva_tax_id_for_pct("IVA No Corresponde"), 55)

    def test_sudata_english_names_give_iva_pct_semantics(self):
        with patch(
            "facturia_matching.padron.taxes.get_purchase_iva_taxes",
            return_value=SUDATA_IVA_TAXES,
        ):
            self.assertEqual(iva_pct_from_tax_id(65), "21")
            self.assertEqual(iva_pct_from_tax_id(63), "10,5")
            self.assertEqual(iva_pct_from_tax_id(59), "IVA Exento")

    def test_no_dinner_fallback_when_profile_is_not_default(self):
        """Sin catálogo del tenant es mejor no mandar impuesto que mandar el de Dinner."""
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=[]):
            with odoo_profile_context("sudata"):
                self.assertIsNone(resolve_iva_tax_id_for_pct("21"))
                self.assertIsNone(resolve_iva_tax_id_for_pct("IVA Exento"))
            with odoo_profile_context("aliare"):
                self.assertIsNone(resolve_iva_tax_id_for_pct("21"))

    def test_sudata_english_percepcion_labels_resolve(self):
        with patch(
            "facturia_matching.padron.taxes.get_tax_name_by_id",
            return_value=SUDATA_TAX_NAMES,
        ):
            self.assertEqual(resolve_tax_label_to_id("Percepción IVA Sufrida"), 72)
            self.assertEqual(resolve_tax_label_to_id("Percepción Ganancias Sufrida"), 29)
            self.assertEqual(resolve_tax_label_to_id("Percepción IIBB CABA Sufrida"), 1)
            self.assertEqual(resolve_tax_label_to_id("Impuestos internos"), 26)

    def test_saved_english_labels_resolve_against_spanish_catalog(self):
        """Conversiones guardadas con el catálogo en inglés siguen resolviendo tras pasar a es_419."""
        with patch(
            "facturia_matching.padron.taxes.get_tax_name_by_id",
            return_value=SUDATA_TAX_NAMES_ES,
        ):
            self.assertEqual(resolve_tax_label_to_id("Perc VAT"), 72)
            self.assertEqual(resolve_tax_label_to_id("Perc Profits"), 29)
            self.assertEqual(resolve_tax_label_to_id("Internal taxes"), 26)
            self.assertEqual(resolve_tax_label_to_id("Percepción IVA Sufrida"), 72)

    def test_sudata_spanish_catalog_resolves_iva(self):
        spanish_taxes = [
            {"id": tid, "name": name, "amount": amount}
            for tid, name, amount in (
                (55, "IVA No Corresp", 0.0),
                (57, "IVA No Grav", 0.0),
                (59, "IVA Exen", 0.0),
                (63, "IVA 10.5%", 10.5),
                (65, "IVA 21%", 21.0),
            )
        ]
        with patch(
            "facturia_matching.padron.taxes.get_purchase_iva_taxes",
            return_value=spanish_taxes,
        ):
            self.assertEqual(resolve_iva_tax_id_for_pct("21"), 65)
            self.assertEqual(resolve_iva_tax_id_for_pct("IVA Exento"), 59)

    def test_padron_primary_remaps_dinner_27_on_aliare(self):
        dinner_semantics = _build_iva_semantics_from_taxes(DINNER_IVA_TAXES)
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES), patch(
            "facturia_matching.padron.taxes._padron_source_iva_semantics_by_id",
            return_value=dinner_semantics,
        ):
            row = {"_padron_tax_id_primary": "65"}
            self.assertEqual(tax_id_for_csv_export(row), "67")

    def test_padron_primary_remaps_dinner_id_on_aliare(self):
        dinner_semantics = _build_iva_semantics_from_taxes(DINNER_IVA_TAXES)
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES), patch(
            "facturia_matching.padron.taxes._padron_source_iva_semantics_by_id",
            return_value=dinner_semantics,
        ):
            row = {"_padron_tax_id_primary": "63"}
            self.assertEqual(tax_id_for_csv_export(row), "65")

    def test_dynamic_semantics_from_odoo_tax_rows(self):
        semantics = _build_iva_semantics_from_taxes(ALIARE_IVA_TAXES)
        self.assertEqual(semantics[65], "21")
        self.assertEqual(semantics[63], "10,5")
        self.assertEqual(semantics[67], "27")

    def test_iva_pct_wins_over_padron_primary(self):
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES):
            row = {"iva_pct": "21", "_padron_tax_id_primary": "63"}
            self.assertEqual(tax_id_for_csv_export(row), "65")

    def test_iva_pct_requires_line_tax(self):
        from facturia_matching.padron.taxes import iva_pct_requires_line_tax

        self.assertTrue(iva_pct_requires_line_tax("IVA Exento"))
        self.assertTrue(iva_pct_requires_line_tax("IVA No Gravado"))
        self.assertTrue(iva_pct_requires_line_tax("IVA No Corresponde"))
        self.assertFalse(iva_pct_requires_line_tax("0"))
        self.assertTrue(iva_pct_requires_line_tax("21"))

    def test_exento_single_line_includes_tax_id(self):
        row = {
            "iva_pct": "IVA Exento",
            "invoice_line_ids/name": "Producto",
            "invoice_line_ids/price_unit": "100",
            "invoice_line_ids/quantity": "1",
        }
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=DINNER_IVA_TAXES):
            groups = [propagate_invoice_headers(g) for g in group_rows_into_invoices([row])]
            group = groups[0]
            tax_ids = _tax_ids_for_odoo_line(group[0], group)
        self.assertEqual(tax_ids, [59])

    def test_meriti_import_assigns_aliare_21_tax(self):
        row = {
            "iva_pct": "21",
            "__fac_iva_montos": '{"21": "57255.38"}',
            "invoice_line_ids/name": "Consumos",
            "invoice_line_ids/price_unit": "272644.68",
            "invoice_line_ids/quantity": "1",
        }
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES):
            groups = [propagate_invoice_headers(g) for g in group_rows_into_invoices([row])]
            group = groups[0]
            tax_ids = _tax_ids_for_odoo_line(group[0], group)
            amounts = collect_expected_tax_amounts_from_group(group)
            csv_tax = build_csv_tax_ids_dot_id(row)
        self.assertEqual(tax_ids, [65])
        self.assertEqual(amounts, {65: 57255.38})
        self.assertEqual(csv_tax, "65")

    def test_meriti_exento_clears_stale_21_footer_amounts(self):
        """PDF Mauri 16/7: elegir IVA Exento no debe mandar IVA 21% residual del pie."""
        from facturia_matching.core.comprobante_tax import reconcile_fac_iva_for_import

        row = {
            "iva_pct": "IVA Exento",
            "__fac_iva_monto": "57255.38",
            "__fac_iva_montos": '{"21": "57255.38"}',
            "otros_impuestos": "Percepción IIBB Jujuy Sufrida",
            "otros_impuestos_monto": "3544.38",
            "invoice_line_ids/name": "Consumos",
            "invoice_line_ids/price_unit": "272644.68",
            "invoice_line_ids/quantity": "1",
        }
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES), patch(
            "facturia_matching.padron.taxes.resolve_tax_label_to_id", return_value=101
        ), patch(
            "facturia_matching.padron.taxes.is_iva_tax_id",
            side_effect=lambda tid: int(tid) in {55, 57, 59, 61, 63, 65, 67},
        ):
            groups = [propagate_invoice_headers(g) for g in group_rows_into_invoices([row])]
            group = groups[0]
            reconcile_fac_iva_for_import(group)
            tax_ids = _tax_ids_for_odoo_line(group[0], group)
            amounts = collect_expected_tax_amounts_from_group(group)
        self.assertEqual(tax_ids, [59, 101])
        self.assertNotIn(65, amounts)
        self.assertEqual(amounts, {101: 3544.38})
        self.assertFalse(group[0].get("__fac_iva_montos"))
        self.assertEqual(group[0].get("__fac_iva_monto"), "")

    def test_meriti_no_gravado_clears_stale_21_footer_amounts(self):
        from facturia_matching.core.comprobante_tax import reconcile_fac_iva_for_import

        row = {
            "iva_pct": "IVA No Gravado",
            "__fac_iva_montos": '{"21": "57255.38"}',
            "__fac_iva_monto": "57255.38",
            "invoice_line_ids/name": "Consumos",
            "invoice_line_ids/price_unit": "272644.68",
            "invoice_line_ids/quantity": "1",
        }
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES):
            groups = [propagate_invoice_headers(g) for g in group_rows_into_invoices([row])]
            group = groups[0]
            reconcile_fac_iva_for_import(group)
            tax_ids = _tax_ids_for_odoo_line(group[0], group)
            amounts = collect_expected_tax_amounts_from_group(group)
        self.assertEqual(tax_ids, [57])
        self.assertEqual(amounts, {})

    def test_meriti_no_corresponde_clears_stale_21_footer_amounts(self):
        from facturia_matching.core.comprobante_tax import reconcile_fac_iva_for_import

        row = {
            "iva_pct": "IVA No Corresponde",
            "__fac_iva_montos": '{"21": "57255.38"}',
            "__fac_iva_monto": "57255.38",
            "invoice_line_ids/name": "Consumos",
            "invoice_line_ids/price_unit": "272644.68",
            "invoice_line_ids/quantity": "1",
        }
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES):
            groups = [propagate_invoice_headers(g) for g in group_rows_into_invoices([row])]
            group = groups[0]
            reconcile_fac_iva_for_import(group)
            tax_ids = _tax_ids_for_odoo_line(group[0], group)
            amounts = collect_expected_tax_amounts_from_group(group)
        # No Corresponde se adjunta como tax cero (como Exento); sin montos IVA residuales.
        self.assertEqual(tax_ids, [55])
        self.assertEqual(amounts, {})

    def test_switching_line_rate_sends_new_iva_tax_id(self):
        """Testing Elías 13/8: cambiar 21 → 10,5 en la fila mandaba igual IVA 21% del pie."""
        from facturia_matching.core.comprobante_tax import reconcile_fac_iva_for_import

        row = {
            "iva_pct": "10,5",
            "__fac_subtotal": "294299,87",
            "__fac_iva_monto": "48306,18",
            "__fac_iva_montos": '{"21": "48306,18"}',
            "invoice_line_ids/name": "COCA-COLA 600*12 PET",
            "invoice_line_ids/price_unit": "294299,87",
            "invoice_line_ids/quantity": "1",
        }
        with patch(
            "facturia_matching.padron.taxes.get_purchase_iva_taxes",
            return_value=SUDATA_IVA_TAXES,
        ):
            group = propagate_invoice_headers(group_rows_into_invoices([row])[0])
            reconcile_fac_iva_for_import(group)
            amounts = collect_expected_tax_amounts_from_group(group)
        self.assertEqual(amounts, {63: 48306.18})
        self.assertEqual(group[0].get("__fac_iva_montos"), '{"10.5": "48306.18"}')

    def test_header_mode_empty_iva_pct_keeps_footer_amounts(self):
        """Modo header legítimo (iva_pct vacío) sigue usando el pie FacturIA."""
        row = {
            "iva_pct": "",
            "__fac_iva_montos": '{"21": "57255.38"}',
            "__fac_iva_monto": "57255.38",
            "invoice_line_ids/name": "Consumos",
            "invoice_line_ids/price_unit": "272644.68",
            "invoice_line_ids/quantity": "1",
        }
        with patch("facturia_matching.padron.taxes.get_purchase_iva_taxes", return_value=ALIARE_IVA_TAXES):
            groups = [propagate_invoice_headers(g) for g in group_rows_into_invoices([row])]
            group = groups[0]
            amounts = collect_expected_tax_amounts_from_group(group)
        self.assertEqual(amounts, {65: 57255.38})


if __name__ == "__main__":
    unittest.main()
