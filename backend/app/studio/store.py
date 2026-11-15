"""Database and file layout for Studio projects (their own tables, same SQLite file)."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .. import db
from ..config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS studio_projects (
    id                TEXT PRIMARY KEY,
    user_id           INTEGER,
    title             TEXT NOT NULL DEFAULT 'Untitled video',
    status            TEXT NOT NULL DEFAULT 'draft',   -- draft | queued | rendering | completed | failed
    progress          INTEGER NOT NULL DEFAULT 0,
    stage_text        TEXT,                            -- "Scene 3 of 12: Title reveal"
    render_kind       TEXT,                            -- what was last asked for: final | preview
    render_scene      TEXT,                            -- preview of one scene (its id); NULL = the whole video
    error             TEXT,
    doc_json          TEXT NOT NULL,
    output_path       TEXT,                            -- the finished video
    output_meta_json  TEXT,
    preview_path      TEXT,                            -- the latest quick preview
    preview_scene     TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS studio_assets (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL,
    kind          TEXT NOT NULL,                       -- video | audio | image
    position      INTEGER NOT NULL,
    original_name TEXT,
    file          TEXT NOT NULL,                       -- server-made file name inside the project's assets/ folder
    width         INTEGER,
    height        INTEGER,
    duration      REAL,
    has_audio     INTEGER NOT NULL DEFAULT 0,
    size_bytes    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_studio_assets ON studio_assets(project_id, position);
"""

_JSON = ("doc_json", "output_meta_json")
ACTIVE = ("queued", "rendering")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_tables() -> None:
    with db.connect() as conn:
        conn.executescript(SCHEMA)


def project_dir(project_id: str) -> Path:
    return get_settings().storage_dir / "studio" / project_id


def _row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for col in _JSON:
        if data.get(col):
            data[col] = json.loads(data[col])
    return data


def create(project_id: str, user_id: int | None, title: str, doc: dict[str, Any]) -> None:
    now = _now()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO studio_projects (id, user_id, title, doc_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, user_id, title, json.dumps(doc), now, now),
        )
    for sub in ("assets", "thumbs", "previews"):
        (project_dir(project_id) / sub).mkdir(parents=True, exist_ok=True)


def get(project_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        return _row(conn.execute("SELECT * FROM studio_projects WHERE id = ?", (project_id,)).fetchone())


def update(project_id: str, **fields: Any) -> None:
    for col in _JSON:
        if fields.get(col) is not None:
            fields[col] = json.dumps(fields[col])
    fields["updated_at"] = _now()
    with db.connect() as conn:
        conn.execute(
            f"UPDATE studio_projects SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
            (*fields.values(), project_id),
        )


def list_for_user(user_id: int | None, *, everyone: bool = False) -> list[dict[str, Any]]:
    with db.connect() as conn:
        sql = "SELECT p.*, (SELECT COUNT(*) FROM studio_assets a WHERE a.project_id = p.id) AS asset_count FROM studio_projects p"
        rows = conn.execute(
            sql + ("" if everyone else " WHERE p.user_id IS ?") + " ORDER BY p.updated_at DESC", () if everyone else (user_id,)
        ).fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


def count_for_user(user_id: int | None) -> int:
    with db.connect() as conn:
        return int(conn.execute("SELECT COUNT(*) AS n FROM studio_projects WHERE user_id IS ?", (user_id,)).fetchone()["n"])


def count_active_for_user(user_id: int | None) -> int:
    with db.connect() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM studio_projects WHERE user_id IS ? AND status IN ('queued', 'rendering')", (user_id,)
            ).fetchone()["n"]
        )


# ---- assets -----------------------------------------------------------------

def assets(project_id: str) -> list[dict[str, Any]]:
    with db.connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM studio_assets WHERE project_id = ? ORDER BY position", (project_id,))]


def get_asset(project_id: str, asset_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM studio_assets WHERE project_id = ? AND id = ?", (project_id, asset_id)).fetchone()
    return dict(row) if row else None


def add_asset(project_id: str, asset_id: str, kind: str, name: str, file: str, *, width: int | None, height: int | None,
              duration: float | None, has_audio: bool, size_bytes: int) -> None:
    with db.connect() as conn:
        pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM studio_assets WHERE project_id = ?", (project_id,)).fetchone()["p"]
        conn.execute(
            "INSERT INTO studio_assets (id, project_id, kind, position, original_name, file, width, height, duration, has_audio, size_bytes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (asset_id, project_id, kind, pos, name, file, width, height, duration, int(has_audio), size_bytes),
        )


def asset_totals(project_id: str) -> tuple[int, int]:
    """(number of files, their total size in bytes)."""
    with db.connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS b FROM studio_assets WHERE project_id = ?", (project_id,)).fetchone()
    return int(row["n"]), int(row["b"])


def delete_asset(project_id: str, asset_id: str) -> None:
    asset = get_asset(project_id, asset_id)
    if asset is None:
        return
    with db.connect() as conn:
        conn.execute("DELETE FROM studio_assets WHERE project_id = ? AND id = ?", (project_id, asset_id))
    base = project_dir(project_id)
    (base / "assets" / asset["file"]).unlink(missing_ok=True)
    (base / "thumbs" / f"{asset_id}.jpg").unlink(missing_ok=True)


# ---- rendering queue ----------------------------------------------------------

def claim_next() -> dict[str, Any] | None:
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT id FROM studio_projects WHERE status = 'queued' ORDER BY updated_at LIMIT 1").fetchone()
        if row is None:
            return None
        conn.execute("UPDATE studio_projects SET status = 'rendering', updated_at = ? WHERE id = ?", (_now(), row["id"]))
    return get(row["id"])


def requeue_interrupted() -> int:
    with db.connect() as conn:
        return conn.execute("UPDATE studio_projects SET status = 'queued' WHERE status = 'rendering'").rowcount


# ---- cleanup ------------------------------------------------------------------

def delete(project_id: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM studio_assets WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM studio_projects WHERE id = ?", (project_id,))
    shutil.rmtree(project_dir(project_id), ignore_errors=True)


def purge_old(retention_days: int) -> int:
    """Remove projects not touched for `retention_days` (never one that is being rendered)."""
    if retention_days <= 0:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat(timespec="seconds")
    with db.connect() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM studio_projects WHERE updated_at < ? AND status NOT IN ('queued', 'rendering')", (cutoff,))]
    for pid in ids:
        delete(pid)
    return len(ids)
