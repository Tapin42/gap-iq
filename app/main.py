"""FastAPI entrypoint: serves the JSON API and the built SPA from one process."""

from __future__ import annotations

import logging
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import REPO_ROOT, get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
)

log = logging.getLogger("gapiq")

SPA_DIR = REPO_ROOT / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.poller import get_supervisor

    supervisor = get_supervisor()
    supervisor.start()
    try:
        yield
    finally:
        await supervisor.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Gap IQ",
        version="0.1.0",
        description="Live race-tracking dashboard: division position and neighbour gaps.",
        lifespan=lifespan,
    )

    # Health first: it must answer even when nothing else is wired up, because its whole
    # job is to be reachable when things are broken.
    from app.health import router as health_router

    app.include_router(health_router)

    from app.api import router as api_router

    app.include_router(api_router, prefix="/api")

    _mount_spa(app)

    log.info(
        "Gap IQ starting: provider=%s edition=%s polling=%s",
        settings.provider,
        settings.edition,
        settings.polling_allowed()[1],
    )
    return app


def _mount_spa(app: FastAPI) -> None:
    """Serve the built SPA, falling back to index.html for client-side routes.

    In development the SPA is served by Vite instead, so a missing dist/ is expected and
    must not stop the API from booting.
    """
    if not SPA_DIR.exists():
        log.info("No built SPA at %s; serving API only (expected in development)", SPA_DIR)
        return

    assets = SPA_DIR / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    index = SPA_DIR / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        candidate = SPA_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
