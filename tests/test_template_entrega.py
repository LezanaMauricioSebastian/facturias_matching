"""Entrega por export_template: columnas de staging + match Excel."""

import unittest
from unittest.mock import MagicMock, patch

from facturia_matching.padron.template_entrega import (
    facturas_from_json_data,
    project_template,
)
from facturia_matching.persistence.export_template_store import (
    ExportTemplateNotFound,
    load_export_template,
)

# Subconjunto de columnas de staging «De Castillo (A)» (id 23) más una línea.
DE_CASTILLO_TEMPLATE = {
    "id": 23,
    "name": "De Castillo (A)",
    "sheets": [
        {
            "name": "hoja1",
            "columns": [
                {
                    "header_label": "Proveedor",
                    "source_type": "canonical",
                    "source_value": "cabecera.proveedor.nombre",
                    "should_repeat": 1,
                },
                {
                    "header_label": "Concepto",
                    "source_type": "canonical",
                    "source_value": "cabecera.concepto",
                    "should_repeat": 1,
                },
                {
                    "header_label": "Forma de pago",
                    "source_type": "canonical",
                    "source_value": "cabecera.forma_de_pago",
                    "should_repeat": 1,
                },
                {
                    "header_label": "Fecha",
                    "source_type": "canonical",
                    "source_value": "cabecera.fecha",
                    "should_repeat": 1,
                },
                {
                    "header_label": "Total",
                    "source_type": "canonical",
                    "source_value": "cabecera.total",
                    "should_repeat": 0,
                },
                {
                    "header_label": "Descripcion",
                    "source_type": "canonical",
                    "source_value": "items[].descripcion",
                    "should_repeat": 1,
                },
                {
                    "header_label": "Nota",
                    "source_type": "static",
                    "source_value": "fijo",
                    "should_repeat": 1,
                },
            ],
        }
    ],
}


def _padron():
    return {
        "proveedores": [
            {"razon_social": "AADI CAPIF", "nombre_fantasia": "", "cuit": "30"},
        ],
        "conceptos": ["Servicios", "Alquiler"],
        "formas_pago": ["Santander", "Efectivo"],
        "productos": [{"nombre": "Cafe"}],
    }


class TestProjectTemplate(unittest.TestCase):
    def test_dropdowns_and_excel_match_not_raw_name(self):
        facturas = [
            {
                "fecha": "02/01/2026",
                "total": "99000",
                "concepto": "Servicios crudo",
                "forma_de_pago": "Transferencia",
                "proveedor": {"nombre": "Proveedor FacturIA"},
                "items": [
                    {"descripcion": "Cafe"},
                    {"descripcion": "Leche"},
                ],
            }
        ]
        excel_rows = [
            {
                "__comprobante_idx": 0,
                "__excel_proveedor": "AADI CAPIF",
                "__excel_concepto": "Servicios",
                "__excel_forma_pago": "Santander",
            },
            {
                "__comprobante_idx": 0,
                "__excel_proveedor": "AADI CAPIF",
                "__excel_concepto": "Servicios",
                "__excel_forma_pago": "",
            },
        ]
        sheets = project_template(DE_CASTILLO_TEMPLATE, facturas, excel_rows, _padron())
        self.assertEqual(len(sheets), 1)
        sheet = sheets[0]
        flags = {c["name"]: c["is_dropdown"] for c in sheet["columns"]}
        self.assertEqual(
            flags,
            {
                "Proveedor": True,
                "Concepto": True,
                "Forma de pago": True,
                "Fecha": False,
                "Total": False,
                "Descripcion": False,
                "Nota": False,
            },
        )
        self.assertEqual(sheet["options"]["Proveedor"], ["AADI CAPIF"])
        self.assertEqual(sheet["options"]["Concepto"], ["Servicios", "Alquiler"])
        self.assertNotIn("Fecha", sheet["options"])
        self.assertEqual(len(sheet["rows"]), 2)
        self.assertEqual(sheet["rows"][0]["Proveedor"], "AADI CAPIF")
        self.assertNotEqual(sheet["rows"][0]["Proveedor"], "Proveedor FacturIA")
        self.assertEqual(sheet["rows"][0]["Concepto"], "Servicios")
        self.assertEqual(sheet["rows"][0]["Forma de pago"], "Santander")
        self.assertEqual(sheet["rows"][0]["Fecha"], "02/01/2026")
        self.assertEqual(sheet["rows"][0]["Total"], "99000")
        self.assertEqual(sheet["rows"][0]["Descripcion"], "Cafe")
        self.assertEqual(sheet["rows"][0]["Nota"], "fijo")
        # should_repeat=0: el total de cabecera no se repite en la 2ª línea.
        self.assertEqual(sheet["rows"][1]["Total"], "")
        self.assertEqual(sheet["rows"][1]["Proveedor"], "AADI CAPIF")
        self.assertEqual(sheet["rows"][1]["Forma de pago"], "Santander")
        self.assertEqual(sheet["rows"][1]["Descripcion"], "Leche")

    def test_falls_back_to_facturia_when_excel_match_empty(self):
        facturas = [
            {
                "proveedor": {"nombre": "Proveedor FacturIA"},
                "concepto": "Servicios crudo",
                "forma_de_pago": "Transferencia",
                "fecha": "02/01/2026",
                "total": "10",
                "items": [{"descripcion": "Cafe"}],
            }
        ]
        excel_rows = [
            {
                "__comprobante_idx": 0,
                "__excel_proveedor": "",
                "__excel_concepto": "",
                "__excel_forma_pago": "",
            }
        ]
        row = project_template(DE_CASTILLO_TEMPLATE, facturas, excel_rows, _padron())[0]["rows"][0]
        self.assertEqual(row["Proveedor"], "Proveedor FacturIA")
        self.assertEqual(row["Concepto"], "Servicios crudo")
        self.assertEqual(row["Forma de pago"], "Transferencia")

    def test_header_only_sheet_is_one_row_per_comprobante(self):
        template = {
            "sheets": [
                {
                    "name": "hoja1",
                    "columns": [
                        {
                            "header_label": "Proveedor",
                            "source_type": "canonical",
                            "source_value": "cabecera.proveedor.nombre",
                            "should_repeat": 1,
                        },
                        {
                            "header_label": "Rubro",
                            "source_type": "canonical",
                            "source_value": "cabecera.rubro",
                            "should_repeat": 0,
                        },
                    ],
                }
            ]
        }
        facturas = [
            {
                "proveedor": {"nombre": "X"},
                "rubro": "Cocina",
                "items": [{"descripcion": "a"}, {"descripcion": "b"}],
            }
        ]
        sheet = project_template(template, facturas, [], {})[0]
        self.assertEqual(len(sheet["rows"]), 1)
        self.assertEqual(sheet["rows"][0]["Proveedor"], "X")
        self.assertEqual(sheet["rows"][0]["Rubro"], "Cocina")
        self.assertTrue(sheet["columns"][1]["is_dropdown"])
        self.assertEqual(sheet["options"]["Rubro"], [])

    def test_facturas_skip_wraps_without_json(self):
        raw = {
            "facturas": [
                {"json": "no-dict"},
                {"json": {"factura": {"fecha": "1"}}},
            ]
        }
        facs = facturas_from_json_data(raw)
        self.assertEqual(len(facs), 1)
        self.assertEqual(facs[0]["fecha"], "1")


class TestLookupSuggestion(unittest.TestCase):
    def test_suggest_returns_sheet_value_and_marks_dropdown(self):
        template = {
            "sheets": [
                {
                    "name": "hoja1",
                    "columns": [
                        {
                            "header_label": "Proveedor",
                            "source_type": "canonical",
                            "source_value": "cabecera.proveedor.cuit",
                            "should_repeat": 1,
                            "lookup_suggest": 0,
                            "lookup_integration_id": 1,
                            "lookup_sheet_title": "Proveedores",
                            "lookup_match_column": "cuit",
                            "lookup_return_column": "nombre",
                        },
                        {
                            "header_label": "Producto",
                            "source_type": "canonical",
                            "source_value": "items[].codigo",
                            "should_repeat": 1,
                            "lookup_suggest": 0,
                            "lookup_integration_id": 3,
                            "lookup_sheet_title": "Productos",
                            "lookup_match_column": "codigo",
                            "lookup_return_column": "titulo",
                        },
                    ],
                }
            ]
        }
        lookups = {
            (1, "proveedores", "cuit", "nombre"): {
                "by_key": {"30546688999": "La Alemana"},
                "options": ["La Alemana", "Otro"],
            },
            (3, "productos", "codigo", "titulo"): {
                "by_key": {"a1": "Landing"},
                "options": ["Landing"],
            },
        }
        facturas = [
            {
                "proveedor": {"cuit": "30-54668899-9", "nombre": "Crudo"},
                "items": [{"codigo": "A1", "descripcion": "x"}],
            }
        ]
        sheet = project_template(template, facturas, [], {}, lookups)[0]
        self.assertTrue(sheet["columns"][0]["is_dropdown"])
        self.assertTrue(sheet["columns"][1]["is_dropdown"])
        self.assertEqual(sheet["rows"][0]["Proveedor"], "La Alemana")
        self.assertEqual(sheet["rows"][0]["Producto"], "Landing")
        self.assertEqual(sheet["options"]["Proveedor"], ["La Alemana", "Otro"])

    def test_suggest_fills_later_lines_when_should_repeat_is_off(self):
        template = {
            "sheets": [
                {
                    "name": "hoja1",
                    "columns": [
                        {
                            "header_label": "Proveedor",
                            "source_type": "canonical",
                            "source_value": "cabecera.proveedor.cuit",
                            "should_repeat": 1,
                            "lookup_suggest": 0,
                            "lookup_integration_id": 1,
                            "lookup_sheet_title": "Proveedores",
                            "lookup_match_column": "cuit",
                            "lookup_return_column": "nombre",
                        },
                        {
                            "header_label": "Total",
                            "source_type": "canonical",
                            "source_value": "cabecera.total",
                            "should_repeat": 0,
                        },
                        {
                            "header_label": "Producto",
                            "source_type": "canonical",
                            "source_value": "items[].codigo",
                            "should_repeat": 0,
                        },
                    ],
                }
            ]
        }
        lookups = {
            (1, "proveedores", "cuit", "nombre"): {
                "by_key": {"30708790598": "La Alemana"},
                "options": ["La Alemana"],
            },
        }
        facturas = [
            {
                "proveedor": {
                    "cuit": "30708790598",
                    "razon_social": "LA ALEMANA S.R.L.",
                },
                "total": "15879.75",
                "items": [
                    {"codigo": "A1", "descripcion": "Pan Frances por mayor"},
                    {"codigo": "A2", "descripcion": "Pan Frances por mayor"},
                ],
            }
        ]
        rows = project_template(template, facturas, [], {}, lookups)[0]["rows"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Proveedor"], "La Alemana")
        self.assertEqual(rows[1]["Proveedor"], "La Alemana")
        self.assertEqual(rows[0]["Total"], "15879.75")
        self.assertEqual(rows[1]["Total"], "")
        self.assertEqual(rows[0]["Producto"], "A1")
        self.assertEqual(rows[1]["Producto"], "A2")

        missed = project_template(
            template,
            [
                {
                    "proveedor": {"cuit": "20111111112"},
                    "total": "10",
                    "items": [{"codigo": "A1"}, {"codigo": "A2"}],
                }
            ],
            [],
            {},
            lookups,
        )[0]["rows"]
        self.assertEqual(missed[0]["Proveedor"], "")
        self.assertEqual(missed[1]["Proveedor"], "")

    def test_razon_social_suggest_repeats_without_item_columns(self):
        template = {
            "sheets": [
                {
                    "name": "hoja1",
                    "columns": [
                        {
                            "header_label": "Razon social",
                            "source_type": "canonical",
                            "source_value": "cabecera.proveedor.razon_social",
                            "should_repeat": 1,
                            "lookup_suggest": 0,
                            "lookup_integration_id": 4,
                            "lookup_sheet_title": "Config",
                            "lookup_match_column": "Proveedores",
                            "lookup_return_column": "",
                        },
                    ],
                }
            ]
        }
        facturas = [
            {
                "proveedor": {
                    "razon_social": "LA ALEMANA S.R.L.",
                    "cuit": "30708790598",
                },
                "items": [
                    {"descripcion": "Pan Frances por mayor"},
                    {"descripcion": "Pan Frances por mayor"},
                ],
            }
        ]
        excel_rows = [
            {"__comprobante_idx": 0, "__excel_proveedor": "La Alemana"},
            {"__comprobante_idx": 0, "__excel_proveedor": "La Alemana"},
        ]
        rows = project_template(template, facturas, excel_rows, {})[0]["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Razon social"], "La Alemana")
        self.assertNotEqual(rows[0]["Razon social"], "LA ALEMANA S.R.L.")

    def test_la_alemana_no_toma_el_historial_de_gran_crianza(self):
        template = {
            "sheets": [
                {
                    "name": "hoja1",
                    "columns": [
                        {
                            "header_label": "RAZON SOCIAL",
                            "source_type": "canonical",
                            "source_value": "cabecera.proveedor.razon_social",
                            "should_repeat": 1,
                            "lookup_suggest": 0,
                            "lookup_integration_id": 4,
                            "lookup_sheet_title": "Config",
                            "lookup_match_column": "Proveedores",
                            "lookup_return_column": "",
                        },
                        {
                            "header_label": "DESCRIPCION LINEA 1",
                            "source_type": "canonical",
                            "source_value": "items[].descripcion",
                            "should_repeat": 1,
                            "lookup_suggest": 0,
                            "lookup_integration_id": 4,
                            "lookup_sheet_title": "Config",
                            "lookup_match_column": "Producto",
                            "lookup_return_column": "",
                        },
                    ],
                }
            ]
        }
        lookups = {
            (4, "config", "proveedores", "proveedores"): {
                "by_key": {
                    "la alemana": "La Alemana",
                    "gran crianza s.a": "GRAN CRIANZA S.A",
                    "la alemana s.r.l": "LA ALEMANA S.R.L",
                },
                "options": ["GRAN CRIANZA S.A", "LA ALEMANA S.R.L", "La Alemana"],
            },
            (4, "config", "producto", "producto"): {
                "by_key": {},
                "options": ['PICADA "C" ESP (8214)', "Pan Frances por mayor"],
            },
        }
        facturas = [
            {
                "proveedor": {"razon_social": "La Alemana"},
                "items": [{"descripcion": "Panificados"}],
            },
            {
                "proveedor": {"razon_social": "LA ALEMANA S.R.L."},
                "items": [{"descripcion": "Pan Frances por mayor"}],
            },
        ]
        excel_rows = [
            {"__comprobante_idx": 0, "__excel_proveedor": "GRAN CRIANZA S.A"},
            {"__comprobante_idx": 1, "__excel_proveedor": "GRAN CRIANZA S.A"},
        ]
        gastos = [
            {
                "proveedor": "GRAN CRIANZA S.A",
                "concepto": "PICADA",
                "valores": {"producto": 'PICADA "C" ESP (8214)'},
            },
            {
                "proveedor": "GRAN CRIANZA S.A",
                "concepto": "PICADA",
                "valores": {"producto": 'PICADA "C" ESP (8214)'},
            },
        ]
        rows = project_template(
            template, facturas, excel_rows, {}, lookups, gastos_records=gastos
        )[0]["rows"]
        self.assertEqual(rows[0]["RAZON SOCIAL"], "La Alemana")
        self.assertEqual(rows[1]["RAZON SOCIAL"], "La Alemana")
        self.assertNotEqual(rows[0]["DESCRIPCION LINEA 1"], 'PICADA "C" ESP (8214)')
        self.assertEqual(rows[1]["DESCRIPCION LINEA 1"], "Pan Frances por mayor")

    def test_texto_igual_a_la_lista_gana_al_historial(self):
        template = {
            "sheets": [
                {
                    "name": "hoja1",
                    "columns": [
                        {
                            "header_label": "FORMA DE PAGO",
                            "source_type": "canonical",
                            "source_value": "cabecera.forma_de_pago",
                            "lookup_suggest": 0,
                            "lookup_integration_id": 4,
                            "lookup_sheet_title": "Config",
                            "lookup_match_column": "Forma de Pago",
                            "lookup_return_column": "",
                        },
                        {
                            "header_label": "DESCRIPCION LINEA 1",
                            "source_type": "canonical",
                            "source_value": "items[].descripcion",
                            "lookup_suggest": 0,
                            "lookup_integration_id": 4,
                            "lookup_sheet_title": "Config",
                            "lookup_match_column": "Producto",
                            "lookup_return_column": "",
                        },
                    ],
                }
            ]
        }
        lookups = {
            (4, "config", "forma de pago", "forma de pago"): {
                "by_key": {"(vacio)": "(vacío)", "efectivo": "Efectivo"},
                "options": ["(vacío)", "Efectivo", "Cta. Cte."],
            },
            (4, "config", "producto", "producto"): {
                "by_key": {},
                "options": ['PICADA "C" ESP (8214)', "Pan Francés por mayor"],
            },
        }
        facturas = [
            {
                "proveedor": {"razon_social": "La Alemana"},
                "forma_de_pago": "EFECTIVO",
                "items": [{"descripcion": "Pan Frances por mayor"}],
            }
        ]
        excel_rows = [{"__comprobante_idx": 0, "__excel_proveedor": "La Alemana"}]
        gastos = [
            {
                "proveedor": "La Alemana",
                "concepto": "",
                "valores": {
                    "forma de pago": "(vacío)",
                    "producto": 'PICADA "C" ESP (8214)',
                },
            }
        ]
        row = project_template(
            template, facturas, excel_rows, {}, lookups, gastos_records=gastos
        )[0]["rows"][0]
        self.assertEqual(row["FORMA DE PAGO"], "Efectivo")
        self.assertEqual(row["DESCRIPCION LINEA 1"], "Pan Francés por mayor")

    def test_tilde_no_pisa_un_texto_que_ya_esta_en_la_lista(self):
        template = {
            "sheets": [
                {
                    "name": "hoja1",
                    "columns": [
                        {
                            "header_label": "RAZON SOCIAL",
                            "source_type": "canonical",
                            "source_value": "cabecera.proveedor.razon_social",
                            "lookup_suggest": 1,
                            "lookup_integration_id": 4,
                            "lookup_sheet_title": "Config",
                            "lookup_match_column": "Proveedores",
                            "lookup_return_column": "",
                        },
                        {
                            "header_label": "FORMA DE PAGO",
                            "source_type": "canonical",
                            "source_value": "cabecera.forma_de_pago",
                            "lookup_suggest": 1,
                            "lookup_integration_id": 4,
                            "lookup_sheet_title": "Config",
                            "lookup_match_column": "Forma de Pago",
                            "lookup_return_column": "",
                        },
                    ],
                }
            ]
        }
        lookups = {
            (4, "config", "proveedores", "proveedores"): {
                "by_key": {},
                "options": ["GRAN CRIANZA S.A", "La Alemana"],
            },
            (4, "config", "forma de pago", "forma de pago"): {
                "by_key": {},
                "options": ["Cta. Cte.", "Efectivo"],
            },
        }
        facturas = [
            {
                "proveedor": {"razon_social": "LA ALEMANA S.R.L."},
                "forma_de_pago": "EFECTIVO",
                "items": [],
            }
        ]
        excel_rows = [{"__comprobante_idx": 0, "__excel_proveedor": "GRAN CRIANZA S.A"}]
        rows = project_template(template, facturas, excel_rows, {}, lookups)[0]["rows"]
        self.assertEqual(rows[0]["RAZON SOCIAL"], "La Alemana")
        self.assertEqual(rows[0]["FORMA DE PAGO"], "Efectivo")

    def test_tilde_uses_excel_pipeline_even_if_source_is_static(self):
        template = {
            "sheets": [
                {
                    "name": "hoja1",
                    "columns": [
                        {
                            "header_label": "Concepto",
                            "source_type": "static",
                            "source_value": "",
                            "lookup_suggest": 1,
                            "lookup_integration_id": 4,
                            "lookup_sheet_title": "Config",
                            "lookup_match_column": "Conceptos",
                            "lookup_return_column": "Conceptos",
                        },
                        {
                            "header_label": "Categoria de gasto",
                            "source_type": "static",
                            "source_value": "",
                            "lookup_suggest": 1,
                            "lookup_integration_id": 4,
                            "lookup_sheet_title": "Config",
                            "lookup_match_column": "Categoria de Gasto",
                            "lookup_return_column": "Categoria de Gasto",
                        },
                        {
                            "header_label": "Mes",
                            "source_type": "static",
                            "source_value": "",
                            "lookup_suggest": 0,
                            "lookup_integration_id": 4,
                            "lookup_sheet_title": "Config",
                            "lookup_match_column": "Mes",
                            "lookup_return_column": "Mes",
                        },
                    ],
                }
            ]
        }
        lookups = {
            (4, "config", "conceptos", "conceptos"): {
                "by_key": {},
                "options": ["Servicios", "Alquiler"],
            },
            (4, "config", "categoria de gasto", "categoria de gasto"): {
                "by_key": {},
                "options": ["Gastos Fijos"],
            },
            (4, "config", "mes", "mes"): {
                "by_key": {},
                "options": ["enero", "febrero"],
            },
        }
        facturas = [{"proveedor": {"razon_social": "X"}, "items": [{"descripcion": "cafe"}]}]
        excel_rows = [
            {
                "__comprobante_idx": 0,
                "__excel_concepto": "Alquiler",
                "__excel_concepto_fuzzy": "Alquiler",
                "__excel_concepto_ai": "Servicios",
                "__excel_categoria": "Gastos Var",
                "__excel_categoria_fuzzy": "Gastos Var",
                "__excel_categoria_ai": "Gastos Fijos",
            }
        ]
        with patch(
            "facturia_matching.padron.column_suggest.suggest_lookup_columns",
            return_value={"Concepto": "Servicios", "Categoria de gasto": "Gastos Fijos"},
        ):
            sheet = project_template(template, facturas, excel_rows, {}, lookups)[0]
        flags = {c["name"]: c["is_dropdown"] for c in sheet["columns"]}
        self.assertTrue(flags["Concepto"])
        self.assertTrue(flags["Mes"])
        self.assertEqual(sheet["rows"][0]["Concepto"], "Servicios")
        self.assertEqual(sheet["rows"][0]["Categoria de gasto"], "Gastos Fijos")
        self.assertEqual(sheet["rows"][0]["Mes"], "")
        self.assertEqual(sheet["options"]["Mes"], ["enero", "febrero"])

    def test_tilde_concepto_es_ia_y_sin_tilde_es_fuzzy(self):
        template = {
            "sheets": [
                {
                    "name": "hoja1",
                    "columns": [
                        {
                            "header_label": "Concepto",
                            "source_type": "static",
                            "source_value": "",
                            "lookup_suggest": 1,
                        },
                        {
                            "header_label": "Concepto fuzzy",
                            "source_type": "static",
                            "source_value": "",
                            "lookup_suggest": 0,
                        },
                        {
                            "header_label": "Categoria de gasto",
                            "source_type": "static",
                            "source_value": "",
                            "lookup_suggest": 1,
                        },
                        {
                            "header_label": "Categoria fuzzy",
                            "source_type": "static",
                            "source_value": "",
                            "lookup_suggest": 0,
                        },
                    ],
                }
            ]
        }
        facturas = [{"proveedor": {"razon_social": "X"}, "items": [{"descripcion": "cafe"}]}]
        excel_rows = [
            {
                "__comprobante_idx": 0,
                "__excel_concepto": "No usar",
                "__excel_concepto_fuzzy": "Alquiler",
                "__excel_concepto_ai": "Servicios",
                "__excel_categoria": "No usar",
                "__excel_categoria_fuzzy": "Gastos Var",
                "__excel_categoria_ai": "Gastos Fijos",
            }
        ]
        row = project_template(template, facturas, excel_rows, {})[0]["rows"][0]
        self.assertEqual(row["Concepto"], "Servicios")
        self.assertEqual(row["Concepto fuzzy"], "Alquiler")
        self.assertEqual(row["Categoria de gasto"], "Gastos Fijos")
        self.assertEqual(row["Categoria fuzzy"], "Gastos Var")

    def test_cualquier_columna_vinculada_historial_o_ia(self):
        """No depende del nombre Concepto: la lista vinculada define fuzzy o IA."""
        template = {
            "sheets": [
                {
                    "name": "hoja1",
                    "columns": [
                        {
                            "header_label": "Centro de costo",
                            "source_type": "static",
                            "source_value": "",
                            "lookup_suggest": 0,
                            "lookup_integration_id": 4,
                            "lookup_sheet_title": "Config",
                            "lookup_match_column": "Centro de costo",
                            "lookup_return_column": "Centro de costo",
                        },
                        {
                            "header_label": "Sucursal",
                            "source_type": "static",
                            "source_value": "",
                            "lookup_suggest": 1,
                            "lookup_integration_id": 4,
                            "lookup_sheet_title": "Config",
                            "lookup_match_column": "Sucursal",
                            "lookup_return_column": "Sucursal",
                        },
                    ],
                }
            ]
        }
        lookups = {
            (4, "config", "centro de costo", "centro de costo"): {
                "by_key": {},
                "options": ["Cocina", "Salon"],
            },
            (4, "config", "sucursal", "sucursal"): {
                "by_key": {},
                "options": ["Palermo", "Belgrano"],
            },
        }
        facturas = [{"proveedor": {"razon_social": "ACME"}, "items": [{"descripcion": "cafe"}]}]
        excel_rows = [{"__comprobante_idx": 0, "__excel_proveedor": "ACME"}]
        gastos = [
            {
                "proveedor": "ACME",
                "concepto": "",
                "categoria": "",
                "descripcion": "",
                "valores": {"centro de costo": "Cocina", "sucursal": "Belgrano"},
            },
            {
                "proveedor": "ACME",
                "concepto": "",
                "categoria": "",
                "descripcion": "",
                "valores": {"centro de costo": "Cocina", "sucursal": "Belgrano"},
            },
        ]
        with patch(
            "facturia_matching.padron.column_suggest.suggest_lookup_columns",
            return_value={"Sucursal": "Palermo"},
        ):
            row = project_template(
                template, facturas, excel_rows, {}, lookups, gastos_records=gastos
            )[0]["rows"][0]
        self.assertEqual(row["Centro de costo"], "Cocina")
        self.assertEqual(row["Sucursal"], "Palermo")

    def test_empty_return_column_lists_the_match_column(self):
        template = {
            "sheets": [
                {
                    "name": "hoja1",
                    "columns": [
                        {
                            "header_label": "Estado de Deuda",
                            "source_type": "static",
                            "source_value": "",
                            "lookup_suggest": 0,
                            "lookup_integration_id": 4,
                            "lookup_sheet_title": "Config",
                            "lookup_match_column": "Estado de Deuda",
                            "lookup_return_column": "",
                        }
                    ],
                }
            ]
        }
        lookups = {
            (4, "config", "estado de deuda", "estado de deuda"): {
                "by_key": {},
                "options": ["Pagado", "Debe"],
            }
        }
        sheet = project_template(template, [{}], [], {}, lookups)[0]
        self.assertTrue(sheet["columns"][0]["is_dropdown"])
        self.assertEqual(sheet["options"]["Estado de Deuda"], ["Pagado", "Debe"])

    def test_fecha_monto_y_observacion_salen_de_la_factura(self):
        template = {
            "sheets": [
                {
                    "name": "hoja1",
                    "columns": [
                        {
                            "header_label": name,
                            "source_type": "static",
                            "source_value": "",
                            "lookup_suggest": 1,
                        }
                        for name in (
                            "Fecha",
                            "Monto",
                            "Fecha de pago",
                            "Observacion",
                        )
                    ],
                }
            ]
        }
        facturas = [
            {
                "fecha": "02/10/2026",
                "total": 1500,
                "vencimiento": "15/10/2026",
                "observaciones": "nota del comprobante",
                "items": [],
            }
        ]
        row = project_template(template, facturas, [], {})[0]["rows"][0]
        self.assertEqual(row["Fecha"], "02/10/2026")
        self.assertEqual(row["Monto"], "$1.500,00")
        self.assertEqual(row["Fecha de pago"], "15/10/2026")
        self.assertEqual(row["Observacion"], "nota del comprobante")

    def test_iso_date_month_empty_total_and_unknown_forma_pago(self):
        template = {
            "sheets": [
                {
                    "name": "hoja1",
                    "columns": [
                        {
                            "header_label": "Mes",
                            "source_type": "canonical",
                            "source_value": "cabecera.fecha",
                            "should_repeat": 0,
                            "lookup_suggest": 1,
                        },
                        {
                            "header_label": "Fecha",
                            "source_type": "canonical",
                            "source_value": "cabecera.fecha",
                            "should_repeat": 0,
                            "lookup_suggest": 1,
                        },
                        {
                            "header_label": "Monto",
                            "source_type": "canonical",
                            "source_value": "cabecera.total",
                            "should_repeat": 0,
                            "lookup_suggest": 1,
                        },
                        {
                            "header_label": "Forma de pago",
                            "source_type": "canonical",
                            "source_value": "cabecera.forma_de_pago",
                            "should_repeat": 0,
                            "lookup_suggest": 1,
                        },
                    ],
                }
            ]
        }
        facturas = [
            {
                "fecha": "2026-04-04",
                "fecha_emision": "01/01/2020",
                "total": None,
                "forma_de_pago": "AF05",
                "items": [
                    {"descripcion": "a", "subtotal": 144000},
                    {"descripcion": "b", "subtotal": 10},
                ],
            }
        ]
        excel_rows = [
            {
                "__comprobante_idx": 0,
                "__excel_forma_pago": "AF05",
                "__excel_forma_pago_score": 0,
            },
            {"__comprobante_idx": 0, "__excel_forma_pago": "", "__excel_forma_pago_score": 0},
        ]
        rows = project_template(template, facturas, excel_rows, {})[0]["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Fecha"], "04/04/2026")
        self.assertNotEqual(rows[0]["Fecha"], "01/01/2020")
        self.assertEqual(rows[0]["Mes"], "abril")
        self.assertEqual(rows[0]["Monto"], "")
        self.assertEqual(rows[0]["Forma de pago"], "")

    def test_lodepepe_no_suggest_on_monto_or_unmapped_date(self):
        """JM - Lodepepe: sin tilde no se sugiere Monto ni una fecha de pago distinta."""
        template = {
            "sheets": [
                {
                    "name": "hoja1",
                    "columns": [
                        {
                            "header_label": "Fecha",
                            "source_type": "canonical",
                            "source_value": "cabecera.fecha",
                            "should_repeat": 0,
                            "lookup_suggest": 0,
                        },
                        {
                            "header_label": "Monto",
                            "source_type": "canonical",
                            "source_value": "cabecera.total",
                            "should_repeat": 0,
                            "lookup_suggest": 0,
                        },
                        {
                            "header_label": "Fecha de pago",
                            "source_type": "static",
                            "source_value": "",
                            "should_repeat": 0,
                            "lookup_suggest": 0,
                        },
                    ],
                }
            ]
        }
        facturas = [
            {
                "fecha": "2026-04-04",
                "fecha_emision": "01/01/2020",
                "total": None,
                "vencimiento": "15/10/2026",
                "items": [{"descripcion": "a", "subtotal": 144000}, {"descripcion": "b"}],
            }
        ]
        rows = project_template(template, facturas, [], {})[0]["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Fecha"], "04/04/2026")
        self.assertEqual(rows[0]["Monto"], "")
        self.assertEqual(rows[0]["Fecha de pago"], "")

    def test_coincidir_con_no_abre_una_fila_por_item(self):
        """Coincidir con no multiplica filas. La preview es una por comprobante."""
        template = {
            "sheets": [
                {
                    "name": "hoja1",
                    "columns": [
                        {
                            "header_label": "RAZON SOCIAL",
                            "source_type": "canonical",
                            "source_value": "cabecera.proveedor.razon_social",
                            "should_repeat": 1,
                            "lookup_suggest": 0,
                            "lookup_integration_id": 4,
                            "lookup_sheet_title": "Config",
                            "lookup_match_column": "Proveedores",
                            "lookup_return_column": "",
                        }
                    ],
                }
            ]
        }
        facturas = [
            {
                "proveedor": {"razon_social": "GRAN CRIANZA S.A"},
                "items": [{}, {}, {}],
            },
            {
                "proveedor": {"razon_social": "LA ALEMANA S.R.L"},
                "items": [{}, {}],
            },
        ]
        rows = project_template(template, facturas, [], {})[0]["rows"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            [r["RAZON SOCIAL"] for r in rows],
            ["GRAN CRIANZA S.A", "LA ALEMANA S.R.L"],
        )

    def test_gastos_sin_items_no_desalinea_el_comprobante_siguiente(self):
        """Sin columnas items[], una fila por factura: el mes no es una fecha y el monto vacío no copia el total de la siguiente."""
        template = {
            "sheets": [
                {
                    "name": "hoja1",
                    "columns": [
                        {
                            "header_label": "Mes",
                            "source_type": "canonical",
                            "source_value": "cabecera.fecha",
                            "should_repeat": 0,
                            "lookup_suggest": 1,
                        },
                        {
                            "header_label": "Fecha",
                            "source_type": "canonical",
                            "source_value": "cabecera.fecha",
                            "should_repeat": 0,
                            "lookup_suggest": 0,
                        },
                        {
                            "header_label": "Monto",
                            "source_type": "canonical",
                            "source_value": "cabecera.total",
                            "should_repeat": 0,
                            "lookup_suggest": 0,
                        },
                        {
                            "header_label": "Proveedor",
                            "source_type": "canonical",
                            "source_value": "cabecera.proveedor.razon_social",
                            "should_repeat": 1,
                            "lookup_suggest": 1,
                            "lookup_integration_id": 5,
                            "lookup_sheet_title": "Config",
                            "lookup_match_column": "Proveedores",
                            "lookup_return_column": "",
                        },
                    ],
                }
            ]
        }
        facturas = [
            {
                "fecha": "10/10/2026",
                "total": "46084.91",
                "items": [{"descripcion": "a"}, {"descripcion": "b"}],
            },
            {
                "fecha": "07/10/2026",
                "total": "914730.51",
                "items": [{"descripcion": "c"}],
            },
            {
                "fecha": "2026-04-04",
                "total": None,
                "items": [{"descripcion": "d", "subtotal": 144000}],
            },
        ]
        rows = project_template(template, facturas, [], {})[0]["rows"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["Mes"], "octubre")
        self.assertEqual(rows[0]["Fecha"], "10/10/2026")
        self.assertEqual(rows[0]["Monto"], "$46.084,91")
        self.assertEqual(rows[1]["Mes"], "octubre")
        self.assertEqual(rows[1]["Fecha"], "07/10/2026")
        self.assertEqual(rows[1]["Monto"], "$914.730,51")
        self.assertEqual(rows[2]["Mes"], "abril")
        self.assertEqual(rows[2]["Fecha"], "04/04/2026")
        self.assertEqual(rows[2]["Monto"], "")


class TestLoadExportTemplate(unittest.TestCase):
    def _conn(self, fetchone, fetchall_batches):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = fetchone
        cur.fetchall.side_effect = fetchall_batches
        return conn, cur

    def test_groups_columns_and_ignores_deleted_in_sql(self):
        conn, cur = self._conn(
            {
                "id": 23,
                "company_id": 1,
                "name": "De Castillo (A)",
                "export_format": "excel",
            },
            [
                [{"id": 10, "name": "hoja1", "sort_order": 0}],
                [
                    {
                        "id": 1,
                        "sheet_id": 10,
                        "header_label": "Proveedor",
                        "source_type": "canonical",
                        "source_value": "cabecera.proveedor.nombre",
                        "should_repeat": 1,
                        "sort_order": 0,
                    }
                ],
            ],
        )
        with patch(
            "facturia_matching.persistence.export_template_store.get_mysql_connection",
            return_value=conn,
        ):
            out = load_export_template(23, 1)
        sql = cur.execute.call_args_list[0][0][0]
        self.assertIn("deleted_at IS NULL", sql)
        self.assertEqual(out["name"], "De Castillo (A)")
        self.assertEqual(out["sheets"][0]["columns"][0]["header_label"], "Proveedor")
        self.assertEqual(out["sheets"][0]["columns"][0]["source_value"], "cabecera.proveedor.nombre")

    def test_other_company_is_not_found(self):
        conn, _cur = self._conn(
            {"id": 23, "company_id": 2, "name": "Otro", "export_format": "excel"},
            [],
        )
        with patch(
            "facturia_matching.persistence.export_template_store.get_mysql_connection",
            return_value=conn,
        ):
            with self.assertRaises(ExportTemplateNotFound):
                load_export_template(23, 1)

    def test_null_company_is_global(self):
        conn, _cur = self._conn(
            {"id": 99, "company_id": None, "name": "Odoo", "export_format": "odoo"},
            [[]],
        )
        with patch(
            "facturia_matching.persistence.export_template_store.get_mysql_connection",
            return_value=conn,
        ):
            out = load_export_template(99, 1)
        self.assertEqual(out["company_id"], None)
        self.assertEqual(out["sheets"], [])


class TestIntegrationCanList(unittest.TestCase):
    def test_deleted_row_still_lists_its_spreadsheet(self):
        from facturia_matching.padron.template_lookup import integration_can_list

        self.assertTrue(
            integration_can_list(
                {
                    "spreadsheet_id": "1klqwF",
                    "is_active": 1,
                    "deleted_at": "2026-10-16",
                }
            )
        )

    def test_inactive_row_does_not_list(self):
        from facturia_matching.padron.template_lookup import integration_can_list

        self.assertFalse(
            integration_can_list(
                {"spreadsheet_id": "1klqwF", "is_active": 0, "deleted_at": None}
            )
        )

    def test_missing_spreadsheet_does_not_list(self):
        from facturia_matching.padron.template_lookup import integration_can_list

        self.assertFalse(
            integration_can_list({"spreadsheet_id": "", "is_active": 1, "deleted_at": None})
        )
