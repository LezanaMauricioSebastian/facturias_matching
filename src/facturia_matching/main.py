"""FastAPI application entrypoint."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from facturia_matching.api.routes import router
from facturia_matching.infra.paths import CSS_DIR, HTML_DIR, JS_DIR

app = FastAPI(title="FacturIA matching UI")
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

# Remote MCP for Claude web / ChatGPT (Streamable HTTP). Opt-in: FACTURIA_MCP_HTTP=1
# Endpoint: https://<host>/mcp  — requires pip extra [mcp].
_mcp_http = (os.environ.get("FACTURIA_MCP_HTTP") or "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
if _mcp_http:
    try:
        from facturia_matching.mcp.server import build_streamable_http_app

        # Sub-app listens at "/" → public URL is https://host/mcp
        app.mount("/mcp", build_streamable_http_app(path="/"), name="facturia_mcp")
    except SystemExit:
        pass
    except Exception as exc:  # pragma: no cover
        import logging

        logging.getLogger(__name__).warning("FACTURIA_MCP_HTTP=1 but MCP failed to mount: %s", exc)


@app.middleware("http")
async def no_cache_static_modules(request, call_next):
    """Evita 304 stale de ES modules durante desarrollo/iteración de UI."""
    response = await call_next(request)
    path = request.url.path or ""
    if path.startswith("/js/") or path.startswith("/css/"):
        # no-store: el grafo de ES modules no debe reutilizarse tras un deploy de UI.
        response.headers["Cache-Control"] = "no-store"
    return response

