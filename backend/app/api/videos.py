"""Upload, preview and download endpoints."""

from __future__ import annotations

import logging
import re
import threading
import uuid
from pathlib import Path as FsPath

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from .. import db, stages, uploadguard
from ..auth import User, current_user, ensure_no_other_active_job, ensure_quota, media_user, spend_quota
from ..config import get_settings
from ..plan.text import clean_instructions
from ..schemas import EditSettings, UploadResponse
from ..services import media
from .jobs import JOB_ID, get_job_or_404

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/videos", tags=["videos"])

CHUNK = 1024 * 1024
uploadguard.register(r"^/api/videos/upload$", lambda: get_settings().max_upload_bytes + CHUNK)
ALLOWED_SUFFIXES = {".mp4"}

THUMB_HEIGHTS = (48, 64, 96, 144)  # the only sizes the filmstrip asks for
_thumb_slots = threading.BoundedSemaphore(3)  # never let a filmstrip hog the CPU while a render runs


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
    user: User = Depends(current_user),
) -> UploadResponse:
    cfg = get_settings()
    ensure_quota(user, "video")  # 429 when today's videos are used up
    ensure_no_other_active_job(user)  # one video at a time per user (keeps the shared queue fair)

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
        spend_quota(user, "video")  # last check, atomic: parallel uploads can't slip past the limit
    except BaseException:
        dest.unlink(missing_ok=True)
        raise

    db.create_job(
        job_id=job_id,
        original_filename=display_name,
        upload_path=str(dest),
        settings=edit_settings.model_dump(),
        metadata=info.to_dict(),
        user_id=user.id if cfg.auth_enabled else None,
    )
    log.info("job %s: uploaded %s (%.1f MB, %.1fs)", job_id, display_name, written / 1e6, info.duration)
    return UploadResponse(job_id=job_id)


VERSION = Query(None, ge=1, description="Version number; omit for the current one")


def _output_file(job_id: str, version: int | None, user: User) -> FsPath:
    job = get_job_or_404(job_id, user)
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
def preview_video(
    job_id: str = JOB_ID, version: int | None = VERSION, user: User = Depends(media_user)
) -> FileResponse:
    """Inline playback (supports HTTP Range for seeking)."""
    return FileResponse(_output_file(job_id, version, user), media_type="video/mp4")


@router.get("/{job_id}/download")
def download_video(
    job_id: str = JOB_ID, version: int | None = VERSION, user: User = Depends(media_user)
) -> FileResponse:
    suffix = f"-v{version}" if version else ""
    return FileResponse(
        _output_file(job_id, version, user),
        media_type="video/mp4",
        filename=f"short-{job_id[:8]}{suffix}.mp4",
    )


@router.get("/{job_id}/original")
def original_video(job_id: str = JOB_ID, user: User = Depends(media_user)) -> FileResponse:
    """The uploaded source, for side-by-side comparison on the result screen."""
    job = get_job_or_404(job_id, user)
    path = FsPath(job["upload_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The original video file is missing")
    return FileResponse(path, media_type="video/mp4")


@router.get("/{job_id}/thumb")
def thumbnail(
    job_id: str = JOB_ID,
    t: float = Query(..., ge=0, le=1_000_000, description="Seconds into the original video"),
    h: int = Query(64, description="Height in pixels: one of 48, 64, 96, 144"),
    user: User = Depends(media_user),
) -> FileResponse:
    """One small JPEG frame of the original video (for the CapCut-style filmstrips).

    Frames are cut on a half-second grid, made on first request with FFmpeg and cached on disk
    (and by the browser), so scrolling around a timeline only ever extracts each frame once.
    """
    job = get_job_or_404(job_id, user)
    if h not in THUMB_HEIGHTS:
        raise HTTPException(status_code=422, detail=f"h must be one of {list(THUMB_HEIGHTS)}")
    src = FsPath(job["upload_path"])
    if not src.is_file():
        raise HTTPException(status_code=404, detail="The original video file is missing")

    duration = float((job.get("metadata_json") or {}).get("duration") or 0)
    slot = int(min(t, max(duration - 0.3, 0.0)) * 2)  # half-second grid, always a bit before the end
    out_dir = get_settings().temp_dir / job_id / "thumbs"
    path = out_dir / f"{h}_{slot:07d}.jpg"
    headers = {"Cache-Control": "private, max-age=86400"}  # a frame of a given job never changes; it is the user's own
    if path.is_file():
        return FileResponse(path, media_type="image/jpeg", headers=headers)

    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part.jpg")
    with _thumb_slots:
        if not path.is_file():  # another request may have made it while we waited
            proc = media.run_tool(
                [
                    get_settings().ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", f"{slot / 2:.1f}", "-i", str(src),
                    "-frames:v", "1", "-an",
                    "-vf", f"scale=-2:{h},format=yuvj420p", "-q:v", "6",  # yuvj = full range, what JPEG expects
                    str(tmp),
                ],
                timeout=60,
            )
            if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < 200:
                tmp.unlink(missing_ok=True)
                log.warning("job %s: thumbnail at %.1fs failed: %s", job_id, slot / 2, proc.stderr.strip()[:200])
                raise HTTPException(status_code=404, detail="No frame at that time")
            tmp.replace(path)
    return FileResponse(path, media_type="image/jpeg", headers=headers)
