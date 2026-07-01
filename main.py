#!/usr/bin/env python3
"""Levantar la UI en local: python main.py"""

import os

from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8080"))
    reload = os.getenv("RELOAD", "1").strip().lower() not in ("0", "false", "no")

    uvicorn.run(
        "facturia_matching.main:app",
        host=host,
        port=port,
        reload=reload,
    )
