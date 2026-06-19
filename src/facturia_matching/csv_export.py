"""CSV export from UI rows."""

import csv
import io
from typing import Any, Dict, List, Optional

from fastapi.responses import StreamingResponse

from facturia_matching.amounts import csv_export_cell, rows_prepared_for_odoo_csv
from facturia_matching.constants import CSV_EXPORT_TAX_IDS_HEADER, OUTPUT_HEADERS, csv_export_headers
from facturia_matching.padron_taxes import build_csv_tax_ids_dot_id
from facturia_matching.utils import normalize


def _otro_sort_key(s: str):
    try:
        n = int(s.split("_")[2])
    except Exception:
        n = 10**9
    return (n, s)


def _otros_name_key_for_monto(monto_key: str) -> Optional[str]:
    parts = monto_key.split("_")
    if len(parts) < 4 or parts[-1] != "monto":
        return None
    try:
        n = int(parts[2])
    except Exception:
        return None
    if n < 2:
        return None
    return f"otros_impuestos_{n}"


def _dyn_monto_used(rows: List[Any], monto_key: str) -> bool:
    nk = _otros_name_key_for_monto(monto_key)
    if nk is None:
        return False
    for row in rows:
        if not isinstance(row, dict):
            continue
        if normalize(row.get(monto_key)) or normalize(row.get(nk)):
            return True
    return False


def _collect_dynamic_otro_monto_keys(rows: List[Any]) -> List[str]:
    dyn_otro_monto: List[str] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        for k in r.keys():
            if not isinstance(k, str):
                continue
            if k.startswith("otros_impuestos_") and k.endswith("_monto"):
                if k == "otros_impuestos_monto":
                    continue
                parts = k.split("_")
                if len(parts) >= 4:
                    try:
                        n = int(parts[2])
                    except Exception:
                        n = None
                    if n is not None and n >= 2:
                        dyn_otro_monto.append(k)
    dyn_otro_monto = sorted(set(dyn_otro_monto), key=_otro_sort_key)
    return [k for k in dyn_otro_monto if _dyn_monto_used(rows, k)]


def build_csv_response(rows: List[Dict[str, Any]]) -> StreamingResponse:
    dyn_otro_monto = _collect_dynamic_otro_monto_keys(rows)

    base_headers = list(OUTPUT_HEADERS)
    csv_base_headers = csv_export_headers(base_headers)
    headers = [*csv_base_headers, *dyn_otro_monto, CSV_EXPORT_TAX_IDS_HEADER]

    export_rows = rows_prepared_for_odoo_csv(rows)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in export_rows:
        if not isinstance(r, dict):
            continue
        base_row = [csv_export_cell(r, h) for h in base_headers]
        dyn_monto_row = [csv_export_cell(r, h) for h in dyn_otro_monto]
        tax_ids_cell = build_csv_tax_ids_dot_id(r)
        w.writerow([*base_row, *dyn_monto_row, tax_ids_cell])
    buf.seek(0)

    content = buf.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="resultado.csv"'},
    )
