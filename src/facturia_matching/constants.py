"""UI and CSV export column definitions."""

from typing import Any, Dict, List

CSV_HEADER_BY_ROW_KEY: Dict[str, str] = {
    "partner_id": "partner_id/.id",
    "l10n_latam_document_type_id": "l10n_latam_document_type_id/.id",
    "x_studio_category": "x_studio_category/.id",
    "journal_id": "journal_id/.id",
    "invoice_line_ids/account_id": "invoice_line_ids/account_id/.id",
    "invoice_line_ids/product_id": "invoice_line_ids/product_id/.id",
}

CSV_EXPORT_TAX_IDS_HEADER = "invoice_line_ids/tax_ids/.id"

OUTPUT_HEADERS = [
    "l10n_latam_document_number",
    "CUIT",
    "partner_id",
    "l10n_latam_document_type_id",
    "invoice_date",
    "invoice_date_due",
    "x_studio_category",
    "invoice_line_ids/name",
    "invoice_line_ids/product_id",
    "journal_id",
    "invoice_line_ids/account_id",
    "invoice_line_ids/quantity",
    "invoice_line_ids/price_unit",
    "iva_monto",
    "iva_pct",
    "otros_impuestos_monto",
]

IVA_SPECIAL_OPTIONS = ["IVA No Corresponde", "IVA No Gravado", "IVA Exento"]
IVA_OPTIONS = [
    *IVA_SPECIAL_OPTIONS,
    "0",
    "2,5",
    "5",
    "10,5",
    "21",
    "27",
]
OTROS_IMPUESTOS_OPTIONS = [
    "Percepción IIBB CABA Sufrida",
    "Percepción IIBB ARBA Sufrida",
    "Percepción IIBB Catamarca Sufrida",
    "Percepción IIBB Córdoba Sufrida",
    "Percepción IIBB Corrientes Sufrida",
    "Percepción IIBB Entre Ríos Sufrida",
    "Percepción IIBB Jujuy Sufrida",
    "Percepción IIBB Mendoza Sufrida",
    "Percepción IIBB La Rioja Sufrida",
    "Percepción IIBB Salta Sufrida",
    "Percepción IIBB San Juan Sufrida",
    "Percepción IIBB San Luis Sufrida",
    "Percepción IIBB Santa Fe Sufrida",
    "Percepción IIBB Santiago del Estero Sufrida",
    "Percepción IIBB Tucumán Sufrida",
    "Percepción IIBB Chaco Sufrida",
    "Percepción IIBB Chubut Sufrida",
    "Percepción IIBB Formosa Sufrida",
    "Percepción IIBB Misiones Sufrida",
    "Percepción IIBB Neuquén Sufrida",
    "Percepción IIBB La Pampa Sufrida",
    "Percepción IIBB Río Negro Sufrida",
    "Percepción IIBB Santa Cruz Sufrida",
    "Percepción IIBB Tierra del Fuego Sufrida",
    "Percepción IVA Aplicada",
    "Percepción Ganancias Aplicada",
    "Percepción Ganancias Sufrida",
    "Percepción IIBB CABA Aplicada",
    "Percepción IIBB ARBA Aplicada",
    "Percepción IIBB Catamarca Aplicada",
    "Percepción IIBB Córdoba Aplicada",
    "Percepción IIBB Corrientes Aplicada",
    "Percepción IIBB Entre Ríos Aplicada",
    "Percepción IIBB Jujuy Aplicada",
    "Percepción IIBB Mendoza Aplicada",
    "Percepción IIBB La Rioja Aplicada",
    "Percepción IIBB Salta Aplicada",
    "Percepción IIBB San Juan Aplicada",
    "Percepción IIBB San Luis Aplicada",
    "Percepción IIBB Santa Fe Aplicada",
    "Percepción IIBB Santiago del Estero Aplicada",
    "Percepción IIBB Tucumán Aplicada",
    "Percepción IIBB Chaco Aplicada",
    "Percepción IIBB Chubut Aplicada",
    "Percepción IIBB Formosa Aplicada",
    "Percepción IIBB Misiones Aplicada",
    "Percepción IIBB Neuquén Aplicada",
    "Percepción IIBB La Pampa Aplicada",
    "Percepción IIBB Río Negro Aplicada",
    "Percepción IIBB Santa Cruz Aplicada",
    "Percepción IIBB Tierra del Fuego Aplicada",
    "Percepción IVA Sufrida",
    "IVA Adicional 20%",
]
DOCUMENT_TYPES_OPTIONS = ["FACTURAS A", "FACTURAS B", "FACTURAS C", "OC-X"]

UI_COLUMNS = [
    "otros_impuestos",
]

PURCHASE_UI_COLUMNS = [
    "__qty_pedido",
    "__qty_recibido",
    "__um_proveedor",
    "__um_empresa",
    "__oc_match_note",
]

COLUMN_LABELS = {
    "l10n_latam_document_number": "Número de Documento",
    "partner_id": "Proveedor",
    "CUIT": "Cuit",
    "l10n_latam_document_type_id": "Tipo de Documento",
    "invoice_date": "Fecha factura",
    "invoice_date_due": "Fecha de vencimiento",
    "x_studio_category": "Rubros",
    "invoice_line_ids/name": "Etiqueta",
    "invoice_line_ids/product_id": "Producto",
    "journal_id": "Diario",
    "invoice_line_ids/account_id": "Cuenta",
    "invoice_line_ids/quantity": "Cantidad",
    "invoice_line_ids/price_unit": "Precio",
    "iva_pct": "Impuesto IVA",
    "iva_monto": "Monto IVA",
    "otros_impuestos": "Otros Impuestos",
    "otros_impuestos_monto": "Monto Otros Impuestos",
    "__um_proveedor": "UM proveedor",
    "__um_empresa": "UM empresa",
    "__oc_match_note": "Notas OC/UM",
    "__qty_pedido": "Cant. pedida",
    "__qty_recibido": "Cant. recibida",
}


def csv_export_header(row_key: str) -> str:
    return CSV_HEADER_BY_ROW_KEY.get(row_key, row_key)


def csv_export_headers(row_keys: List[str]) -> List[str]:
    return [csv_export_header(k) for k in row_keys]


def ui_header_keys() -> List[str]:
    return list(OUTPUT_HEADERS)


def purchase_numeric_keys() -> set:
    return {"__qty_pedido", "__qty_recibido"}


def append_purchase_columns(columns: List[Dict[str, Any]], readonly_cols: set) -> None:
    numeric_cols = purchase_numeric_keys()
    for key in PURCHASE_UI_COLUMNS:
        col_type = "numeric" if key in numeric_cols else "text"
        columns.append(
            {
                "key": key,
                "label": COLUMN_LABELS.get(key, key),
                "type": col_type,
                "options_key": None,
                "readonly": True,
                "editable": False,
            }
        )
        readonly_cols.add(key)
