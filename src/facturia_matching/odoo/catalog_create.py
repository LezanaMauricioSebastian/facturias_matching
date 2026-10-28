"""Alta de proveedor y producto en Odoo (solo perfil Aliare / Central Tickets)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from facturia_matching.odoo.api import (
    get_odoo_import_config,
    is_odoo_config_ready,
    odoo_available_fields,
    odoo_execute_kw_with_config,
    odoo_search_read,
)
from facturia_matching.odoo.env import is_odoo_aliare_profile

_UOM_RANK = {"unidades": 0, "units": 1, "unidad": 2, "unit": 3}


class CatalogCreateError(ValueError):
    """Nombre inválido, perfil incorrecto o Odoo rechazó el alta."""


def supplier_partner_vals(name: str, vat: str = "") -> Dict[str, Any]:
    """res.partner: nombre tipeado, marca de proveedor y CUIT si la fila lo trae."""
    clean = " ".join(str(name or "").split())
    if len(clean) < 2:
        raise CatalogCreateError("El nombre debe tener al menos 2 caracteres.")
    vals: Dict[str, Any] = {"name": clean, "supplier_rank": 1}
    vat_clean = " ".join(str(vat or "").split())
    if vat_clean:
        vals["vat"] = vat_clean
    return vals


def product_create_vals(name: str, uom_id: int) -> Dict[str, Any]:
    """product.product comprable, con la UM Unidades del tenant."""
    clean = " ".join(str(name or "").split())
    if len(clean) < 2:
        raise CatalogCreateError("El nombre debe tener al menos 2 caracteres.")
    uid = int(uom_id)
    if uid <= 0:
        raise CatalogCreateError("No hay unidad de medida Unidades en Odoo.")
    return {
        "name": clean,
        "purchase_ok": True,
        "type": "consu",
        "uom_id": uid,
        "uom_po_id": uid,
    }


def pick_unidades_uom(rows: List[Dict[str, Any]]) -> Optional[int]:
    """Elige Unidades / Units entre filas de uom.uom. None si ninguna coincide."""
    best_id: Optional[int] = None
    best_rank = 99
    for row in rows or []:
        if not isinstance(row, dict) or row.get("id") is None:
            continue
        name = str(row.get("name") or "").strip().lower()
        rank = _UOM_RANK.get(name)
        if rank is None:
            continue
        rid = int(row["id"])
        if rank < best_rank or (rank == best_rank and (best_id is None or rid < best_id)):
            best_rank = rank
            best_id = rid
    return best_id


def _require_aliare() -> Dict[str, Any]:
    if not is_odoo_aliare_profile():
        raise CatalogCreateError(
            "Crear proveedor o producto solo está habilitado para Central Tickets (Aliare)."
        )
    config = get_odoo_import_config()
    if not is_odoo_config_ready(config):
        raise CatalogCreateError("Odoo Aliare no está configurado.")
    return config


def _filter_vals(model: str, vals: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    allowed = odoo_available_fields(model, list(vals.keys()), config)
    filtered = {key: vals[key] for key in allowed if key in vals}
    if "name" not in filtered and vals.get("name"):
        filtered["name"] = vals["name"]
    return filtered


def resolve_unidades_uom_id(config: Dict[str, Any]) -> int:
    rows = odoo_search_read(
        "uom.uom",
        [
            "|",
            "|",
            "|",
            ("name", "=ilike", "Unidades"),
            ("name", "=ilike", "Unidad"),
            ("name", "=ilike", "Units"),
            ("name", "=ilike", "Unit"),
        ],
        ["id", "name"],
        limit=20,
        order="id",
        config=config,
    )
    uom_id = pick_unidades_uom(rows or [])
    if uom_id is None:
        raise CatalogCreateError("No hay unidad de medida Unidades en Odoo.")
    return uom_id


def create_supplier_partner(name: str, vat: str = "") -> Dict[str, Any]:
    config = _require_aliare()
    vals = _filter_vals("res.partner", supplier_partner_vals(name, vat), config)
    new_id = odoo_execute_kw_with_config(config, "res.partner", "create", [vals])
    out: Dict[str, Any] = {"id": int(new_id), "name": vals["name"]}
    if vals.get("vat"):
        out["vat"] = vals["vat"]
    return out


def create_purchase_product(name: str) -> Dict[str, Any]:
    config = _require_aliare()
    uom_id = resolve_unidades_uom_id(config)
    vals = _filter_vals("product.product", product_create_vals(name, uom_id), config)
    new_id = odoo_execute_kw_with_config(config, "product.product", "create", [vals])
    return {"id": int(new_id), "name": vals["name"]}
