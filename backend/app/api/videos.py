"""Upload, preview and download endpoints."""

from __future__ import annotations

import logging
import re
import threading
import uuid
from pathlib import Path as FsPath
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from .. import chunked, db, stages, uploadguard
from ..auth import User, current_user, ensure_no_other_active_job, ensure_quota, media_user, spend_quota
from ..config import get_settings
from ..filenames import keep_extension
from ..pipeline import prepare
from ..plan.text import clean_instructions
from ..schemas import EditSettings, UploadResponse
from ..services import media
from .jobs import JOB_ID, get_job_or_404

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/videos", tags=["videos"])

CHUNK = 1024 * 1024
uploadguard.register(r"^/api/videos/upload$", lambda: get_settings().max_upload_bytes + CHUNK)
ALLOWED_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
_QUICKTIME_ATOMS = {b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"}  # what the first box of an MP4 / MOV can be
_EBML = b"\x1a\x45\xdf\xa3"  # MKV / WebM


def _looks_like_video(suffix: str, head: bytes) -> bool:
    """A quick look at the first bytes, so a renamed text file is refused before it is stored. ffprobe has the final say."""
    if suffix in (".mkv", ".webm"):
        return head[:4] == _EBML
    return head[4:8] in _QUICKTIME_ATOMS  # .mp4, .m4v and .mov (older QuickTime files start with moov / mdat)


def _media_type(path: FsPath) -> str:
    return {".mov": "video/quicktime", ".mkv": "video/x-matroska", ".webm": "video/webm"}.get(path.suffix.lower(), "video/mp4")

THUMB_HEIGHTS = (48, 64, 96, 144)  # the only sizes the filmstrip asks for
_thumb_slots = threading.BoundedSemaphore(3)  # never let a filmstrip hog the CPU while a render runs


def _display_name(raw: str | None) -> str:
    """Client filename -> safe label for the UI only (never used as a path)."""
    name = (raw or "video.mp4").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[^\w .()\-]", "_", name).strip() or "video.mp4"
    return keep_extension(name)  # a long download name must not lose its ".mp4" (the file would be refused as "not a video")


def _too_large(limit_mb: int) -> HTTPException:
    return HTTPException(status_code=413, detail=f"File is larger than {limit_mb} MB.")


def _check_chunked_upload(user: User, params: dict[str, Any], name: str, size: int) -> int:
    """Called when the page announces a big video, before any of it is sent."""
    ensure_quota(user, "video")
    ensure_no_other_active_job(user)
    if FsPath(_display_name(name)).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="Use a video file: MP4, MOV, M4V, MKV or WebM.")
    return get_settings().max_upload_bytes


chunked.register("video", _check_chunked_upload)


@router.post("/upload", response_model=UploadResponse, status_code=201)
def upload_video(
    request: Request,
    file: UploadFile | None = File(None),
    upload_id: str = Form(""),  # a finished chunked upload (see chunked.py) instead of `file`
    target_duration: int = Form(45),
    captions: bool = Form(True),
    remove_silence: bool = Form(True),
    background_music: bool = Form(False),
    music_track: str | None = Form(None),
    hook: bool = Form(True),
    instructions: str = Form(""),
    style: str = Form("talking"),  # "highlight" = best moments, no speech needed
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
            style=style,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid editing settings") from exc

    taken = chunked.take(user, upload_id, "video") if upload_id else None  # the pieces, put back together
    try:
        if taken is None and file is None:
            raise HTTPException(status_code=422, detail="No video was sent.")
        display_name = _display_name(taken.name if taken else file.filename)  # type: ignore[union-attr]
        suffix = FsPath(display_name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=415, detail="Use a video file: MP4, MOV, M4V, MKV or WebM.")

        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > cfg.max_upload_bytes + CHUNK:
            raise _too_large(cfg.max_upload_mb)

        job_id = uuid.uuid4().hex
        dest = cfg.uploads_dir / f"{job_id}{suffix}"  # server-generated name (the extension comes from our own list): no traversal possible
        info, written = _store_and_probe(taken, file, dest, suffix, cfg)
        try:
            spend_quota(user, "video")  # last check, atomic: parallel uploads can't slip past the limit
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
    except BaseException:
        if taken is not None:
            chunked.discard(taken.id)
        raise
    if taken is not None:
        chunked.discard(taken.id)

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


def _store_and_probe(taken: chunked.Taken | None, file: UploadFile | None, dest: FsPath, suffix: str, cfg: Any) -> tuple[Any, int]:
    """Put the video at `dest` (from the upload or the pieces), check it, and return (probe info, bytes). Leaves nothing on failure."""
    written = 0
    try:
        if taken is not None:
            with taken.path.open("rb") as head_in:
                if not _looks_like_video(suffix, head_in.read(16)):
                    raise HTTPException(status_code=415, detail=f"This doesn't look like a {suffix[1:].upper()} video file.")
            written = taken.size
            if written > cfg.max_upload_bytes:
                raise _too_large(cfg.max_upload_mb)
            taken.path.replace(dest)  # same disk: no copy
        else:
            assert file is not None
            with dest.open("wb") as out:
                first = True
                while chunk := file.file.read(CHUNK):
                    if first:
                        if not _looks_like_video(suffix, chunk[:16]):
                            raise HTTPException(status_code=415, detail=f"This doesn't look like a {suffix[1:].upper()} video file.")
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
    return info, written


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
    web = prepare.web_copy_path(job_id)  # a browser-friendly copy, made for phone formats a browser may not play (HEVC, MOV)
    if web.is_file():
        return FileResponse(web, media_type="video/mp4")
    return FileResponse(path, media_type=_media_type(path))


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
    tmp = path.with_name(f"{path.stem}.{uuid.uuid4().hex[:8]}.part.jpg")  # two requests for one frame must not share it
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
            try:
                tmp.replace(path)
            except OSError:  # Windows: the same frame was just made by another request and is being sent
                tmp.unlink(missing_ok=True)
                if not path.is_file():
                    raise
    return FileResponse(path, media_type="image/jpeg", headers=headers)
