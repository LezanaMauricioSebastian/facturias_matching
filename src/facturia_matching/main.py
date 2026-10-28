"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from facturia_matching.api.routes import router
from facturia_matching.infra.paths import CSS_DIR, HTML_DIR, JS_DIR

logger = logging.getLogger(__name__)

_mcp_http = (os.environ.get("FACTURIA_MCP_HTTP") or "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
_mcp_asgi: Any = None
_mcp_session_manager: Any = None

if _mcp_http:
    try:
        from facturia_matching.mcp.server import prepare_remote_mcp

        # Sub-app at path "/" → public URL https://host/mcp/ (and /mcp via rewrite)
        _mcp_asgi, _mcp_session_manager = prepare_remote_mcp(path="/")
        logger.info("MCP Streamable HTTP prepared for mount at /mcp")
    except SystemExit as exc:
        logger.warning("FACTURIA_MCP_HTTP=1 but MCP unavailable: %s", exc)
    except Exception as exc:  # pragma: no cover
        logger.warning("FACTURIA_MCP_HTTP=1 but MCP failed to prepare: %s", exc)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # MCP SDK requires session_manager.run() for the Streamable HTTP task group.
    if _mcp_session_manager is not None:
        async with _mcp_session_manager.run():
            yield
    else:
        yield


app = FastAPI(title="FacturIA matching UI", lifespan=_lifespan, redirect_slashes=False)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if HTML_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(HTML_DIR)), name="static")

if CSS_DIR.is_dir():
    app.mount("/css", StaticFiles(directory=str(CSS_DIR)), name="css")

if JS_DIR.is_dir():
    app.mount("/js", StaticFiles(directory=str(JS_DIR)), name="js")

app.include_router(router)

if _mcp_asgi is not None:
    app.mount("/mcp", _mcp_asgi, name="facturia_mcp")


@app.middleware("http")
async def rewrite_mcp_path(request: Request, call_next):
    """Claude hits /mcp (no slash); Starlette mount only serves /mcp/ → rewrite."""
    if request.scope.get("path") == "/mcp":
        request.scope["path"] = "/mcp/"
    return await call_next(request)


@app.get("/.well-known/oauth-protected-resource")
@app.get("/.well-known/oauth-protected-resource/mcp")
@app.get("/.well-known/oauth-protected-resource/mcp/")
async def oauth_protected_resource_metadata(request: Request):
    """Authless MCP: tell Claude there is no authorization server (no login)."""
    base = str(request.base_url).rstrip("/")
    return JSONResponse(
        {
            "resource": f"{base}/mcp/",
            "authorization_servers": [],
            "bearer_methods_supported": [],
            "resource_documentation": f"{base}/docs/mcp.md",
        }
    )


@app.get("/.well-known/oauth-authorization-server")
async def oauth_authorization_server_absent():
    """No OAuth on this host — 404 without WWW-Authenticate (authless)."""
    return JSONResponse({"error": "not_supported", "message": "No OAuth on this MCP (authless)"}, status_code=404)


@app.middleware("http")
async def no_cache_static_modules(request, call_next):
    """Evita 304 stale de ES modules durante desarrollo/iteración de UI."""
    response = await call_next(request)
    path = request.url.path or ""
    if path.startswith("/js/") or path.startswith("/css/"):
        # no-store: el grafo de ES modules no debe reutilizarse tras un deploy de UI.
        response.headers["Cache-Control"] = "no-store"
    return response
