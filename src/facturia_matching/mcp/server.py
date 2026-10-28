"""Facturia matching MCP: preview → confirm → Odoo draft.

Run (matching UI must be up, default http://127.0.0.1:8080):

    FACTURIA_MATCHING_URL=http://127.0.0.1:8080 python -m facturia_matching.mcp

Or after ``pip install 'facturia-matching[mcp]'``:

    facturia-mcp
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from facturia_matching.mcp.api_client import MatchingApiClient, MatchingApiError
from facturia_matching.mcp.confirm import ConfirmStore, ConfirmationError
from facturia_matching.mcp.preview import build_match_preview

INSTRUCTIONS = """
Sos el asistente de FacturIA Matching para contadores.
Flujo obligatorio:
1) preview_invoice_match (process_number) — muestra resumen y gaps.
2) Preguntá al contador si proveedor, montos, IVA y líneas están bien.
3) Si corrige algo, volvé a preview. Si confirma, confirm_invoice_preview.
4) Solo entonces import_odoo_draft con el confirmation_token.
Nunca inventes impuestos ni partner_id. Nunca publiques (posted): solo borrador.
Si falta process_number, pedilo: el OCR/extracción vive en FacturIA; este MCP carga ese proceso.
""".strip()

_store = ConfirmStore()
_client: Optional[MatchingApiClient] = None


def _api() -> MatchingApiClient:
    global _client
    if _client is None:
        _client = MatchingApiClient()
    return _client


def _err(exc: Exception) -> Dict[str, Any]:
    return {"ok": False, "error": str(exc)}


def tool_odoo_health(
    empresa: Optional[str] = None,
    odoo_profile: str = "default",
) -> Dict[str, Any]:
    """Chequea conectividad Odoo del matching UI (perfil activo)."""
    try:
        data = _api().odoo_health(empresa=empresa, odoo_profile=odoo_profile)
        return {"ok": True, "health": data, "odoo_profile": odoo_profile}
    except MatchingApiError as exc:
        return _err(exc)


def tool_search_proveedor(
    query: str,
    limit: int = 20,
    empresa: Optional[str] = None,
    odoo_profile: str = "default",
) -> Dict[str, Any]:
    """Busca proveedores en Odoo (nombre / CUIT). Mínimo 2 caracteres."""
    q = (query or "").strip()
    if len(q) < 2:
        return {"ok": False, "error": "query debe tener al menos 2 caracteres"}
    try:
        data = _api().search_partners(
            q, limit=limit, empresa=empresa, odoo_profile=odoo_profile
        )
        return {"ok": True, **(data if isinstance(data, dict) else {"result": data})}
    except MatchingApiError as exc:
        return _err(exc)


def tool_preview_invoice_match(
    process_number: str,
    empresa: Optional[str] = None,
    odoo_profile: str = "default",
    regenerate: bool = False,
) -> Dict[str, Any]:
    """
    Carga el proceso FacturIA vía matching UI, resume matches/gaps y crea un preview_id.
    No escribe en Odoo. Mostrá el resumen al contador y pedí confirmación.
    """
    pn = str(process_number or "").strip()
    if not pn:
        return {
            "ok": False,
            "error": "Falta process_number (el id del proceso FacturIA ya OCR-eado).",
        }
    try:
        proceso = _api().get_proceso(
            pn,
            empresa=empresa,
            odoo_profile=odoo_profile,
            regenerate=regenerate,
        )
    except MatchingApiError as exc:
        return _err(exc)

    rows = list(proceso.get("rows") or []) if isinstance(proceso, dict) else []
    profile = (
        (proceso.get("odoo_profile") if isinstance(proceso, dict) else None)
        or odoo_profile
        or "default"
    )
    summary = build_match_preview(
        rows,
        process_number=pn,
        odoo_profile=str(profile),
        source=(proceso.get("source") if isinstance(proceso, dict) else None),
    )
    rec = _store.create_preview(
        process_number=pn,
        rows=rows,
        summary=summary,
        empresa=empresa or (proceso.get("empresa") if isinstance(proceso, dict) else None),
        odoo_profile=str(profile),
    )
    return {
        "ok": True,
        "preview_id": rec.preview_id,
        "preview_expires_minutes": int(_store.preview_ttl_sec // 60),
        "process_number": pn,
        "odoo_profile": rec.odoo_profile,
        "empresa": rec.empresa,
        "row_count": len(rows),
        "summary": summary,
        "next_step": (
            "Preguntá al contador si los datos son correctos. "
            "Si sí → confirm_invoice_preview(preview_id). "
            "Si no → corregí / search_proveedor y volvé a preview_invoice_match."
        ),
    }


def tool_confirm_invoice_preview(preview_id: str) -> Dict[str, Any]:
    """
    El contador confirmó que el preview está bien.
    Devuelve confirmation_token de un solo uso para import_odoo_draft.
    """
    try:
        token = _store.confirm(preview_id)
        rec = _store.get_preview(preview_id)
    except ConfirmationError as exc:
        return _err(exc)
    return {
        "ok": True,
        "preview_id": preview_id,
        "confirmation_token": token,
        "process_number": rec.process_number,
        "confirm_expires_minutes": int(_store.confirm_ttl_sec // 60),
        "next_step": "Llamá import_odoo_draft(confirmation_token=...). Solo crea borrador en Odoo.",
    }


def tool_import_odoo_draft(
    confirmation_token: str,
    skip_duplicates: bool = True,
    import_id: Optional[int] = None,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Importa a Odoo en estado borrador. Requiere confirmation_token de confirm_invoice_preview.
    Sin token válido → error (no se escribe nada).
    Opcional: import_id + token del deep-link FacturIA (erp-imports webhook).
    """
    try:
        rec = _store.consume_for_import(confirmation_token)
    except ConfirmationError as exc:
        return _err(exc)

    try:
        result = _api().import_odoo(
            rec.rows,
            empresa=rec.empresa,
            odoo_profile=rec.odoo_profile,
            skip_duplicates=skip_duplicates,
            import_id=import_id,
            token=token,
        )
    except MatchingApiError as exc:
        # Re-issue is not automatic; user must preview+confirm again.
        return {
            "ok": False,
            "error": str(exc),
            "hint": "El token ya se consumió. Volvé a preview_invoice_match → confirm → import.",
            "process_number": rec.process_number,
        }

    return {
        "ok": True,
        "process_number": rec.process_number,
        "odoo_profile": rec.odoo_profile,
        "target_state": "draft",
        "import_result": result,
        "message": "Import borrador enviado a Odoo. Revisá el resultado con el contador.",
    }


def create_mcp_server():
    """Build FastMCP app (requires optional dependency ``mcp``)."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Falta el paquete MCP. Instalá con: pip install 'mcp>=1.2.0'\n"
            f"Detalle: {exc}"
        ) from exc

    mcp = FastMCP(
        "facturia-matching",
        instructions=INSTRUCTIONS,
    )

    mcp.tool(description=tool_odoo_health.__doc__)(tool_odoo_health)
    mcp.tool(description=tool_search_proveedor.__doc__)(tool_search_proveedor)
    mcp.tool(description=tool_preview_invoice_match.__doc__)(tool_preview_invoice_match)
    mcp.tool(description=tool_confirm_invoice_preview.__doc__)(tool_confirm_invoice_preview)
    mcp.tool(description=tool_import_odoo_draft.__doc__)(tool_import_odoo_draft)

    return mcp


def main() -> None:
    # Allow override before first request
    if os.environ.get("FACTURIA_MATCHING_URL"):
        global _client
        _client = MatchingApiClient(os.environ["FACTURIA_MATCHING_URL"])
    mcp = create_mcp_server()
    mcp.run(transport=os.environ.get("FACTURIA_MCP_TRANSPORT", "stdio"))


if __name__ == "__main__":
    main()
