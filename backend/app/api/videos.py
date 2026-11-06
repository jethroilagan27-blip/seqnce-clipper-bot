"""Upload, preview and download endpoints."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path as FsPath

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from .. import db, stages
from ..config import get_settings
from ..plan.text import clean_instructions
from ..schemas import EditSettings, UploadResponse
from ..services import media
from .jobs import JOB_ID, get_job_or_404

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/videos", tags=["videos"])

CHUNK = 1024 * 1024
ALLOWED_SUFFIXES = {".mp4"}


def _display_name(raw: str | None) -> str:
    """Client filename -> safe label for the UI only (never used as a path)."""
    name = (raw or "video.mp4").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[^\w .()\-]", "_", name).strip() or "video.mp4"
    return name[:120]


def _too_large(limit_mb: int) -> HTTPException:
    return HTTPException(status_code=413, detail=f"File is larger than {limit_mb} MB.")


@router.post("/upload", response_model=UploadResponse, status_code=201)
def upload_video(
    request: Request,
    file: UploadFile = File(...),
    target_duration: int = Form(45),
    captions: bool = Form(True),
    remove_silence: bool = Form(True),
    background_music: bool = Form(False),
    music_track: str | None = Form(None),
    hook: bool = Form(True),
    instructions: str = Form(""),
) -> UploadResponse:
    cfg = get_settings()

    try:
        edit_settings = EditSettings(
            target_duration=target_duration,
            captions=captions,
            remove_silence=remove_silence,
            background_music=background_music,
            music_track=music_track or None,
            hook=hook,
            instructions=clean_instructions(instructions),
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid editing settings") from exc

    display_name = _display_name(file.filename)
    if FsPath(display_name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="Only .mp4 files are supported right now.")

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > cfg.max_upload_bytes + CHUNK:
        raise _too_large(cfg.max_upload_mb)

    job_id = uuid.uuid4().hex
    dest = cfg.uploads_dir / f"{job_id}.mp4"  # server-generated name: no traversal possible

    written = 0
    try:
        with dest.open("wb") as out:
            first = True
            while chunk := file.file.read(CHUNK):
                if first:
                    if chunk[4:8] != b"ftyp":
                        raise HTTPException(status_code=415, detail="This doesn't look like an MP4 file.")
                    first = False
                written += len(chunk)
                if written > cfg.max_upload_bytes:
                    raise _too_large(cfg.max_upload_mb)
                out.write(chunk)
        if written == 0:
            raise HTTPException(status_code=422, detail="The uploaded file is empty.")

        try:
            info = media.probe(dest)
        except media.MediaError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if info.duration > cfg.max_video_duration_s:
            raise HTTPException(
                status_code=413,
                detail=f"Video is longer than {cfg.max_video_duration_s // 60} minutes.",
            )
    except BaseException:
        dest.unlink(missing_ok=True)
        raise

    db.create_job(
        job_id=job_id,
        original_filename=display_name,
        upload_path=str(dest),
        settings=edit_settings.model_dump(),
        metadata=info.to_dict(),
    )
    log.info("job %s: uploaded %s (%.1f MB, %.1fs)", job_id, display_name, written / 1e6, info.duration)
    return UploadResponse(job_id=job_id)


VERSION = Query(None, ge=1, description="Version number; omit for the current one")


def _output_file(job_id: str, version: int | None = None) -> FsPath:
    job = get_job_or_404(job_id)
    if version is not None:
        row = db.get_version(job_id, version)
        if row is None or not row.get("output_path"):
            raise HTTPException(status_code=404, detail="That version doesn't exist")
        path = FsPath(row["output_path"])
    else:
        # A job that is revising still has its previous video; only unfinished first renders are "not ready".
        if not job.get("output_path"):
            raise HTTPException(status_code=409, detail="The edited video is not ready yet")
        path = FsPath(job["output_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The edited video file is missing")
    return path


@router.get("/{job_id}/preview")
def preview_video(job_id: str = JOB_ID, version: int | None = VERSION) -> FileResponse:
    """Inline playback (supports HTTP Range for seeking)."""
    return FileResponse(_output_file(job_id, version), media_type="video/mp4")


@router.get("/{job_id}/download")
def download_video(job_id: str = JOB_ID, version: int | None = VERSION) -> FileResponse:
    suffix = f"-v{version}" if version else ""
    return FileResponse(
        _output_file(job_id, version),
        media_type="video/mp4",
        filename=f"short-{job_id[:8]}{suffix}.mp4",
    )


@router.get("/{job_id}/original")
def original_video(job_id: str = JOB_ID) -> FileResponse:
    """The uploaded source, for side-by-side comparison on the result screen."""
    job = get_job_or_404(job_id)
    path = FsPath(job["upload_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The original video file is missing")
    return FileResponse(path, media_type="video/mp4")
