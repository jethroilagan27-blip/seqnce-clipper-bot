"""SQLite persistence for processing jobs.

One short-lived connection per call keeps this thread-safe for both the API
threadpool and the background worker thread. WAL mode lets the worker write
while the API reads.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id                TEXT PRIMARY KEY,
    status            TEXT NOT NULL,            -- queued | running | completed | failed
    stage             TEXT NOT NULL,            -- see app/stages.py
    progress          INTEGER NOT NULL DEFAULT 0,
    original_filename TEXT NOT NULL,
    upload_path       TEXT NOT NULL,
    audio_path        TEXT,
    transcript_path   TEXT,
    output_path       TEXT,
    settings_json     TEXT NOT NULL,
    metadata_json     TEXT,                     -- ffprobe result of the original
    output_metadata_json TEXT,                  -- ffprobe result of the render
    visual_json       TEXT,                     -- AI visual analysis of sampled frames
    plan_json         TEXT,                     -- validated AI editing plan
    error             TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
"""

_JSON_COLUMNS = {
    "settings_json",
    "metadata_json",
    "output_metadata_json",
    "visual_json",
    "plan_json",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(get_settings().db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    get_settings().ensure_dirs()
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        # Tiny migration for databases created before a column existed.
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
        if "visual_json" not in existing:
            conn.execute("ALTER TABLE jobs ADD COLUMN visual_json TEXT")


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for col in _JSON_COLUMNS:
        if data.get(col):
            data[col] = json.loads(data[col])
    return data


def create_job(
    job_id: str,
    original_filename: str,
    upload_path: str,
    settings: dict[str, Any],
    metadata: dict[str, Any] | None,
) -> None:
    now = _now()
    with connect() as conn:
        conn.execute(
            """INSERT INTO jobs (id, status, stage, progress, original_filename,
                                 upload_path, settings_json, metadata_json,
                                 created_at, updated_at)
               VALUES (?, 'queued', 'uploaded', 5, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                original_filename,
                upload_path,
                json.dumps(settings),
                json.dumps(metadata) if metadata else None,
                now,
                now,
            ),
        )


def get_job(job_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row)


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    for col in _JSON_COLUMNS:
        if col in fields and fields[col] is not None:
            fields[col] = json.dumps(fields[col])
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(
            f"UPDATE jobs SET {assignments} WHERE id = ?",
            (*fields.values(), job_id),
        )


def claim_next_job() -> dict[str, Any] | None:
    """Atomically take the oldest queued job and mark it running."""
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ?",
            (_now(), row["id"]),
        )
    return get_job(row["id"])


def requeue_interrupted_jobs() -> int:
    """Jobs left 'running' by a crash/restart go back to the queue."""
    with connect() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status = 'queued', updated_at = ? WHERE status = 'running'",
            (_now(),),
        )
        return cur.rowcount
