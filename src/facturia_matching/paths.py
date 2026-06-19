"""Project root and static asset paths."""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
STATIC_DIR = PACKAGE_DIR / "static"
HTML_DIR = STATIC_DIR / "html"
CSS_DIR = STATIC_DIR / "css"
JS_DIR = STATIC_DIR / "js"
