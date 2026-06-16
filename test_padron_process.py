#!/usr/bin/env python3
"""Compare matching output for a process using old vs new padron view."""
import json
import os
from typing import Any, Dict, List

import dotenv

_here = os.path.dirname(__file__)
dotenv.load_dotenv(os.path.join(_here, ".env"))

VIEWS = ["view_padron_facturia", "view_padron_facturia_actualizado"]
PROCESS_NUMBERS = ["185", "214"]


def _summary_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        if r.get("__solo_encabezado"):
            continue
        prov = r.get("Nombre de Proveedor") or ""
        if not prov and not r.get("CUIT"):
            continue
        out.append(
            {
                "proveedor": prov,
                "cuit": r.get("CUIT"),
                "partner_id": r.get("partner_id"),
                "rubro": r.get("x_studio_category"),
                "journal_id": r.get("journal_id"),
                "account_id": r.get("invoice_line_ids/account_id"),
                "match_score": r.get("_match_score_proveedor"),
                "doc": r.get("l10n_latam_document_number"),
            }
        )
    # dedupe by proveedor+cuit for header rows only
    seen = set()
    deduped = []
    for x in out:
        key = (x["proveedor"], x["cuit"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(x)
    return deduped


def run_for_view(view_name: str, process_number: str) -> Dict[str, Any]:
    os.environ["DB_TABLE_NAME"] = view_name
    # Reset padron cache between views
    import app as app_module

    app_module.DB_TABLE_NAME = view_name
    app_module._PADRON_CACHE = None

    filas, product_options = app_module._parse_process_json(process_number)
    out_rows = app_module._build_output_rows(filas)
    return {
        "view": view_name,
        "process_number": process_number,
        "row_count": len(out_rows),
        "product_options_count": len(product_options or []),
        "proveedores_summary": _summary_rows(out_rows),
    }


def main():
    results = {}
    for pn in PROCESS_NUMBERS:
        results[pn] = {}
        for view in VIEWS:
            try:
                results[pn][view] = run_for_view(view, pn)
            except Exception as e:
                results[pn][view] = {"error": str(e)}
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
