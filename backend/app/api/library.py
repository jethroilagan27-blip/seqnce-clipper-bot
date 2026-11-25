"""The library: every video one account has made (video mode, photo videos and Studio), newest first.

It only ever lists the signed-in person's own work, admins included. The files themselves are served by the routes
each mode already has (which check ownership again); the paths here are relative to the API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from .. import db
from ..auth import User, current_user
from ..config import get_settings
from ..slideshow import store as photo_store
from ..studio import store as studio_store

router = APIRouter(prefix="/api/library", tags=["library"])

LIMIT = 200


def _exists(path: str | None) -> bool:
    return bool(path) and Path(path).is_file()  # type: ignore[arg-type]


def _videos(owner: int | None) -> list[dict[str, Any]]:
    out = []
    for job in db.list_jobs_for_user(owner, LIMIT):
        ready = _exists(job.get("output_path"))
        working = job["status"] in ("queued", "running")
        if not ready and not working:
            continue  # it failed and left nothing to watch
        jid = job["id"]
        out.append({
            "kind": "video", "id": jid, "title": job["original_filename"],
            "status": "working" if working else "ready",
            "updated_at": job["updated_at"],
            "duration": (job.get("output_metadata_json") or {}).get("duration") if ready else None,
            "thumb": f"/api/videos/{jid}/thumb?t=1&h=144",
            "video": f"/api/videos/{jid}/preview" if ready else None,
            "download": f"/api/videos/{jid}/download" if ready else None,
        })
    return out


def _photo_videos(owner: int | None) -> list[dict[str, Any]]:
    out = []
    for p in photo_store.list_for_user(owner)[:LIMIT]:
        ready = _exists(p.get("output_path"))
        working = p["status"] in photo_store.ACTIVE
        if not ready and not working:
            continue
        pid = p["id"]
        first = next(iter(photo_store.photos(pid)), None)
        count = p["photo_count"]
        out.append({
            "kind": "photos", "id": pid, "title": f"Photo video ({count} photo{'' if count == 1 else 's'})",
            "status": "working" if working else "ready",
            "updated_at": p["updated_at"],
            "duration": (p.get("output_meta_json") or {}).get("duration") if ready else None,
            "thumb": f"/api/slideshows/{pid}/photos/{first['id']}/thumb" if first else None,
            "video": f"/api/slideshows/{pid}/video" if ready else None,
            "download": f"/api/slideshows/{pid}/download" if ready else None,
        })
    return out


def _studio_videos(owner: int | None) -> list[dict[str, Any]]:
    out = []
    for p in studio_store.list_for_user(owner)[:LIMIT]:
        ready = _exists(p.get("output_path"))
        working = p["status"] in studio_store.ACTIVE
        if not ready and not working:
            continue  # a project that was never rendered is not a video yet
        pid = p["id"]
        picture = next((a for a in studio_store.assets(pid) if a["kind"] in ("video", "image")), None)
        out.append({
            "kind": "studio", "id": pid, "title": p["title"],
            "status": "working" if working else "ready",
            "updated_at": p["updated_at"],
            "duration": (p.get("output_meta_json") or {}).get("duration") if ready else None,
            "thumb": f"/api/studio/projects/{pid}/assets/{picture['id']}/thumb" if picture else None,
            "video": f"/api/studio/projects/{pid}/video" if ready else None,
            "download": f"/api/studio/projects/{pid}/download" if ready else None,
        })
    return out


@router.get("")
def library(user: User = Depends(current_user)) -> dict[str, Any]:
    cfg = get_settings()
    owner = user.id if cfg.auth_enabled else None
    items = _videos(owner) + _photo_videos(owner) + _studio_videos(owner)
    items.sort(key=lambda i: i["updated_at"], reverse=True)
    days = cfg.retention_days
    return {
        "items": items,
        # how long things are kept after their last change (None = forever); Studio projects take days to finish
        "keep_days": {"video": days or None, "photos": days or None, "studio": max(days, 30) if days > 0 else None},
    }
