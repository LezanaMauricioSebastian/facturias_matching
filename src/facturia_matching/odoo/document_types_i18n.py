"""
Respaldo de nombres de l10n_latam.document.type cuando Odoo no traduce.
La vía principal es context.lang=es_AR en todas las llamadas execute_kw (ver ODOO_LANG).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# Nombres estándar Odoo en_US → español (AFIP / localización Argentina).
_DOC_TYPE_EN_TO_ES: Dict[str, str] = {
    "CLASS A SINGLE COMMERCIAL TAX SETTLEMENT": "LIQUIDACIÓN ÚNICA IMPOSITIVA CLASE A",
    "CLASS B SINGLE COMMERCIAL TAX SETTLEMENT": "LIQUIDACIÓN ÚNICA IMPOSITIVA CLASE B",
    "CLASS C SINGLE COMMERCIAL TAX SETTLEMENT": "LIQUIDACIÓN ÚNICA IMPOSITIVA CLASE C",
    "CREDIT NOTE SINGLE COMMERCIAL TAX SETTLEMENT CLASS A": "NOTA DE CRÉDITO LIQUIDACIÓN ÚNICA IMPOSITIVA CLASE A",
    "CREDIT NOTE SINGLE COMMERCIAL TAX SETTLEMENT CLASS B": "NOTA DE CRÉDITO LIQUIDACIÓN ÚNICA IMPOSITIVA CLASE B",
    "CREDIT NOTE SINGLE COMMERCIAL TAX SETTLEMENT CLASS C": "NOTA DE CRÉDITO LIQUIDACIÓN ÚNICA IMPOSITIVA CLASE C",
    "DEBIT NOTE SINGLE COMMERCIAL TAX SETTLEMENT CLASS A": "NOTA DE DÉBITO LIQUIDACIÓN ÚNICA IMPOSITIVA CLASE A",
    "DEBIT NOTE SINGLE COMMERCIAL TAX SETTLEMENT CLASS B": "NOTA DE DÉBITO LIQUIDACIÓN ÚNICA IMPOSITIVA CLASE B",
    "DEBIT NOTE SINGLE COMMERCIAL TAX SETTLEMENT CLASS C": "NOTA DE DÉBITO LIQUIDACIÓN ÚNICA IMPOSITIVA CLASE C",
    "CREDIT NOTE TICKET": "NOTA DE CRÉDITO TIQUE",
    "CREDIT NOTE TICKET A": "NOTA DE CRÉDITO TIQUE A",
    "CREDIT NOTE TICKET B": "NOTA DE CRÉDITO TIQUE B",
    "CREDIT NOTE TICKET C": "NOTA DE CRÉDITO TIQUE C",
    "CREDIT NOTE TICKET M": "NOTA DE CRÉDITO TIQUE M",
    "DEBIT NOTE TICKET A": "NOTA DE DÉBITO TIQUE A",
    "DEBIT NOTE TICKET B": "NOTA DE DÉBITO TIQUE B",
    "DEBIT NOTE TICKET C": "NOTA DE DÉBITO TIQUE C",
    "DEBIT NOTE TICKET M": "NOTA DE DÉBITO TIQUE M",
    "CREDIT NOTES A": "NOTAS DE CRÉDITO A",
    "CREDIT NOTES B": "NOTAS DE CRÉDITO B",
    "CREDIT NOTES C": "NOTAS DE CRÉDITO C",
    "CREDIT NOTES FOR FOREIGN OPERATIONS": "NOTAS DE CRÉDITO POR OPERACIONES CON EL EXTERIOR",
    "CREDIT NOTES M": "NOTAS DE CRÉDITO M",
    "DEBIT MEMOS A": "NOTAS DE DÉBITO A",
    "DEBIT MEMOS B": "NOTAS DE DÉBITO B",
    "DEBIT MEMOS M": "NOTAS DE DÉBITO M",
    "DEBIT NOTES C": "NOTAS DE DÉBITO C",
    "DEBIT NOTES FOR FOREIGN OPERATIONS": "NOTAS DE DÉBITO POR OPERACIONES CON EL EXTERIOR",
    "ELECTRONIC CREDIT INVOICE FOR SMBs (ECF) B": "FACTURA DE CRÉDITO ELECTRÓNICA MiPyMEs (FCE) B",
    "ELECTRONIC CREDIT INVOICE FOR SMBs (FCE) C": "FACTURA DE CRÉDITO ELECTRÓNICA MiPyMEs (FCE) C",
    "ELECTRONIC CREDIT INVOICE FOR SMBs (FCE) TO": "FACTURA DE CRÉDITO ELECTRÓNICA MiPyMEs (FCE) A",
    "ELECTRONIC CREDIT NOTE SME SMEs (FCE) A": "NOTA DE CRÉDITO ELECTRÓNICA MiPyMEs (FCE) A",
    "ELECTRONIC CREDIT NOTE SME's (FCE) C": "NOTA DE CRÉDITO ELECTRÓNICA MiPyMEs (FCE) C",
    "ELECTRONIC CREDIT NOTICE FOR SMBs (FCE) B": "NOTA DE CRÉDITO ELECTRÓNICA MiPyMEs (FCE) B",
    "ELECTRONIC DEBIT NOTE SME's (FCE) B": "NOTA DE DÉBITO ELECTRÓNICA MiPyMEs (FCE) B",
    "ELECTRONIC DEBIT NOTE SME's (FCE) C": "NOTA DE DÉBITO ELECTRÓNICA MiPyMEs (FCE) C",
    "ELECTRONIC DEBIT NOTE SMMEs (FCE) A": "NOTA DE DÉBITO ELECTRÓNICA MiPyMEs (FCE) A",
    "EXPORT INVOICES": "FACTURAS DE EXPORTACIÓN",
    "FOREIGN CREDIT NOTES AND REIMBURSEMENTS": "NOTAS DE CRÉDITO Y REINTEGROS DEL EXTERIOR",
    "IMPORT CLEARANCE": "DESPACHO DE IMPORTACIÓN",
    "INVOICES A": "FACTURAS A",
    "INVOICES AND RECEIPTS FROM ABROAD": "FACTURAS Y RECIBOS DEL EXTERIOR",
    "INVOICES B": "FACTURAS B",
    "INVOICES C": "FACTURAS C",
    "INVOICES M": "FACTURAS M",
    "LIQUIDATION OF CLASS A UTILITIES": "LIQUIDACIÓN DE SERVICIOS PÚBLICOS CLASE A",
    "LIQUIDATION OF CLASS B UTILITIES": "LIQUIDACIÓN DE SERVICIOS PÚBLICOS CLASE B",
    "LIQUIDATIONS A": "LIQUIDACIONES A",
    "LIQUIDATIONS B": "LIQUIDACIONES B",
    "OTHER COMPROBANTES A QUE CUMPLEN CON LA R.G. Nº 1415": "OTROS COMPROBANTES A QUE CUMPLEN CON LA R.G. Nº 1415",
    "OTHER COMPROBANTES B QUE CUMPLAN CON LA R.G. Nº 1415": "OTROS COMPROBANTES B QUE CUMPLAN CON LA R.G. Nº 1415",
    "OTHER COMPROBANTES C QUE CUMPLAN CON LA R.G. Nº 1415": "OTROS COMPROBANTES C QUE CUMPLAN CON LA R.G. Nº 1415",
    "OTHER VOUCHERS THAT DO NOT COMPLY WITH OR ARE EXEMPT FROM G.R. NO. 1415 AND AMENDMENTS THERETO": "OTROS COMPROBANTES QUE NO CUMPLEN O ESTÁN EXCEPTUADOS DE LA R.G. Nº 1415 Y SUS MODIFICATORIAS",
    "PROOF CREDIT NOTES WITH CODE. 34, 39, 58, 59, 60, 63, 96, 97,": "COMPROBANTES NOTAS DE CRÉDITO CON CÓD. 34, 39, 58, 59, 60, 63, 96, 97,",
    "PROOFS OF PURCHASE OF NON-REGISTRABLE GOODS TO FINAL CONSUMERS": "COMPROBANTES DE COMPRA DE BIENES NO REGISTRABLES A CONSUMIDORES FINALES",
    "RECEIPT A": "RECIBO A",
    "RECEIPT B": "RECIBO B",
    "RECEIPT C": "RECIBO C",
    "RECEIPTS M": "RECIBOS M",
    "SALES ACCOUNTS AND LIQUID PRODUCT A": "CUENTAS DE VENTA Y LÍQUIDO PRODUCTO A",
    "SALES ACCOUNTS AND LIQUID PRODUCT B": "CUENTAS DE VENTA Y LÍQUIDO PRODUCTO B",
    "TICKET": "TIQUE",
    "TICKET - INVOICE B": "TIQUE - FACTURA B",
    "TICKET INVOICE A": "TIQUE FACTURA A",
    "TICKET INVOICE C": "TIQUE FACTURA C",
    "TICKET INVOICE M": "TIQUE FACTURA M",
}

_EN_DOC_TYPE_PATTERNS: List[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^INVOICES ([ABC])$", re.I), r"FACTURAS \1"),
    (re.compile(r"^INVOICE ([ABC])$", re.I), r"FACTURA \1"),
    (re.compile(r"^CREDIT NOTES ([ABC])$", re.I), r"NOTAS DE CRÉDITO \1"),
    (re.compile(r"^DEBIT (?:NOTES|MEMOS) ([ABC])$", re.I), r"NOTAS DE DÉBITO \1"),
    (re.compile(r"^RECEIPT ([ABC])$", re.I), r"RECIBO \1"),
    (re.compile(r"^TICKET INVOICE ([ABCM])$", re.I), r"TIQUE FACTURA \1"),
]


def _norm_key(name: str) -> str:
    return " ".join(str(name or "").strip().split()).upper()


def localize_latam_document_type_name(name: str) -> str:
    """Devuelve el nombre en español; si ya está en español o no hay traducción, el original."""
    raw = " ".join(str(name or "").strip().split())
    if not raw:
        return raw
    if raw.upper() == "OC-X":
        return "OC-X"

    key = _norm_key(raw)
    mapped = _DOC_TYPE_EN_TO_ES.get(key)
    if mapped:
        return mapped

    for pattern, repl in _EN_DOC_TYPE_PATTERNS:
        m = pattern.match(raw)
        if m:
            return pattern.sub(repl, raw, count=1).upper()

    if any(
        tok in key
        for tok in (
            "FACTURA",
            "NOTA DE",
            "RECIBO",
            "LIQUIDACI",
            "ORDEN DE",
            "COMPROBANTE",
            "DESPACHO",
            "CUENTAS DE VENTA",
        )
    ):
        return raw

    return raw


def prepare_document_types_for_ui(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Localiza nombres y conserva id + code para mapeo AFIP."""
    out: List[Dict[str, Any]] = []
    seen: set[tuple[Any, str]] = set()
    for row in rows or []:
        iid = row.get("id")
        if iid is None:
            continue
        name = localize_latam_document_type_name(str(row.get("name") or "").strip())
        if not name:
            continue
        item: Dict[str, Any] = {"id": int(iid), "name": name}
        code = str(row.get("code") or "").strip()
        if code:
            item["code"] = code
        key = (iid, name)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out
