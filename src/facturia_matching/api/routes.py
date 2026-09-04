"""FastAPI route handlers — facade que compone routers por dominio."""

from fastapi import APIRouter

from facturia_matching.api.route_meta import router as meta_router
from facturia_matching.api.route_odoo import router as odoo_router
from facturia_matching.api.route_padron_excel import router as padron_excel_router
from facturia_matching.api.route_proceso import router as proceso_router

router = APIRouter()
router.include_router(meta_router)
router.include_router(odoo_router)
router.include_router(padron_excel_router)
router.include_router(proceso_router)
