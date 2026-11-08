"""SQLite persistence for processing jobs.

One short-lived connection per call keeps this thread-safe for both the API
threadpool and the background worker thread. WAL mode lets the worker write
while the API reads.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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

-- Accounts (only used when AUTH_ENABLED=true). Passwords are scrypt hashes; session and invite
-- tokens are stored only as SHA-256 hashes, so a leaked database cannot be replayed.
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    disabled      INTEGER NOT NULL DEFAULT 0,
    video_limit   INTEGER,                      -- NULL = the server default
    chat_limit    INTEGER,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invites (
    code_hash  TEXT PRIMARY KEY,
    email      TEXT,                            -- when set, only this address can use the code
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at    TEXT,
    used_by    INTEGER
);
CREATE TABLE IF NOT EXISTS usage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    kind       TEXT NOT NULL,                   -- video | chat
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage ON usage(user_id, kind, created_at);

-- Every render of a job is a numbered version with its own plan and output file.
CREATE TABLE IF NOT EXISTS plan_versions (
    job_id               TEXT NOT NULL,
    version              INTEGER NOT NULL,
    source               TEXT NOT NULL,            -- initial | chat | manual | restore
    message              TEXT,                     -- what the user asked for (chat) / what they changed
    reply                TEXT,                     -- the AI editor's answer (chat only)
    plan_json            TEXT NOT NULL,
    changes_json         TEXT,                     -- diff against the previous version
    output_path          TEXT,
    output_metadata_json TEXT,
    created_at           TEXT NOT NULL,
    PRIMARY KEY (job_id, version)
);
"""

_JSON_COLUMNS = {
    "settings_json",
    "metadata_json",
    "output_metadata_json",
    "visual_json",
    "plan_json",
    "revision_json",
}
_VERSION_JSON = ("plan_json", "changes_json", "output_metadata_json")


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
        if "current_version" not in existing:
            conn.execute("ALTER TABLE jobs ADD COLUMN current_version INTEGER NOT NULL DEFAULT 1")
        if "user_id" not in existing:
            conn.execute("ALTER TABLE jobs ADD COLUMN user_id INTEGER")  # owner; NULL = created without accounts
        if "revision_json" not in existing:
            conn.execute("ALTER TABLE jobs ADD COLUMN revision_json TEXT")  # pending revision request


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
    user_id: int | None = None,
) -> None:
    now = _now()
    with connect() as conn:
        conn.execute(
            """INSERT INTO jobs (id, status, stage, progress, original_filename,
                                 upload_path, settings_json, metadata_json,
                                 created_at, updated_at, user_id)
               VALUES (?, 'queued', 'uploaded', 5, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                original_filename,
                upload_path,
                json.dumps(settings),
                json.dumps(metadata) if metadata else None,
                now,
                now,
                user_id,
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


def start_revision(
    job_id: str,
    revision: dict[str, Any],
    stage: str,
    progress: int,
    plan: dict[str, Any] | None = None,
) -> bool:
    """Queue a revision of a finished job (atomically, together with its new plan for hand edits).

    False if the job isn't finished or is already revising."""
    with connect() as conn:
        cur = conn.execute(
            """UPDATE jobs SET status = 'queued', stage = ?, progress = ?, revision_json = ?,
                               plan_json = COALESCE(?, plan_json), error = NULL, updated_at = ?
               WHERE id = ? AND status = 'completed' AND output_path IS NOT NULL
                     AND revision_json IS NULL""",
            (stage, progress, json.dumps(revision), json.dumps(plan) if plan else None, _now(), job_id),
        )
        return cur.rowcount == 1


def _version_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for col in _VERSION_JSON:
        if data.get(col):
            data[col] = json.loads(data[col])
    return data


def add_version(
    job_id: str,
    version: int,
    *,
    plan: dict[str, Any],
    source: str,
    message: str | None = None,
    reply: str | None = None,
    changes: dict[str, Any] | None = None,
    output_path: str | None = None,
    output_metadata: dict[str, Any] | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO plan_versions
               (job_id, version, source, message, reply, plan_json, changes_json,
                output_path, output_metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id, version, source, message, reply, json.dumps(plan),
                json.dumps(changes) if changes is not None else None,
                output_path,
                json.dumps(output_metadata) if output_metadata else None,
                _now(),
            ),
        )


def list_versions(job_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM plan_versions WHERE job_id = ? ORDER BY version", (job_id,)
        ).fetchall()
    return [_version_row(r) for r in rows]  # type: ignore[misc]


def get_version(job_id: str, version: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM plan_versions WHERE job_id = ? AND version = ?", (job_id, version)
        ).fetchone()
    return _version_row(row)


def latest_version_number(job_id: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT MAX(version) AS v FROM plan_versions WHERE job_id = ?", (job_id,)
        ).fetchone()
    return int(row["v"] or 0)


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


# ---------------------------------------------------------------------------
# accounts, sessions, invites, usage
# ---------------------------------------------------------------------------

def _iso_in(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat(timespec="seconds")


def create_user(email: str, password_hash: str, *, is_admin: bool = False) -> int | None:
    """Returns the new user id, or None when that email already has an account."""
    try:
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
                (email, password_hash, int(is_admin), _now()),
            )
            return int(cur.lastrowid)
    except sqlite3.IntegrityError:
        return None


def get_user(user_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def list_users() -> list[dict[str, Any]]:
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY id")]


_USER_FIELDS = {"password_hash", "is_admin", "disabled", "video_limit", "chat_limit"}


def update_user(user_id: int, **fields: Any) -> None:
    bad = set(fields) - _USER_FIELDS
    if bad:
        raise ValueError(f"unknown user fields: {sorted(bad)}")
    if not fields:
        return
    with connect() as conn:
        conn.execute(
            f"UPDATE users SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
            (*fields.values(), user_id),
        )


def add_session(token_hash: str, user_id: int, lifetime: timedelta) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash, user_id, _now(), _iso_in(lifetime)),
        )


def get_session_user(token_hash: str) -> dict[str, Any] | None:
    """The (enabled) user owning a live session, or None."""
    with connect() as conn:
        row = conn.execute(
            """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.expires_at > ? AND u.disabled = 0""",
            (token_hash, _now()),
        ).fetchone()
    return dict(row) if row else None


def delete_session(token_hash: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def delete_user_sessions(user_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def add_invite(code_hash: str, email: str | None, lifetime: timedelta) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO invites (code_hash, email, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (code_hash, email, _now(), _iso_in(lifetime)),
        )


def create_user_with_invite(code_hash: str, email: str, password_hash: str) -> tuple[str, int | None]:
    """Spend an invite and create the account in ONE transaction.

    Returns ("ok", user_id), ("invalid", None) for an unknown/used/expired/other-email invite, or
    ("exists", None). Two people racing for one code can never both get in."""
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        invite = conn.execute(
            "SELECT email FROM invites WHERE code_hash = ? AND used_at IS NULL AND expires_at > ?",
            (code_hash, _now()),
        ).fetchone()
        if invite is None or (invite["email"] and invite["email"] != email):
            return "invalid", None
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            return "exists", None
        user_id = int(
            conn.execute(
                "INSERT INTO users (email, password_hash, is_admin, created_at) VALUES (?, ?, 0, ?)",
                (email, password_hash, _now()),
            ).lastrowid
        )
        conn.execute("UPDATE invites SET used_at = ?, used_by = ? WHERE code_hash = ?", (_now(), user_id, code_hash))
        return "ok", user_id


def create_user_open(email: str, password_hash: str, daily_cap: int) -> tuple[str, int | None]:
    """Open sign-up: create the account unless the server already took `daily_cap` new accounts in 24 h.

    Returns ("ok", user_id), ("full", None) or ("exists", None). Check and insert are one transaction."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            return "exists", None
        if conn.execute("SELECT COUNT(*) FROM users WHERE created_at > ?", (since,)).fetchone()[0] >= daily_cap:
            return "full", None
        user_id = int(
            conn.execute(
                "INSERT INTO users (email, password_hash, is_admin, created_at) VALUES (?, ?, 0, ?)",
                (email, password_hash, _now()),
            ).lastrowid
        )
        return "ok", user_id


def try_record_usage(user_id: int, kind: str, limit: int | None, window: timedelta) -> bool:
    """Record one use of `kind` unless the user already used `limit` of them in the last `window`.

    Check and insert happen in one transaction, so parallel requests cannot slip past the limit."""
    since = (datetime.now(timezone.utc) - window).isoformat(timespec="seconds")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if limit is not None:
            used = conn.execute(
                "SELECT COUNT(*) AS n FROM usage WHERE user_id = ? AND kind = ? AND created_at > ?",
                (user_id, kind, since),
            ).fetchone()["n"]
            if used >= limit:
                return False
        conn.execute("INSERT INTO usage (user_id, kind, created_at) VALUES (?, ?, ?)", (user_id, kind, _now()))
        return True


def usage_in_window(user_id: int, kind: str, window: timedelta) -> tuple[int, str | None]:
    """(uses in the window, time the oldest of them leaves the window)."""
    since = (datetime.now(timezone.utc) - window).isoformat(timespec="seconds")
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, MIN(created_at) AS oldest FROM usage WHERE user_id = ? AND kind = ? AND created_at > ?",
            (user_id, kind, since),
        ).fetchone()
    resets = None
    if row["oldest"]:
        resets = (datetime.fromisoformat(row["oldest"]) + window).isoformat(timespec="seconds")
    return int(row["n"]), resets


def count_active_jobs(user_id: int) -> int:
    with connect() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE user_id = ? AND status IN ('queued', 'running')", (user_id,)
            ).fetchone()["n"]
        )


def purge_auth() -> None:
    """Forget expired sessions and invites and old usage records (called at startup)."""
    now = _now()
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.execute("DELETE FROM invites WHERE expires_at <= ? AND used_at IS NULL", (now,))
        conn.execute("DELETE FROM usage WHERE created_at <= ?", (old,))
