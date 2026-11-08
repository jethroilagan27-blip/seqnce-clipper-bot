"""Database and file layout for photo projects (its own tables, same SQLite file)."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .. import db
from ..config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS slideshows (
    id                TEXT PRIMARY KEY,
    user_id           INTEGER,
    status            TEXT NOT NULL DEFAULT 'draft',   -- draft | queued | rendering | completed | failed
    progress          INTEGER NOT NULL DEFAULT 0,
    settings_json     TEXT NOT NULL,
    music_name        TEXT,
    music_file        TEXT,
    music_duration    REAL,
    error             TEXT,
    output_path       TEXT,
    output_meta_json  TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS slideshow_photos (
    id            TEXT PRIMARY KEY,
    slideshow_id  TEXT NOT NULL,
    position      INTEGER NOT NULL,
    original_name TEXT,
    width         INTEGER,
    height        INTEGER,
    taken_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_slideshow_photos ON slideshow_photos(slideshow_id, position);
"""

_JSON = ("settings_json", "output_meta_json")
ACTIVE = ("queued", "rendering")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_tables() -> None:
    with db.connect() as conn:
        conn.executescript(SCHEMA)


def project_dir(project_id: str) -> Path:
    return get_settings().storage_dir / "slideshows" / project_id


def _row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for col in _JSON:
        if data.get(col):
            data[col] = json.loads(data[col])
    return data


def create(project_id: str, user_id: int | None, settings: dict[str, Any]) -> None:
    now = _now()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO slideshows (id, user_id, settings_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (project_id, user_id, json.dumps(settings), now, now),
        )
    for sub in ("photos", "previews", "thumbs"):
        (project_dir(project_id) / sub).mkdir(parents=True, exist_ok=True)


def get(project_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        return _row(conn.execute("SELECT * FROM slideshows WHERE id = ?", (project_id,)).fetchone())


def update(project_id: str, **fields: Any) -> None:
    for col in _JSON:
        if fields.get(col) is not None:
            fields[col] = json.dumps(fields[col])
    fields["updated_at"] = _now()
    with db.connect() as conn:
        conn.execute(
            f"UPDATE slideshows SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
            (*fields.values(), project_id),
        )


def list_for_user(user_id: int | None, *, everyone: bool = False) -> list[dict[str, Any]]:
    with db.connect() as conn:
        sql = (
            "SELECT s.*, (SELECT COUNT(*) FROM slideshow_photos p WHERE p.slideshow_id = s.id) AS photo_count FROM slideshows s"
        )
        rows = conn.execute(sql + ("" if everyone else " WHERE s.user_id IS ?") + " ORDER BY s.created_at DESC",
                            () if everyone else (user_id,)).fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


def count_for_user(user_id: int | None) -> int:
    with db.connect() as conn:
        return int(conn.execute("SELECT COUNT(*) AS n FROM slideshows WHERE user_id IS ?", (user_id,)).fetchone()["n"])


def count_active_for_user(user_id: int | None) -> int:
    with db.connect() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM slideshows WHERE user_id IS ? AND status IN ('queued', 'rendering')", (user_id,)
            ).fetchone()["n"]
        )


# ---- photos ---------------------------------------------------------------

def photos(project_id: str) -> list[dict[str, Any]]:
    with db.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM slideshow_photos WHERE slideshow_id = ? ORDER BY position", (project_id,)
            )
        ]


def add_photo(project_id: str, photo_id: str, name: str, width: int, height: int, taken_at: str | None) -> None:
    with db.connect() as conn:
        pos = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM slideshow_photos WHERE slideshow_id = ?", (project_id,)
        ).fetchone()["p"]
        conn.execute(
            "INSERT INTO slideshow_photos (id, slideshow_id, position, original_name, width, height, taken_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (photo_id, project_id, pos, name, width, height, taken_at),
        )


def photo_count(project_id: str) -> int:
    with db.connect() as conn:
        return int(
            conn.execute("SELECT COUNT(*) AS n FROM slideshow_photos WHERE slideshow_id = ?", (project_id,)).fetchone()["n"]
        )


def reorder(project_id: str, ordered_ids: list[str]) -> list[str]:
    """New order = `ordered_ids`; photos not listed are deleted. Returns the ids that were deleted."""
    existing = {p["id"] for p in photos(project_id)}
    keep = [i for i in dict.fromkeys(ordered_ids) if i in existing]  # drops unknown ids and duplicates
    gone = sorted(existing - set(keep))
    with db.connect() as conn:
        for pos, pid in enumerate(keep):
            conn.execute("UPDATE slideshow_photos SET position = ? WHERE id = ? AND slideshow_id = ?", (pos, pid, project_id))
        for pid in gone:
            conn.execute("DELETE FROM slideshow_photos WHERE id = ? AND slideshow_id = ?", (pid, project_id))
    return gone


# ---- rendering queue ------------------------------------------------------

def claim_next() -> dict[str, Any] | None:
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT id FROM slideshows WHERE status = 'queued' ORDER BY updated_at LIMIT 1").fetchone()
        if row is None:
            return None
        conn.execute("UPDATE slideshows SET status = 'rendering', updated_at = ? WHERE id = ?", (_now(), row["id"]))
    return get(row["id"])


def requeue_interrupted() -> int:
    with db.connect() as conn:
        return conn.execute("UPDATE slideshows SET status = 'queued' WHERE status = 'rendering'").rowcount


# ---- cleanup --------------------------------------------------------------

def delete(project_id: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM slideshow_photos WHERE slideshow_id = ?", (project_id,))
        conn.execute("DELETE FROM slideshows WHERE id = ?", (project_id,))
    shutil.rmtree(project_dir(project_id), ignore_errors=True)


def purge_old(retention_days: int) -> int:
    """Remove projects not touched for `retention_days` (never one that is being rendered)."""
    if retention_days <= 0:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat(timespec="seconds")
    with db.connect() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM slideshows WHERE updated_at < ? AND status NOT IN ('queued', 'rendering')", (cutoff,))]
    for pid in ids:
        delete(pid)
    return len(ids)
