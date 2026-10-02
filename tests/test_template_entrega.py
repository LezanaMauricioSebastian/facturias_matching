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

    def test_header_only_sheet_is_one_row(self):
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
                            "should_repeat": 1,
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
                            "lookup_suggest": 1,
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
                            "lookup_suggest": 1,
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
                "__excel_concepto": "Servicios",
                "__excel_categoria": "Gastos Fijos",
            }
        ]
        sheet = project_template(template, facturas, excel_rows, {}, lookups)[0]
        flags = {c["name"]: c["is_dropdown"] for c in sheet["columns"]}
        self.assertTrue(flags["Concepto"])
        self.assertTrue(flags["Mes"])
        self.assertEqual(sheet["rows"][0]["Concepto"], "Servicios")
        self.assertEqual(sheet["rows"][0]["Categoria de gasto"], "Gastos Fijos")
        self.assertEqual(sheet["rows"][0]["Mes"], "")
        self.assertEqual(sheet["options"]["Mes"], ["enero", "febrero"])

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
