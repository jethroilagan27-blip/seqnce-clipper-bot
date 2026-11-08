"""HTTP API for photo mode: /api/slideshows/...

Same rules as the rest of the app: every route needs a login when accounts are on, a project belongs to the
user who made it (someone else's looks like a missing one), and uploads are checked before they are read.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path as FsPath
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Path, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import uploadguard
from ..auth import (
    User,
    can_access,
    current_user,
    ensure_quota,
    media_user,
    spend_quota,
)
from ..config import get_settings
from ..services import media
from . import images, store
from .schemas import (
    MAX_BATCH_BYTES,
    MAX_MUSIC_BYTES,
    MAX_PHOTO_BYTES,
    MAX_PHOTOS,
    MAX_PROJECTS_PER_USER,
    MUSIC_SUFFIXES,
    SlideshowSettings,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/slideshows", tags=["photos"])

PROJECT_ID = Path(pattern=r"^[0-9a-f]{32}$", description="Photo project id")
PHOTO_ID = Path(pattern=r"^[0-9a-f]{16}$", description="Photo id")

uploadguard.register(r"^/api/slideshows/[0-9a-f]{32}/photos$", lambda: MAX_BATCH_BYTES)
uploadguard.register(r"^/api/slideshows/[0-9a-f]{32}/music$", lambda: MAX_MUSIC_BYTES + 1024 * 1024)


def _owner_id(user: User) -> int | None:
    return user.id if get_settings().auth_enabled else None


def _project_or_404(project_id: str, user: User) -> dict[str, Any]:
    project = store.get(project_id)
    if project is None or not can_access(user, {"user_id": project["user_id"]}):
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _editable(project: dict[str, Any]) -> None:
    if project["status"] in store.ACTIVE:
        raise HTTPException(status_code=409, detail="The video is being made right now. Wait for it to finish.")


def _out(project: dict[str, Any]) -> dict[str, Any]:
    photos = store.photos(project["id"])
    meta = project.get("output_meta_json")
    return {
        "id": project["id"],
        "status": project["status"],
        "progress": project["progress"],
        "error": project.get("error"),
        "settings": project["settings_json"],
        "photos": [
            {"id": p["id"], "position": p["position"], "name": p["original_name"], "width": p["width"],
             "height": p["height"], "taken_at": p["taken_at"]}
            for p in photos
        ],
        "music": {"name": project["music_name"], "duration": project["music_duration"]} if project.get("music_file") else None,
        "has_output": bool(project.get("output_path")),
        "output": ({k: meta[k] for k in ("duration", "width", "height", "size_bytes") if k in meta} if meta else None),
        "limits": {"max_photos": MAX_PHOTOS, "max_photo_mb": MAX_PHOTO_BYTES // (1024 * 1024),
                   "max_music_mb": MAX_MUSIC_BYTES // (1024 * 1024)},
        "created_at": project["created_at"],
        "updated_at": project["updated_at"],
    }


@router.post("", status_code=201)
def create_project(user: User = Depends(current_user)) -> dict[str, str]:
    cfg = get_settings()
    if cfg.auth_enabled and not user.is_admin and store.count_for_user(user.id) >= MAX_PROJECTS_PER_USER:
        raise HTTPException(status_code=409, detail=f"You can keep {MAX_PROJECTS_PER_USER} photo projects. Delete an old one first.")
    project_id = uuid.uuid4().hex
    store.create(project_id, _owner_id(user), SlideshowSettings().model_dump())
    return {"id": project_id}


@router.get("")
def list_projects(user: User = Depends(current_user)) -> dict[str, Any]:
    rows = store.list_for_user(_owner_id(user), everyone=get_settings().auth_enabled and user.is_admin)
    return {"projects": [
        {"id": r["id"], "status": r["status"], "photo_count": r["photo_count"], "has_output": bool(r.get("output_path")),
         "created_at": r["created_at"], "updated_at": r["updated_at"]}
        for r in rows
    ]}


@router.get("/{project_id}")
def get_project(project_id: str = PROJECT_ID, user: User = Depends(current_user)) -> dict[str, Any]:
    return _out(_project_or_404(project_id, user))


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str = PROJECT_ID, user: User = Depends(current_user)) -> None:
    _editable(_project_or_404(project_id, user))
    store.delete(project_id)


@router.post("/{project_id}/photos")
def upload_photos(
    project_id: str = PROJECT_ID, files: list[UploadFile] = File(...), user: User = Depends(current_user)
) -> dict[str, Any]:
    """Add photos (a few per request; the page sends them in batches). They are appended in the order received."""
    project = _project_or_404(project_id, user)
    _editable(project)
    base = store.project_dir(project_id)
    added: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    count = store.photo_count(project_id)
    for f in files:
        name = (f.filename or "photo").replace("\\", "/").rsplit("/", 1)[-1][:120]
        if count >= MAX_PHOTOS:
            rejected.append({"name": name, "reason": f"A project holds at most {MAX_PHOTOS} photos."})
            continue
        f.file.seek(0, 2)
        size = f.file.tell()
        f.file.seek(0)
        if size > MAX_PHOTO_BYTES:
            rejected.append({"name": name, "reason": f"Bigger than {MAX_PHOTO_BYTES // (1024 * 1024)} MB."})
            continue
        photo_id = uuid.uuid4().hex[:16]  # server-made name: nothing from the client reaches the file system
        try:
            width, height, taken = images.ingest(f.file, base, photo_id)
        except images.PhotoError as exc:
            rejected.append({"name": name, "reason": str(exc)})
            continue
        store.add_photo(project_id, photo_id, name, width, height, taken)
        count += 1
        added.append({"id": photo_id, "name": name, "width": width, "height": height, "taken_at": taken})
    return {"added": added, "rejected": rejected, "photo_count": count}


class OrderBody(BaseModel):
    order: list[str] = Field(max_length=MAX_PHOTOS)


@router.put("/{project_id}/order")
def set_order(body: OrderBody, project_id: str = PROJECT_ID, user: User = Depends(current_user)) -> dict[str, Any]:
    """The photos in their new order. Photos left out of the list are deleted."""
    _editable(_project_or_404(project_id, user))
    gone = store.reorder(project_id, body.order)
    base = store.project_dir(project_id)
    for pid in gone:
        for sub in ("photos", "previews", "thumbs"):
            (base / sub / f"{pid}.jpg").unlink(missing_ok=True)
    return _out(store.get(project_id) or {})


@router.put("/{project_id}/settings")
def put_settings(body: SlideshowSettings, project_id: str = PROJECT_ID, user: User = Depends(current_user)) -> dict[str, Any]:
    _editable(_project_or_404(project_id, user))
    store.update(project_id, settings_json=body.model_dump())
    return _out(store.get(project_id) or {})


def _audio_duration(path: FsPath) -> float | None:
    proc = media.run_tool(
        [get_settings().ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        timeout=60,
    )
    try:
        value = float(proc.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        return None
    return value if value > 0 else None


@router.post("/{project_id}/music")
def upload_music(project_id: str = PROJECT_ID, file: UploadFile = File(...), user: User = Depends(current_user)) -> dict[str, Any]:
    project = _project_or_404(project_id, user)
    _editable(project)
    name = (file.filename or "music").replace("\\", "/").rsplit("/", 1)[-1][:120]
    suffix = FsPath(name).suffix.lower()
    if suffix not in MUSIC_SUFFIXES:
        raise HTTPException(status_code=415, detail="Use an MP3, WAV, M4A, AAC, OGG or FLAC file.")
    base = store.project_dir(project_id)
    stored = f"music{suffix}"  # server-made name
    dest = base / stored
    written = 0
    try:
        with dest.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_MUSIC_BYTES:
                    raise HTTPException(status_code=413, detail=f"Music is larger than {MAX_MUSIC_BYTES // (1024 * 1024)} MB.")
                out.write(chunk)
        duration = _audio_duration(dest)
        if duration is None:
            raise HTTPException(status_code=422, detail="I can't find any audio in that file.")
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    for other in base.glob("music.*"):  # a replaced track of another type
        if other != dest:
            other.unlink(missing_ok=True)
    store.update(project_id, music_name=name, music_file=stored, music_duration=round(duration, 2))
    return _out(store.get(project_id) or {})


@router.delete("/{project_id}/music")
def delete_music(project_id: str = PROJECT_ID, user: User = Depends(current_user)) -> dict[str, Any]:
    project = _project_or_404(project_id, user)
    _editable(project)
    for f in store.project_dir(project_id).glob("music.*"):
        f.unlink(missing_ok=True)
    store.update(project_id, music_name=None, music_file=None, music_duration=None)
    return _out(store.get(project_id) or {})


@router.post("/{project_id}/render", status_code=202)
def start_render(project_id: str = PROJECT_ID, user: User = Depends(current_user)) -> dict[str, Any]:
    cfg = get_settings()
    project = _project_or_404(project_id, user)
    _editable(project)
    if store.photo_count(project_id) == 0:
        raise HTTPException(status_code=422, detail="Add at least one photo first.")
    if cfg.auth_enabled and not user.is_admin and store.count_active_for_user(user.id) >= cfg.max_active_jobs_per_user:
        raise HTTPException(status_code=409, detail="You already have a video being made. Wait for it to finish.")
    ensure_quota(user, "video")
    spend_quota(user, "video")  # a photo video counts like any other video against the daily limit
    store.update(project_id, status="queued", progress=0, error=None)
    return _out(store.get(project_id) or {})


# ---- files the browser loads itself (media token or header) ----------------

_PRIVATE = {"Cache-Control": "private, max-age=3600"}


@router.get("/{project_id}/photos/{photo_id}/{kind}")
def photo_file(
    project_id: str = PROJECT_ID,
    photo_id: str = PHOTO_ID,
    kind: Literal["thumb", "preview"] = "thumb",
    user: User = Depends(media_user),
) -> FileResponse:
    _project_or_404(project_id, user)
    path = store.project_dir(project_id) / ("thumbs" if kind == "thumb" else "previews") / f"{photo_id}.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Photo not found")
    return FileResponse(path, media_type="image/jpeg", headers=_PRIVATE)


@router.get("/{project_id}/music/file")
def music_file(project_id: str = PROJECT_ID, user: User = Depends(media_user)) -> FileResponse:
    project = _project_or_404(project_id, user)
    path = store.project_dir(project_id) / (project.get("music_file") or "music.none")
    if not project.get("music_file") or not path.is_file():
        raise HTTPException(status_code=404, detail="No music in this project")
    return FileResponse(path, headers=_PRIVATE)


def _output(project_id: str, user: User) -> FsPath:
    project = _project_or_404(project_id, user)
    path = FsPath(project["output_path"]) if project.get("output_path") else None
    if path is None or not path.is_file():
        raise HTTPException(status_code=409, detail="The video isn't ready yet.")
    return path


@router.get("/{project_id}/video")
def video(project_id: str = PROJECT_ID, user: User = Depends(media_user)) -> FileResponse:
    return FileResponse(_output(project_id, user), media_type="video/mp4")


@router.get("/{project_id}/download")
def download(project_id: str = PROJECT_ID, user: User = Depends(media_user)) -> FileResponse:
    return FileResponse(_output(project_id, user), media_type="video/mp4", filename=f"photos-{project_id[:8]}.mp4")
