"""Tests for Pepe Gastos hardcoded export schema."""

from facturia_matching.padron.pepe_schema import (
    PEPE_GASTOS_COLUMNS,
    format_pepe_money,
    month_name_es_from_date,
    pepe_gastos_values,
)
from facturia_matching.padron.process_to_invoice import factura_to_invoice_input


def test_pepe_columns_match_gastos_sheet():
    assert PEPE_GASTOS_COLUMNS == [
        "Mes",
        "Sucursal",
        "Proveedor",
        "Concepto",
        "Fecha",
        "Monto",
        "Fecha de pago",
        "Mes de pago",
        "Forma de pago",
        "Categoría gasto",
        "Observación",
        "Estado de Deuda",
    ]


def test_month_name_es_from_date():
    assert month_name_es_from_date("2/01/2026") == "enero"
    assert month_name_es_from_date("09/12/2025") == "diciembre"
    assert month_name_es_from_date("2026-03-15") == "marzo"
    assert month_name_es_from_date("") == ""


def test_format_pepe_money():
    assert format_pepe_money(99000) == "$99.000,00"
    assert format_pepe_money("354012.57") == "$354.012,57"
    assert format_pepe_money("") == ""


def test_pepe_gastos_values_from_matched_record():
    row = pepe_gastos_values(
        {
            "fecha": "02/01/2026",
            "fecha_pago": "15/01/2026",
            "sucursal": "Ambas",
            "proveedor_match": "AADI CAPIF",
            "concepto": "Servicios",
            "monto": "99000",
            "forma_pago_match": "Santander",
            "categoria": "Gastos Fijos",
            "observacion": "",
            "estado_deuda": "Pagado",
        }
    )
    assert row[0] == "enero"  # Mes
    assert row[1] == "Ambas"
    assert row[2] == "AADI CAPIF"
    assert row[3] == "Servicios"
    assert row[4] == "02/01/2026"
    assert row[5] == "$99.000,00"
    assert row[6] == "15/01/2026"
    assert row[7] == "enero"
    assert row[8] == "Santander"
    assert row[9] == "Gastos Fijos"
    assert row[10] == ""
    assert row[11] == "Pagado"
    assert len(row) == len(PEPE_GASTOS_COLUMNS)


def test_factura_to_invoice_input_fills_pepe_fields():
    inv = factura_to_invoice_input(
        {
            "fecha": "19/01/2026",
            "fecha_de_vencimiento": "19/01/2026",
            "total": "74500",
            "sucursal": "Rioja",
            "forma_pago": "Efectivo",
            "proveedor": {"razon_social": "Abogado"},
            "items": [{"descripcion": "Honorarios"}],
        }
    )
    assert inv["mes"] == "enero"
    assert inv["mes_pago"] == "enero"
    assert inv["fecha"] == "19/01/2026"
    assert inv["fecha_pago"] == "19/01/2026"
    assert inv["monto"] == "74500"
    assert inv["sucursal"] == "Rioja"
    assert inv["forma_pago"] == "Efectivo"
