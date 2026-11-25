"""HTTP API for Studio: /api/studio/...

Same rules as the rest of the app: every route needs a login when accounts are on, a project belongs to the
user who made it (someone else's looks like a missing one), uploads are checked before they are read, and
every route (apart from the files the browser loads itself) needs the "studio" feature on the account.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path as FsPath
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import auth, chunked, uploadguard
from ..services import playback
from ..auth import User, can_access, current_user, ensure_quota, media_user, spend_quota
from ..config import get_settings
from ..filenames import keep_extension
from . import chat, engine, ingest, store
from .schemas import (
    AUDIO_SUFFIXES,
    FONT_SUFFIXES,
    IMAGE_SUFFIXES,
    MAX_BATCH_BYTES,
    MAX_SCENES_HARD,
    MAX_VISUALS_PER_SCENE,
    VIDEO_SUFFIXES,
    StudioDoc,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/studio", tags=["studio"])

PROJECT_ID = Path(pattern=r"^[0-9a-f]{32}$", description="Studio project id")
ASSET_ID = Path(pattern=r"^[0-9a-f]{16}$", description="Studio file id")
SCENE_ID = r"^[A-Za-z0-9_-]{1,40}$"

# one request is usually one file; allow the server's own upload limit plus a little for the form around it
uploadguard.register(r"^/api/studio/projects/[0-9a-f]{32}/assets$", lambda: max(MAX_BATCH_BYTES, get_settings().max_upload_bytes + 16 * 1024 * 1024))

NO_STUDIO = "Studio isn't included in your plan. Ask the Seqnce team to switch it on for your account."


def _owner_id(user: User) -> int | None:
    return user.id if get_settings().auth_enabled else None


def _feats(user: User) -> dict[str, Any]:
    return auth.require_feature(user, "studio", NO_STUDIO)


def _project_or_404(project_id: str, user: User) -> dict[str, Any]:
    project = store.get(project_id)
    if project is None or not can_access(user, {"user_id": project["user_id"]}):
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _editable(project: dict[str, Any]) -> None:
    if project["status"] in store.ACTIVE:
        raise HTTPException(status_code=409, detail="The video is being made right now. Wait for it to finish.")


def _limits(feats: dict[str, Any]) -> dict[str, Any]:
    keys = ("studio_max_projects", "studio_max_scenes", "studio_max_minutes", "studio_max_height", "studio_max_assets",
            "studio_max_storage_mb", "studio_max_file_mb", "studio_renders_per_day", "studio_crossfade", "studio_text_effects",
            "studio_overlays", "studio_grid", "studio_credits", "studio_ducking", "studio_auto_montage", "studio_custom_fonts",
            "studio_ai_chat")
    return {k.removeprefix("studio_"): feats[k] for k in keys} | {"max_visuals_per_scene": MAX_VISUALS_PER_SCENE}


def _family(project_id: str, asset: dict[str, Any]) -> str | None:
    """The name a text has to ask for to use an uploaded font."""
    try:
        return ingest.font_family(store.project_dir(project_id) / "assets" / asset["file"])
    except ingest.AssetError:
        return None


def _out(project: dict[str, Any], feats: dict[str, Any]) -> dict[str, Any]:
    pid = project["id"]
    asset_rows = store.assets(pid)
    refs = engine.asset_refs(pid)
    doc = StudioDoc.model_validate(project["doc_json"])
    scene_info, total = engine.describe_scenes(doc, refs)
    n_assets, n_bytes = store.asset_totals(pid)
    meta = project.get("output_meta_json")
    return {
        "id": pid,
        "title": project["title"],
        "status": project["status"],
        "progress": project["progress"],
        "stage": project.get("stage_text"),
        "error": project.get("error"),
        "render": {"kind": project.get("render_kind"), "scene": project.get("render_scene")},
        "doc": doc.model_dump(),  # filled in with defaults, so projects saved before a tool existed still open
        "assets": [
            {"id": a["id"], "kind": a["kind"], "name": a["original_name"], "folder": a["folder"], "width": a["width"], "height": a["height"],
             "duration": a["duration"], "has_audio": bool(a["has_audio"]), "size_bytes": a["size_bytes"],
             "family": _family(pid, a) if a["kind"] == "font" else None}
            for a in asset_rows
        ],
        "scenes": scene_info,
        "total_seconds": total,
        "has_output": bool(project.get("output_path")),
        "output": ({k: meta[k] for k in ("duration", "width", "height", "size_bytes") if k in meta} if meta else None),
        "preview": {"scene": project.get("preview_scene") or None} if project.get("preview_path") else None,
        "usage": {"assets": n_assets, "bytes": n_bytes},
        "limits": _limits(feats),
        "created_at": project["created_at"],
        "updated_at": project["updated_at"],
    }


# ---- what the page needs to know ------------------------------------------------

@router.get("/info")
def info(user: User = Depends(current_user)) -> dict[str, Any]:
    feats = _feats(user)
    return {
        "limits": _limits(feats),
        "fonts": engine.font_families(),
        "accepts": {"video": sorted(VIDEO_SUFFIXES), "audio": sorted(AUDIO_SUFFIXES), "image": sorted(IMAGE_SUFFIXES),
                    "font": sorted(FONT_SUFFIXES) if feats["studio_custom_fonts"] else []},
        "max_scenes_hard": MAX_SCENES_HARD,
    }


# ---- projects -------------------------------------------------------------------

class CreateBody(BaseModel):
    title: str = Field(default="Untitled video", max_length=80)


@router.post("/projects", status_code=201)
def create_project(body: CreateBody | None = None, user: User = Depends(current_user)) -> dict[str, str]:
    feats = _feats(user)
    if store.count_for_user(_owner_id(user)) >= feats["studio_max_projects"]:
        raise HTTPException(status_code=409, detail=f"You can keep {feats['studio_max_projects']} Studio project(s). Delete an old one first.")
    doc = StudioDoc(title=body.title if body else "Untitled video")
    project_id = uuid.uuid4().hex
    store.create(project_id, _owner_id(user), doc.title, doc.model_dump())
    return {"id": project_id}


@router.get("/projects")
def list_projects(user: User = Depends(current_user)) -> dict[str, Any]:
    _feats(user)
    rows = store.list_for_user(_owner_id(user), everyone=get_settings().auth_enabled and user.is_admin)
    return {"projects": [
        {"id": r["id"], "title": r["title"], "status": r["status"], "asset_count": r["asset_count"],
         "scene_count": len(r["doc_json"].get("scenes", [])), "has_output": bool(r.get("output_path")),
         "updated_at": r["updated_at"]}
        for r in rows
    ]}


@router.get("/projects/{project_id}")
def get_project(project_id: str = PROJECT_ID, user: User = Depends(current_user)) -> dict[str, Any]:
    feats = _feats(user)
    return _out(_project_or_404(project_id, user), feats)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str = PROJECT_ID, user: User = Depends(current_user)) -> None:
    _feats(user)
    _editable(_project_or_404(project_id, user))
    store.delete(project_id)


@router.put("/projects/{project_id}/doc")
def put_doc(body: StudioDoc, project_id: str = PROJECT_ID, user: User = Depends(current_user)) -> dict[str, Any]:
    """Save the whole project document (scenes and everything in them)."""
    feats = _feats(user)
    project = _project_or_404(project_id, user)
    _editable(project)
    known = {a["id"] for a in store.assets(project_id)}
    unknown = body.asset_ids() - known
    if unknown:
        raise HTTPException(status_code=422, detail="A scene uses a file that isn't in this project (it may have been deleted). Reload the page.")
    problems = engine.check_doc_allowed(body, feats)
    if problems:
        raise HTTPException(status_code=403, detail=problems[0])
    store.update(project_id, title=body.title, doc_json=body.model_dump())
    return _out(store.get(project_id) or {}, feats)


# ---- files ----------------------------------------------------------------------

@router.post("/projects/{project_id}/assets")
def upload_assets(
    project_id: str = PROJECT_ID,
    files: list[UploadFile] = File(...),
    folders: list[str] = Form(default=[]),  # the folder each file came from (same order as files); a label for you and the AI
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Add clips, audio files and pictures (one or a few per request; the page sends them one at a time)."""
    feats = _feats(user)
    project = _project_or_404(project_id, user)
    _editable(project)
    added: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for index, f in enumerate(files):
        name = keep_extension((f.filename or "file").replace("\\", "/").rsplit("/", 1)[-1])  # long names keep their ".mp4"
        folder = ingest.clean_folder(folders[index] if index < len(folders) else "")
        result = _add_one(project_id, feats, f.file, name, folder)
        if "reason" in result:
            rejected.append(result)
        else:
            added.append(result)
    return {"added": added, "rejected": rejected, "project": _out(store.get(project_id) or {}, feats)}


def _add_one(project_id: str, feats: dict[str, Any], fileobj: Any, name: str, folder: str) -> dict[str, Any]:
    """Check, store and register one file. Returns the added file, or {"name", "reason"} when it was refused."""
    base = store.project_dir(project_id)
    count, used = store.asset_totals(project_id)
    if count >= feats["studio_max_assets"]:
        return {"name": name, "reason": f"A project holds at most {feats['studio_max_assets']} files."}
    if ingest.kind_of(name) == "font" and not feats["studio_custom_fonts"]:
        return {"name": name, "reason": "Uploading your own fonts isn't included in your plan."}
    room = feats["studio_max_storage_mb"] * 1024 * 1024 - used
    if room <= 0:
        return {"name": name, "reason": f"This project is full ({feats['studio_max_storage_mb']} MB). Delete files you don't use."}
    asset_id = uuid.uuid4().hex[:16]  # server-made name: nothing from the client reaches the file system
    try:
        got = ingest.ingest(fileobj, name, base, asset_id, min(feats["studio_max_file_mb"] * 1024 * 1024, room))
    except ingest.AssetError as exc:
        return {"name": name, "reason": str(exc)}
    # Uploads arrive side by side (the page sends three at once): the numbers read above may be out of date,
    # so the limits are checked again, atomically, at the moment the file is kept.
    refused = store.add_asset(
        project_id, asset_id, got.kind, name, got.file, width=got.width, height=got.height, duration=got.duration,
        has_audio=got.has_audio, size_bytes=got.size_bytes, folder=folder,
        max_count=feats["studio_max_assets"], max_bytes=feats["studio_max_storage_mb"] * 1024 * 1024,
    )
    if refused:
        (base / "assets" / got.file).unlink(missing_ok=True)
        (base / "thumbs" / f"{asset_id}.jpg").unlink(missing_ok=True)
        return {"name": name, "reason": (f"A project holds at most {feats['studio_max_assets']} files." if refused == "count"
                                         else f"This project is full ({feats['studio_max_storage_mb']} MB). Delete files you don't use.")}
    return {"id": asset_id, "kind": got.kind, "name": name, "folder": folder}


class FromUploadBody(BaseModel):
    upload_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    folder: str = Field(default="", max_length=400)


@router.post("/projects/{project_id}/assets/from-upload")
def add_asset_from_upload(body: FromUploadBody, project_id: str = PROJECT_ID, user: User = Depends(current_user)) -> dict[str, Any]:
    """Add a file the page sent in pieces (see chunked.py). Same checks as a normal upload."""
    feats = _feats(user)
    project = _project_or_404(project_id, user)
    _editable(project)
    taken = chunked.take(user, body.upload_id, "studio")
    try:
        if taken.params.get("project_id") != project_id:
            raise HTTPException(status_code=422, detail="This upload was made for another project.")
        with taken.path.open("rb") as fileobj:
            name = keep_extension(taken.name.replace("\\", "/").rsplit("/", 1)[-1])  # a label only, never a path
            result = _add_one(project_id, feats, fileobj, name, ingest.clean_folder(body.folder))
    finally:
        chunked.discard(taken.id)
    return {"added": [] if "reason" in result else [result], "rejected": [result] if "reason" in result else [],
            "project": _out(store.get(project_id) or {}, feats)}


def _check_chunked_upload(user: User, params: dict[str, Any], name: str, size: int) -> int:
    """Called when the page announces a big file, before any of it is sent: may this person add it to this project?"""
    feats = _feats(user)
    project_id = str(params.get("project_id", ""))
    if not re.fullmatch(r"[0-9a-f]{32}", project_id):
        raise HTTPException(status_code=422, detail="Unknown project.")
    _editable(_project_or_404(project_id, user))
    count, used = store.asset_totals(project_id)
    if count >= feats["studio_max_assets"]:
        raise HTTPException(status_code=409, detail=f"A project holds at most {feats['studio_max_assets']} files.")
    kind = ingest.kind_of(name)
    if kind is None:
        raise HTTPException(status_code=415, detail="Use a video (MP4, MOV, MKV, WebM), an audio file or a picture.")
    if kind == "font" and not feats["studio_custom_fonts"]:
        raise HTTPException(status_code=403, detail="Uploading your own fonts isn't included in your plan.")
    room = feats["studio_max_storage_mb"] * 1024 * 1024 - used
    if room <= 0:
        raise HTTPException(status_code=409, detail=f"This project is full ({feats['studio_max_storage_mb']} MB). Delete files you don't use.")
    return min(feats["studio_max_file_mb"] * 1024 * 1024, room)


chunked.register("studio", _check_chunked_upload)


@router.delete("/projects/{project_id}/assets/{asset_id}")
def delete_asset(project_id: str = PROJECT_ID, asset_id: str = ASSET_ID, user: User = Depends(current_user)) -> dict[str, Any]:
    """Delete a file. Every scene that used it loses that clip / voice-over / music."""
    feats = _feats(user)
    project = _project_or_404(project_id, user)
    _editable(project)
    if store.get_asset(project_id, asset_id) is None:
        raise HTTPException(status_code=404, detail="File not found")
    doc = StudioDoc.model_validate(project["doc_json"]).without_assets({asset_id})
    store.update(project_id, doc_json=doc.model_dump())
    store.delete_asset(project_id, asset_id)
    return _out(store.get(project_id) or {}, feats)


_PRIVATE = {"Cache-Control": "private, max-age=3600"}


@router.get("/projects/{project_id}/assets/{asset_id}/thumb")
def asset_thumb(project_id: str = PROJECT_ID, asset_id: str = ASSET_ID, user: User = Depends(media_user)) -> FileResponse:
    _project_or_404(project_id, user)
    path = store.project_dir(project_id) / "thumbs" / f"{asset_id}.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No thumbnail")
    return FileResponse(path, media_type="image/jpeg", headers=_PRIVATE)


@router.get("/projects/{project_id}/assets/{asset_id}/file")
def asset_file(project_id: str = PROJECT_ID, asset_id: str = ASSET_ID, user: User = Depends(media_user)) -> FileResponse:
    _project_or_404(project_id, user)
    asset = store.get_asset(project_id, asset_id)
    path = store.project_dir(project_id) / "assets" / asset["file"] if asset else None
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, headers=_PRIVATE)


# ---- the AI assistant -------------------------------------------------------------

class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=chat.MAX_MESSAGE_CHARS)


def _chat_out(project_id: str, feats: dict[str, Any], project: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "messages": store.chat_history(project_id),
        "can_undo": store.get_backup(project_id) is not None,
        "project": _out(project or store.get(project_id) or {}, feats),
    }


@router.get("/projects/{project_id}/chat")
def get_chat(project_id: str = PROJECT_ID, user: User = Depends(current_user)) -> dict[str, Any]:
    feats = auth.require_feature(user, "studio_ai_chat", "The AI assistant isn't included in your plan. Ask the Seqnce team to switch it on.")
    _project_or_404(project_id, user)
    return _chat_out(project_id, feats)


@router.post("/projects/{project_id}/chat")
def post_chat(body: ChatBody, project_id: str = PROJECT_ID, user: User = Depends(current_user)) -> dict[str, Any]:
    """Give the assistant a script or an instruction. It rebuilds the scenes (the old version is kept so it can be undone)."""
    feats = auth.require_feature(user, "studio_ai_chat", "The AI assistant isn't included in your plan. Ask the Seqnce team to switch it on.")
    project = _project_or_404(project_id, user)
    _editable(project)
    ensure_quota(user, "chat")  # the AI is free-tier: it shares the daily chat limit with the video chat
    doc = StudioDoc.model_validate(project["doc_json"])
    fonts = engine.font_families() + [
        f for f in (_family(project_id, a) for a in store.assets(project_id) if a["kind"] == "font") if f
    ]
    try:
        outcome = chat.run_turn(body.message, doc, store.assets(project_id), feats, fonts, store.chat_history(project_id), _owner_id(user))
    except chat.ChatUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except chat.ChatFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    spend_quota(user, "chat")  # only a message that got an answer is counted
    reply = outcome.message + ("\n\n" + "\n".join(f"• {n}" for n in outcome.notes) if outcome.notes else "")
    store.add_chat(project_id, "user", body.message[:3000] + ("…" if len(body.message) > 3000 else ""))
    store.add_chat(project_id, "assistant", reply)
    if outcome.new_doc is not None:
        store.set_backup(project_id, doc.model_dump())
        store.update(project_id, doc_json=outcome.new_doc.model_dump())
    return _chat_out(project_id, feats)


@router.post("/projects/{project_id}/chat/undo")
def undo_chat(project_id: str = PROJECT_ID, user: User = Depends(current_user)) -> dict[str, Any]:
    """Put the scenes back the way they were before the assistant's last change."""
    feats = auth.require_feature(user, "studio_ai_chat", "The AI assistant isn't included in your plan. Ask the Seqnce team to switch it on.")
    project = _project_or_404(project_id, user)
    _editable(project)
    backup = store.get_backup(project_id)
    if backup is None:
        raise HTTPException(status_code=409, detail="There is nothing to undo.")
    doc = StudioDoc.model_validate(backup)
    gone = doc.asset_ids() - {a["id"] for a in store.assets(project_id)}
    store.update(project_id, doc_json=(doc.without_assets(gone) if gone else doc).model_dump())
    store.set_backup(project_id, None)
    store.add_chat(project_id, "assistant", "Undone: the scenes are back the way they were before my last change.")
    return _chat_out(project_id, feats)


# ---- making the video -----------------------------------------------------------

class RenderBody(BaseModel):
    kind: Literal["final", "preview"] = "final"
    scene_id: str | None = Field(default=None, pattern=SCENE_ID)  # preview of just this scene (None = the whole video)


@router.post("/projects/{project_id}/render", status_code=202)
def start_render(body: RenderBody, project_id: str = PROJECT_ID, user: User = Depends(current_user)) -> dict[str, Any]:
    cfg = get_settings()
    feats = _feats(user)
    project = _project_or_404(project_id, user)
    _editable(project)
    if body.kind == "final" and body.scene_id is not None:
        raise HTTPException(status_code=422, detail="The finished video is always the whole project. Use a preview for one scene.")
    try:
        engine.prepare(project, body.kind, body.scene_id)  # refuse a problem before it costs the user a render
    except engine.StudioError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if cfg.auth_enabled and not user.is_admin and store.count_active_for_user(user.id) >= cfg.max_active_jobs_per_user:
        raise HTTPException(status_code=409, detail="You already have a video being made. Wait for it to finish.")
    if body.kind == "final":  # previews are free; the finished video counts against the plan's daily limit
        ensure_quota(user, "studio")
        spend_quota(user, "studio")
    store.update(project_id, status="queued", progress=0, error=None, stage_text="Waiting its turn",
                 render_kind=body.kind, render_scene=body.scene_id)
    return _out(store.get(project_id) or {}, feats)


def _file(project_id: str, user: User, which: Literal["output", "preview"], scene: str | None = None) -> FsPath:
    project = _project_or_404(project_id, user)
    key = "output_path" if which == "output" else "preview_path"
    path = FsPath(project[key]) if project.get(key) else None
    if which == "preview":
        wanted = store.project_dir(project_id) / "previews" / f"{scene or 'all'}.mp4"  # any preview made earlier, not only the latest
        path = wanted if wanted.is_file() else None
    if path is None or not path.is_file():
        raise HTTPException(status_code=409, detail="That video isn't ready yet.")
    return path


@router.get("/projects/{project_id}/preview")
def preview(project_id: str = PROJECT_ID, scene: str | None = Query(None, pattern=SCENE_ID), user: User = Depends(media_user)) -> FileResponse:
    return FileResponse(_file(project_id, user, "preview", scene), media_type="video/mp4", headers={"Cache-Control": "no-store"})


@router.get("/projects/{project_id}/video")
def video(project_id: str = PROJECT_ID, user: User = Depends(media_user)) -> FileResponse:
    return FileResponse(playback.best(_file(project_id, user, "output")), media_type="video/mp4", headers={"Cache-Control": "no-store"})


@router.get("/projects/{project_id}/download")
def download(project_id: str = PROJECT_ID, user: User = Depends(media_user)) -> FileResponse:
    project = _project_or_404(project_id, user)
    name = "".join(c if c.isalnum() or c in " -_" else "" for c in project["title"]).strip() or "studio-video"
    return FileResponse(_file(project_id, user, "output"), media_type="video/mp4", filename=f"{name}.mp4")
