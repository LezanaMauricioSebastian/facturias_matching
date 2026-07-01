#!/usr/bin/env python3
"""
Sincroniza rubros en Odoo Aliare (modelo x_rubros).

Requiere el addon facturia_x_rubros instalado en el tenant Aliare.

Uso:
  FACTURIA_ODOO_PROFILE=aliare python scripts/seed_aliare_rubros.py
  FACTURIA_ODOO_PROFILE=aliare python scripts/seed_aliare_rubros.py --from-dinner
  FACTURIA_ODOO_PROFILE=aliare python scripts/seed_aliare_rubros.py --dry-run

Instalación del addon (una vez, en CloudPepper / Odoo Aliare):
  1. Subir la carpeta odoo_addons/facturia_x_rubros al servidor de addons.
  2. Actualizar lista de apps e instalar "FacturIA Rubros".
  3. Ejecutar este script para completar/sincronizar rubros faltantes.
"""

from __future__ import annotations

import argparse
import sys
from typing import Dict, List, Set

from facturia_matching.odoo.api import is_odoo_configured, odoo_execute_kw, odoo_search_read
from facturia_matching.odoo.env import is_odoo_aliare_profile
from facturia_matching.infra.normalization import normalize


def _rubro_names_from_padron() -> List[str]:
    from facturia_matching.padron.postgres import get_padron_cached

    padron = get_padron_cached() or []
    names: Set[str] = set()
    for row in padron:
        name = normalize(row.get("rubro") or "").upper()
        if name:
            names.add(name)
    return sorted(names)


def _rubro_names_from_dinner() -> List[str]:
    from facturia_matching.odoo.env import is_odoo_aliare_profile as _aliare

    if _aliare():
        raise RuntimeError("--from-dinner requiere perfil default (Dinner), no aliare.")
    rows = odoo_search_read(
        "x_rubros",
        [("x_active", "=", True)],
        ["x_name"],
        limit=500,
        order="x_name",
    )
    names: Set[str] = set()
    for row in rows:
        name = normalize(row.get("x_name") or "").upper()
        if name:
            names.add(name)
    return sorted(names)


def _existing_rubro_names() -> Dict[str, int]:
    rows = odoo_search_read("x_rubros", [], ["id", "x_name"], limit=1000, order="x_name")
    out: Dict[str, int] = {}
    for row in rows:
        name = normalize(row.get("x_name") or "").upper()
        if name and row.get("id") is not None:
            out[name] = int(row["id"])
    return out


def seed_rubros(names: List[str], *, dry_run: bool = False) -> Dict[str, int]:
    existing = _existing_rubro_names()
    created = 0
    skipped = 0
    for seq, name in enumerate(names, start=1):
        key = normalize(name).upper()
        if not key:
            continue
        if key in existing:
            skipped += 1
            continue
        vals = {"x_name": name, "x_active": True, "x_studio_sequence": seq * 10}
        if dry_run:
            print(f"[dry-run] crear: {name}")
            created += 1
            continue
        new_id = int(odoo_execute_kw("x_rubros", "create", [vals]))
        existing[key] = new_id
        created += 1
        print(f"creado id={new_id}: {name}")
    return {"created": created, "skipped": skipped, "total": len(existing)}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed x_rubros en Odoo Aliare staging")
    parser.add_argument("--from-dinner", action="store_true", help="Tomar nombres desde Dinner Odoo (perfil default)")
    parser.add_argument("--dry-run", action="store_true", help="Solo listar altas sin crear")
    args = parser.parse_args(argv)

    if not is_odoo_aliare_profile():
        print("AVISO: FACTURIA_ODOO_PROFILE no es aliare; se usará el tenant Odoo activo.", file=sys.stderr)
    if not is_odoo_configured():
        print("Odoo no configurado.", file=sys.stderr)
        return 1

    try:
        odoo_execute_kw("x_rubros", "fields_get", [], {"attributes": ["string"]})
    except Exception as e:
        print(
            "El modelo x_rubros no existe en este tenant. Instalá el addon "
            "odoo_addons/facturia_x_rubros en Aliare y volvé a ejecutar.\n"
            f"Detalle: {e}",
            file=sys.stderr,
        )
        return 2

    if args.from_dinner:
        names = _rubro_names_from_dinner()
        source = "dinner_odoo"
    else:
        names = _rubro_names_from_padron()
        source = "postgres_padron"

    print(f"Fuente: {source} | rubros a revisar: {len(names)}")
    stats = seed_rubros(names, dry_run=args.dry_run)
    print(
        f"Listo. creados={stats['created']} omitidos={stats['skipped']} "
        f"total_en_odoo={stats['total']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
