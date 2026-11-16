"""Uploads in pieces, for setups where something in front of the server limits one request (Cloudflare's free plan: 100 MB).

The page cuts a big file into pieces, sends each piece as its own small request, and then tells the endpoint that
normally takes the file (a video upload, a Studio file) to use the finished upload instead. Every piece stays under the
proxy's limit, so the file can be as large as MAX_UPLOAD_MB.

Safety, in the same spirit as the rest of the app:
- every request needs a login (when accounts are on) and a session belongs to the person who made it (someone else's
  looks like a missing one);
- the purpose ("video", "studio") decides, BEFORE any data is sent, whether that person may upload this file at all
  (daily limit, plan, file type, size), so nobody can fill the disk with files they could not use;
- file names are only labels; pieces are stored under server-made names (the piece number), never a client path;
- the exact size of every piece is checked, unfinished sessions are limited per person and deleted after a few hours.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from .auth import User
from .config import get_settings

log = logging.getLogger(__name__)

SESSION_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_SESSIONS_PER_USER = 6
STALE_SECONDS = 12 * 3600
MAX_PIECES = 5000
COPY_BLOCK = 8 * 1024 * 1024

# purpose -> check(user, params, name, size) -> the most bytes this person may send; raises HTTPException to refuse
Check = Callable[[User, dict[str, Any], str, int], int]
PURPOSES: dict[str, Check] = {}


def register(purpose: str, check: Check) -> None:
    PURPOSES[purpose] = check


@dataclass
class Taken:
    """A finished upload, put back together. The caller moves or reads `path`, then calls discard()."""

    id: str
    path: Path
    name: str
    size: int
    params: dict[str, Any]


def root() -> Path:
    return get_settings().storage_dir / "chunks"


def _dir(upload_id: str) -> Path:
    if not SESSION_ID.match(upload_id or ""):
        raise HTTPException(status_code=404, detail="Upload not found")
    return root() / upload_id


def _owner(user: User) -> int | None:
    return user.id if get_settings().auth_enabled else None


def _meta(upload_id: str, user: User) -> dict[str, Any]:
    path = _dir(upload_id) / "meta.json"
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="Upload not found") from None
    if meta.get("user") != _owner(user):  # someone else's upload looks like a missing one (admins included: it is not theirs to finish)
        raise HTTPException(status_code=404, detail="Upload not found")
    return meta


def piece_count(size: int, chunk: int) -> int:
    return -(-size // chunk)


def piece_size(meta: dict[str, Any], index: int) -> int:
    """The exact number of bytes piece `index` must have (every piece is full-size except the last)."""
    n = piece_count(meta["size"], meta["chunk"])
    return meta["chunk"] if index < n - 1 else meta["size"] - meta["chunk"] * (n - 1)


def purge_stale() -> int:
    """Delete sessions that were never finished."""
    base = root()
    if not base.is_dir():
        return 0
    cutoff = time.time() - STALE_SECONDS
    removed = 0
    for d in base.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def _sessions_of(owner: int | None) -> int:
    base = root()
    count = 0
    if base.is_dir():
        for d in base.iterdir():
            try:
                if json.loads((d / "meta.json").read_text(encoding="utf-8")).get("user") == owner:
                    count += 1
            except (OSError, ValueError):
                continue
    return count


def create(user: User, purpose: str, name: str, size: int, params: dict[str, Any]) -> dict[str, Any]:
    check = PURPOSES.get(purpose)
    if check is None:
        raise HTTPException(status_code=422, detail="Unknown kind of upload.")
    if size <= 0:
        raise HTTPException(status_code=422, detail="That file is empty.")
    limit = check(user, params, name, size)  # may refuse for its own reasons (quota, plan, file type)
    if size > limit:
        raise HTTPException(status_code=413, detail=f"That file is bigger than {limit // (1024 * 1024)} MB.")
    purge_stale()
    owner = _owner(user)
    if _sessions_of(owner) >= MAX_SESSIONS_PER_USER:
        raise HTTPException(status_code=429, detail="You have too many unfinished uploads. Wait for them to finish or try again later.")
    chunk = get_settings().chunk_bytes
    if piece_count(size, chunk) > MAX_PIECES:
        raise HTTPException(status_code=413, detail="That file is too large to send.")
    upload_id = uuid.uuid4().hex
    d = root() / upload_id
    d.mkdir(parents=True)
    meta = {"user": owner, "purpose": purpose, "name": name, "size": size, "chunk": chunk, "params": params, "created": time.time()}
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return {"upload_id": upload_id, "chunk_bytes": chunk, "pieces": piece_count(size, chunk)}


def status(user: User, upload_id: str) -> dict[str, Any]:
    meta = _meta(upload_id, user)
    d = _dir(upload_id)
    done = sorted(
        int(p.stem) for p in d.glob("*.part")
        if p.stem.isdigit() and int(p.stem) < piece_count(meta["size"], meta["chunk"]) and p.stat().st_size == piece_size(meta, int(p.stem))
    )
    return {"pieces": piece_count(meta["size"], meta["chunk"]), "received": done, "chunk_bytes": meta["chunk"]}


def piece_path(user: User, upload_id: str, index: int) -> tuple[Path, int]:
    """Where piece `index` is written, and the exact size it must have. Refuses a piece number that doesn't exist."""
    meta = _meta(upload_id, user)
    if index < 0 or index >= piece_count(meta["size"], meta["chunk"]):
        raise HTTPException(status_code=422, detail="That piece number doesn't exist.")
    _dir(upload_id).mkdir(exist_ok=True)
    return _dir(upload_id) / f"{index:06d}.part", piece_size(meta, index)


def take(user: User, upload_id: str, purpose: str) -> Taken:
    """Put the pieces back together into one file. Raises 409 when a piece is missing, so the page can send it again."""
    meta = _meta(upload_id, user)
    if meta["purpose"] != purpose:
        raise HTTPException(status_code=422, detail="This upload was made for something else.")
    d = _dir(upload_id)
    n = piece_count(meta["size"], meta["chunk"])
    missing = [i for i in range(n) if not (d / f"{i:06d}.part").is_file() or (d / f"{i:06d}.part").stat().st_size != piece_size(meta, i)]
    if missing:
        raise HTTPException(status_code=409, detail=f"The upload isn't complete yet ({len(missing)} of {n} pieces are missing). Send it again.")
    whole = d / "whole.bin"
    try:
        with whole.open("wb") as out:
            for i in range(n):
                part = d / f"{i:06d}.part"
                with part.open("rb") as src:
                    shutil.copyfileobj(src, out, COPY_BLOCK)
                part.unlink()  # free the disk as we go: a 2 GB file must not need 4 GB at once
    except OSError as exc:
        shutil.rmtree(d, ignore_errors=True)
        log.error("could not assemble upload %s: %s", upload_id, exc)
        raise HTTPException(status_code=507, detail="The server ran out of room while putting the upload together.") from exc
    if whole.stat().st_size != meta["size"]:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(status_code=422, detail="The upload has the wrong size.")
    return Taken(upload_id, whole, meta["name"], meta["size"], meta["params"])


def discard(upload_id: str) -> None:
    if SESSION_ID.match(upload_id or ""):
        shutil.rmtree(root() / upload_id, ignore_errors=True)
