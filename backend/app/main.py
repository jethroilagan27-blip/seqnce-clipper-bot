"""FastAPI application factory.

Run (from backend/):  uv run uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import auth, db
from .api import auth as auth_api
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
        db.purge_auth()
        purge_old_jobs(cfg.retention_days)
        worker = Worker()
        worker.start()
        yield
        worker.stop()

    # With accounts on, don't publish the interactive API docs to the whole internet.
    docs = None if cfg.auth_enabled else "/docs"
    app = FastAPI(
        title="Seqnce", version="0.1.0", lifespan=lifespan,
        docs_url=docs, redoc_url=None, openapi_url=None if cfg.auth_enabled else "/openapi.json",
    )
    @app.middleware("http")
    async def guard_upload(request: Request, call_next):
        """Turn away bad uploads BEFORE their (up to 500 MB) body is read.

        FastAPI parses a multipart body before running dependencies, so without this a stranger
        could make the server spool a huge file just to be told "please sign in"."""
        if request.method == "POST" and request.url.path == "/api/videos/upload":
            if cfg.auth_enabled:
                token = auth.bearer_token(request)
                if token is None or db.get_session_user(auth._sha(token)) is None:
                    return JSONResponse({"detail": "Please sign in."}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > cfg.max_upload_bytes + 1024 * 1024:
                return JSONResponse({"detail": f"File is larger than {cfg.max_upload_mb} MB."}, status_code=413)
        return await call_next(request)

    # Added after guard_upload, so CORS is the outermost layer: even the guard's refusals carry CORS headers.
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
        return {"status": "ok", "ffmpeg": ffmpeg_ok, "auth_required": cfg.auth_enabled}

    app.include_router(auth_api.router)
    app.include_router(videos.router)
    app.include_router(jobs.router)
    app.include_router(music.router)
    return app


app = create_app()
