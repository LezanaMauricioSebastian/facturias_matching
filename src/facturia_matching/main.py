"""FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from facturia_matching.api.routes import router
from facturia_matching.paths import CSS_DIR, HTML_DIR, JS_DIR

app = FastAPI(title="FacturIA matching UI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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
