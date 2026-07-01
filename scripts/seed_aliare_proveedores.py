#!/usr/bin/env python3
"""
Copia proveedores de Dinner Odoo → Aliare staging (demo / matching UI).

Uso:
  python scripts/seed_aliare_proveedores.py
  python scripts/seed_aliare_proveedores.py --limit 15
  python scripts/seed_aliare_proveedores.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

from facturia_matching.infra.env import env_strip
from facturia_matching.odoo.api import (
    get_odoo_uid_from_config,
    odoo_execute_kw_with_config,
)
from facturia_matching.odoo.env import build_odoo_main_config
from facturia_matching.infra.normalization import normalize


def _digits_only(s: Any) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _build_dinner_config() -> Dict[str, Any]:
    return dict(build_odoo_main_config("default"))


def _build_aliare_config() -> Dict[str, Any]:
    import os

    prev = os.environ.get("FACTURIA_ODOO_PROFILE")
    os.environ["FACTURIA_ODOO_PROFILE"] = "aliare"
    try:
        from importlib import reload

        import facturia_matching.odoo.env as odoo_env

        reload(odoo_env)
        return odoo_env.build_odoo_main_config()
    finally:
        if prev is None:
            os.environ.pop("FACTURIA_ODOO_PROFILE", None)
        else:
            os.environ["FACTURIA_ODOO_PROFILE"] = prev


def _search_read(
    config: Dict[str, Any],
    model: str,
    domain: List[Any],
    fields: List[str],
    *,
    limit: int = 500,
    order: Optional[str] = None,
) -> List[Dict[str, Any]]:
    kwargs: Dict[str, Any] = {"fields": fields, "limit": limit}
    if order:
        kwargs["order"] = order
    rows = odoo_execute_kw_with_config(config, model, "search_read", [domain], kwargs)
    return rows or []


def _existing_aliare_cuits(config: Dict[str, Any]) -> Dict[str, int]:
    rows = _search_read(
        config,
        "res.partner",
        [("supplier_rank", ">", 0)],
        ["id", "name", "vat"],
        limit=20000,
        order="name",
    )
    out: Dict[str, int] = {}
    for row in rows:
        cuit = _digits_only(row.get("vat"))
        if cuit and row.get("id") is not None:
            out[cuit] = int(row["id"])
    return out


def _dinner_suppliers(config: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    rows = _search_read(
        config,
        "res.partner",
        [("supplier_rank", ">", 0), ("vat", "!=", False)],
        ["id", "name", "vat", "supplier_rank"],
        limit=max(limit * 3, 60),
        order="name",
    )
    picked: List[Dict[str, Any]] = []
    seen_cuits: Set[str] = set()
    for row in rows:
        cuit = _digits_only(row.get("vat"))
        name = normalize(row.get("name") or "")
        if not cuit or len(cuit) < 10 or not name:
            continue
        if cuit in seen_cuits:
            continue
        seen_cuits.add(cuit)
        picked.append(row)
        if len(picked) >= limit:
            break
    return picked


def seed_proveedores(*, limit: int = 15, dry_run: bool = False) -> Dict[str, int]:
    dinner_cfg = _build_dinner_config()
    aliare_cfg = _build_aliare_config()

    if not get_odoo_uid_from_config(dinner_cfg):
        raise RuntimeError("No se pudo autenticar en Dinner Odoo (revisá ODOO_* en .env).")
    if not get_odoo_uid_from_config(aliare_cfg):
        raise RuntimeError("No se pudo autenticar en Aliare (revisá ODOO_*_ALIARE en .env).")

    existing = _existing_aliare_cuits(aliare_cfg)
    dinner_rows = _dinner_suppliers(dinner_cfg, limit)

    created = 0
    skipped = 0
    for row in dinner_rows:
        cuit = _digits_only(row.get("vat"))
        name = normalize(row.get("name") or "")
        if cuit in existing:
            print(f"omitido (ya existe id={existing[cuit]}): {name} ({cuit})")
            skipped += 1
            continue
        vals = {
            "name": name,
            "vat": cuit,
            "company_type": "company",
            "supplier_rank": max(int(row.get("supplier_rank") or 1), 1),
        }
        if dry_run:
            print(f"[dry-run] crear: {name} ({cuit})")
            created += 1
            continue
        new_id = int(odoo_execute_kw_with_config(aliare_cfg, "res.partner", "create", [vals]))
        existing[cuit] = new_id
        created += 1
        print(f"creado id={new_id}: {name} ({cuit})")

    return {"created": created, "skipped": skipped, "candidates": len(dinner_rows)}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copiar proveedores Dinner → Aliare")
    parser.add_argument("--limit", type=int, default=15, help="Cantidad máxima a copiar (default 15)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    print(f"Dinner → Aliare | limit={args.limit}")
    stats = seed_proveedores(limit=args.limit, dry_run=args.dry_run)
    print(
        f"Listo. candidatos={stats['candidates']} creados={stats['created']} "
        f"omitidos={stats['skipped']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
