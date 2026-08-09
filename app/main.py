"""FastAPI application: JSON API plus the static dashboard.

Run locally with:
    uvicorn app.main:app --reload
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import get_settings

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description=(
            "Workflow management for finance processes, with an Azure AI Foundry "
            "assistant over the same data."
        ),
        version="0.1.0",
    )
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    # Mounted last so it cannot shadow /api or /.
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


app = create_app()
