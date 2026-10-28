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
from facturia_matching.mcp.facturia_client import (
    FacturiaApiClient,
    FacturiaApiError,
    extract_init_callback,
)
from facturia_matching.mcp.preview import build_match_preview

INSTRUCTIONS = """
Sos el asistente de FacturIA Matching para contadores.
Flujo obligatorio:
1) preview_invoice_match (process_number) — muestra resumen y gaps.
2) Preguntá al contador si proveedor, montos, IVA y líneas están bien.
3) Si corrige algo, volvé a preview. Si confirma, confirm_invoice_preview.
4) Solo entonces import_odoo_draft con el confirmation_token.
Opcional FacturIA: init_erp_import(process_id) obtiene import_id+token
(GET /api/process/{id}/erp-import/init). Si están en el preview, el import
avisa a FacturIA vía POST /api/erp-imports/webhook (mismo contrato que la UI).
Nunca inventes impuestos ni partner_id. Nunca publiques (posted): solo borrador.
Si falta process_number, pedilo: el OCR/extracción vive en FacturIA; este MCP carga ese proceso.
""".strip()

_store = ConfirmStore()
_client: Optional[MatchingApiClient] = None
_facturia: Optional[FacturiaApiClient] = None


def _api() -> MatchingApiClient:
    global _client
    if _client is None:
        _client = MatchingApiClient()
    return _client


def _facturia_api() -> FacturiaApiClient:
    global _facturia
    if _facturia is None:
        _facturia = FacturiaApiClient()
    return _facturia


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


def tool_init_erp_import(process_id: str) -> Dict[str, Any]:
    """
    Llama FacturIA GET /api/process/{id}/erp-import/init (auth requerida).
    Devuelve import_id + token para avisar el webhook tras importar a Odoo.
    Pasá esos valores a preview_invoice_match o import_odoo_draft.
    """
    try:
        data = _facturia_api().erp_import_init(process_id)
    except FacturiaApiError as exc:
        return _err(exc)
    import_id, token = extract_init_callback(data)
    if import_id is None or not token:
        return {
            "ok": False,
            "error": "init OK pero no trajo import_id/token reconocibles",
            "raw": data,
            "hint": "Revisá el shape de la respuesta FacturIA y avisá al equipo.",
        }
    return {
        "ok": True,
        "process_id": str(process_id).strip(),
        "import_id": import_id,
        "token": token,
        "facturia_base": _facturia_api().base_url,
        "next_step": (
            "Usá import_id+token en preview_invoice_match o import_odoo_draft. "
            "Tras el draft, matching UI hace POST /api/erp-imports/webhook a FacturIA."
        ),
    }


def tool_preview_invoice_match(
    process_number: str,
    empresa: Optional[str] = None,
    odoo_profile: str = "default",
    regenerate: bool = False,
    import_id: Optional[int] = None,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Carga el proceso FacturIA vía matching UI, resume matches/gaps y crea un preview_id.
    No escribe en Odoo. Mostrá el resumen al contador y pedí confirmación.
    Opcional: import_id + token de init_erp_import / deep-link FacturIA.
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
    erp_id = import_id if import_id is not None else None
    erp_tok = (token or "").strip() or None
    rec = _store.create_preview(
        process_number=pn,
        rows=rows,
        summary=summary,
        empresa=empresa or (proceso.get("empresa") if isinstance(proceso, dict) else None),
        odoo_profile=str(profile),
        erp_import_id=erp_id,
        erp_import_token=erp_tok,
    )
    return {
        "ok": True,
        "preview_id": rec.preview_id,
        "preview_expires_minutes": int(_store.preview_ttl_sec // 60),
        "process_number": pn,
        "odoo_profile": rec.odoo_profile,
        "empresa": rec.empresa,
        "row_count": len(rows),
        "erp_import_id": rec.erp_import_id,
        "erp_callback_bound": bool(rec.erp_import_id and rec.erp_import_token),
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
    Si hay import_id+token (args o del preview vía init_erp_import), matching UI
    notifica FacturIA POST /api/erp-imports/webhook.
    """
    try:
        rec = _store.consume_for_import(confirmation_token)
    except ConfirmationError as exc:
        return _err(exc)

    erp_id = import_id if import_id is not None else rec.erp_import_id
    erp_tok = (token or "").strip() or rec.erp_import_token
    rows = list(rec.rows or [])
    if rec.rows_pending_reload or not rows:
        # Portable token / otra instancia Cloud Run: recargar proceso.
        try:
            proceso = _api().get_proceso(
                rec.process_number,
                empresa=rec.empresa,
                odoo_profile=rec.odoo_profile,
            )
            rows = list(proceso.get("rows") or []) if isinstance(proceso, dict) else []
        except MatchingApiError as exc:
            return {
                "ok": False,
                "error": f"No se pudo recargar el proceso para importar: {exc}",
                "process_number": rec.process_number,
            }

    try:
        result = _api().import_odoo(
            rows,
            empresa=rec.empresa,
            odoo_profile=rec.odoo_profile,
            skip_duplicates=skip_duplicates,
            import_id=erp_id,
            token=erp_tok,
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
        "erp_import_id": erp_id,
        "facturia_webhook_requested": bool(erp_id and erp_tok),
        "import_result": result,
        "message": "Import borrador enviado a Odoo. Revisá el resultado con el contador.",
    }


def _make_mcp_server():
    """MCPServer (mcp 2.x) or FastMCP (mcp 1.x)."""
    try:
        from mcp.server.mcpserver import MCPServer as _Server
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as _Server
        except ImportError as exc:  # pragma: no cover
            raise SystemExit(
                "Falta el paquete MCP. Instalá con: pip install 'mcp>=1.2.0'\n"
                f"Detalle: {exc}"
            ) from exc
    return _Server(
        "facturia-matching",
        instructions=INSTRUCTIONS,
    )


def create_mcp_server():
    """Build MCP app with accountant tools (requires optional dependency ``mcp``)."""
    mcp = _make_mcp_server()
    mcp.tool(description=tool_odoo_health.__doc__)(tool_odoo_health)
    mcp.tool(description=tool_search_proveedor.__doc__)(tool_search_proveedor)
    mcp.tool(description=tool_init_erp_import.__doc__)(tool_init_erp_import)
    mcp.tool(description=tool_preview_invoice_match.__doc__)(tool_preview_invoice_match)
    mcp.tool(description=tool_confirm_invoice_preview.__doc__)(tool_confirm_invoice_preview)
    mcp.tool(description=tool_import_odoo_draft.__doc__)(tool_import_odoo_draft)
    return mcp


def _bearer_auth_asgi(app, expected: str):
    """Minimal Bearer gate for remote MCP (Claude static header / ChatGPT)."""

    async def middleware(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return
        headers = {
            k.decode("latin1").lower(): v.decode("latin1")
            for k, v in scope.get("headers") or []
        }
        auth = headers.get("authorization") or ""
        ok = auth == f"Bearer {expected}" or headers.get("x-facturia-mcp-token") == expected
        if not ok:
            body = b'{"error":"unauthorized"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", b'Bearer realm="facturia-mcp"'),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await app(scope, receive, send)

    return middleware


def build_streamable_http_app(*, path: str = "/mcp"):
    """
    ASGI Starlette app for Claude web / ChatGPT remote MCP.

    Endpoint: ``{path}`` (default ``/mcp``). Set ``FACTURIA_MCP_BEARER`` to require
    Authorization: Bearer … (Claude connectors support static request headers).
    """
    if os.environ.get("FACTURIA_MATCHING_URL"):
        global _client
        _client = MatchingApiClient(os.environ["FACTURIA_MATCHING_URL"])

    mcp = create_mcp_server()
    # stateless_http: cada request independiente (mejor en Cloud Run multi-instancia;
    # el confirmation_token es HMAC portable y re-carga el proceso).
    kwargs = {
        "streamable_http_path": path if path.startswith("/") else f"/{path}",
        "stateless_http": True,
        "host": os.environ.get("FACTURIA_MCP_HOST", "0.0.0.0"),
    }
    if not hasattr(mcp, "streamable_http_app"):
        raise SystemExit(
            "Tu paquete mcp no expone streamable_http_app. Actualizá: pip install 'mcp>=1.2'"
        )
    asgi = mcp.streamable_http_app(**kwargs)
    bearer = (os.environ.get("FACTURIA_MCP_BEARER") or "").strip()
    if bearer:
        return _bearer_auth_asgi(asgi, bearer)
    return asgi


def main() -> None:
    # Allow override before first request
    if os.environ.get("FACTURIA_MATCHING_URL"):
        global _client
        _client = MatchingApiClient(os.environ["FACTURIA_MATCHING_URL"])
    mcp = create_mcp_server()
    transport = (os.environ.get("FACTURIA_MCP_TRANSPORT") or "stdio").strip().lower()
    if transport in ("streamable-http", "http", "sse"):
        host = os.environ.get("FACTURIA_MCP_HOST", "0.0.0.0")
        port = int(os.environ.get("FACTURIA_MCP_PORT") or os.environ.get("PORT") or "8081")
        path = os.environ.get("FACTURIA_MCP_PATH", "/mcp")
        if transport == "http":
            transport = "streamable-http"
        run_kwargs: Dict[str, Any] = {"transport": transport, "host": host, "port": port}
        if transport == "streamable-http":
            run_kwargs["stateless_http"] = True
            run_kwargs["streamable_http_path"] = path
        mcp.run(**run_kwargs)
        return
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
