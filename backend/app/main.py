"""FastAPI application factory.

Run (from backend/):  uv run uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .api import jobs, music, videos
from .config import get_settings
from .retention import purge_old_jobs
from .worker import Worker


def create_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    cfg = get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        db.init_db()
        purge_old_jobs(cfg.retention_days)
        worker = Worker()
        worker.start()
        yield
        worker.stop()

    app = FastAPI(title="Short-Form Video Editing Bot", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, object]:
        from .services import media

        try:
            ffmpeg_ok = media.run_tool([cfg.ffmpeg, "-version"], timeout=10).returncode == 0
        except media.MediaError:
            ffmpeg_ok = False
        return {"status": "ok", "ffmpeg": ffmpeg_ok}

    app.include_router(videos.router)
    app.include_router(jobs.router)
    app.include_router(music.router)
    return app


app = create_app()
