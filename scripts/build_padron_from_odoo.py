#!/usr/bin/env python3
"""
CLI: padrón equivalente a view_padron_facturia desde facturas Odoo publicadas.

Uso:
  source .venv311/bin/activate
  FACTURIA_ODOO_PROFILE=aliare python scripts/build_padron_from_odoo.py
  FACTURIA_ODOO_PROFILE=aliare python scripts/build_padron_from_odoo.py --json
  python scripts/build_padron_from_odoo.py --lookup "EMPRESA" --compare-postgres
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import Any, Dict, List

from facturia_matching.odoo_api import get_odoo_uid, is_odoo_configured, odoo_xmlrpc_version
from facturia_matching.odoo_env import FACTURIA_ODOO_PROFILE, is_odoo_aliare_profile
from facturia_matching.padron import get_padron_cached
from facturia_matching.padron_odoo import build_padron_rows_from_odoo
from facturia_matching.utils import normalize

VIEW_COLUMNS = [
    "nombre_contacto",
    "numero_documento",
    "rubro",
    "diario",
    "tipo_documento",
    "cuenta_contable",
    "codigo_cuenta_contable",
    "cuenta_contable_completo",
    "nombre_factura",
    "fecha_factura",
]


def _digits_only(s: str) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def rows_for_display(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        cuenta = r.get("cuenta") or ""
        out.append(
            {
                "nombre_contacto": r.get("name") or "",
                "numero_documento": r.get("doc") or "",
                "rubro": r.get("rubro") or "",
                "diario": r.get("diario") or "",
                "cuenta_contable_completo": cuenta,
                "fecha_factura": "",
                **r,
            }
        )
    return out


def lookup_row(rows: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    q = query.strip().lower()
    q_digits = _digits_only(q)
    hits = []
    for r in rows:
        name = normalize(r.get("name") or "").lower()
        doc = _digits_only(r.get("doc"))
        if q_digits and doc and q_digits in doc:
            hits.append(r)
        elif q and q in name:
            hits.append(r)
    return hits


def compare_with_postgres(odoo_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    pg = get_padron_cached()
    pg_by_cuit = {_digits_only(r.get("doc")): r for r in pg if _digits_only(r.get("doc"))}
    odoo_by_cuit = {_digits_only(r.get("doc")): r for r in odoo_rows if _digits_only(r.get("doc"))}
    shared = sorted(set(pg_by_cuit) & set(odoo_by_cuit))
    only_pg = sorted(set(pg_by_cuit) - set(odoo_by_cuit))
    only_odoo = sorted(set(odoo_by_cuit) - set(pg_by_cuit))
    return {
        "postgres_proveedores": len(pg_by_cuit),
        "odoo_proveedores": len(odoo_by_cuit),
        "cuit_en_ambos": len(shared),
        "solo_postgres": len(only_pg),
        "solo_odoo": len(only_odoo),
        "muestra_solo_odoo": only_odoo[:10],
        "muestra_solo_postgres": only_pg[:10],
    }


def print_table(rows: List[Dict[str, Any]], max_rows: int) -> None:
    cols = ["name", "doc", "rubro", "diario", "cuenta"]
    if not rows:
        return
    widths = {c: max(len(c), *(len(str(r.get(c) or "")) for r in rows[:max_rows])) for c in cols}
    print(" | ".join(c.ljust(widths[c]) for c in cols))
    print("-+-".join("-" * widths[c] for c in cols))
    for r in rows[:max_rows]:
        print(" | ".join(str(r.get(c) or "").ljust(widths[c]) for c in cols))


def main() -> int:
    parser = argparse.ArgumentParser(description="Padrón desde últimas facturas Odoo")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--csv", metavar="FILE")
    parser.add_argument("--lookup", metavar="CUIT_O_NOMBRE")
    parser.add_argument("--compare-postgres", action="store_true")
    parser.add_argument("--max-print", type=int, default=30)
    args = parser.parse_args()

    if not is_odoo_configured():
        print("Odoo no configurado", file=sys.stderr)
        return 1

    uid = get_odoo_uid()
    version = odoo_xmlrpc_version() or {}
    rows = build_padron_rows_from_odoo(limit=args.limit)

    if args.lookup:
        rows = lookup_row(rows, args.lookup)

    meta = {
        "odoo_profile": FACTURIA_ODOO_PROFILE or "default",
        "proveedores_padron": len(rows),
        "uid": uid,
        "odoo_version": version.get("server_version"),
        "aliare": is_odoo_aliare_profile(),
    }
    if args.compare_postgres:
        meta["compare_postgres"] = compare_with_postgres(rows)

    display = rows_for_display(rows)

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=VIEW_COLUMNS, extrasaction="ignore")
            w.writeheader()
            for r in display:
                w.writerow(r)
        print(f"CSV: {args.csv} ({len(rows)} filas)")

    if args.json:
        print(json.dumps({"meta": meta, "rows": display}, indent=2, ensure_ascii=False))
    elif not args.csv:
        print(f"Perfil: {meta['odoo_profile']} | uid={uid} | proveedores={len(rows)}")
        print_table(rows, args.max_print)
        if args.compare_postgres:
            print(json.dumps(meta["compare_postgres"], indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
