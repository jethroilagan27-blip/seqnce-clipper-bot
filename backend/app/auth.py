"""Accounts for a shared deployment: passwords, sessions, signed media tokens, quotas.

Everything here is inert unless `AUTH_ENABLED=true`: with it off (the default, i.e. local use) every
request is served as a built-in admin without limits and no login exists.

Security choices, kept deliberately boring:
- passwords: scrypt with a random salt (standard library, no extra dependency), constant-time compare;
- sessions / invite codes: random tokens stored only as SHA-256 hashes;
- media (<video>, <img>, downloads) cannot send an Authorization header, so they use short-lived
  HMAC-signed tokens in the URL that only work on the four media endpoints;
- login attempts are throttled per email and per address;
- users only ever see their own jobs (someone else's job id looks like "not found").
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Query, Request

from . import db
from .config import get_settings

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1  # ~16 MiB and ~50-100 ms per hash
MIN_PASSWORD, MAX_PASSWORD = 10, 200
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
QUOTA_WINDOW = timedelta(hours=24)
MEDIA_TOKEN_TTL_S = 6 * 3600
INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I to avoid typos
KINDS = {"video": ("video", "videos"), "chat": ("chat message", "chat messages")}


@dataclass(frozen=True)
class User:
    id: int
    email: str
    is_admin: bool
    video_limit: int | None = None  # per-user override of DAILY_VIDEO_LIMIT
    chat_limit: int | None = None


LOCAL_USER = User(id=0, email="local", is_admin=True)  # who everyone is when accounts are switched off


def _to_user(row: dict[str, Any]) -> User:
    return User(
        id=int(row["id"]),
        email=row["email"],
        is_admin=bool(row["is_admin"]),
        video_limit=row.get("video_limit"),
        chat_limit=row.get("chat_limit"),
    )


# ---------------------------------------------------------------------------
# passwords and emails
# ---------------------------------------------------------------------------

def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


_dummy_hash: str | None = None


def _burn_time() -> None:
    """Spend the same time as a real check, so an unknown email can't be told apart by how fast we answer."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("not-a-real-password")
    verify_password("wrong", _dummy_hash)


def normalize_email(raw: str | None) -> str | None:
    email = (raw or "").strip().lower()
    return email if len(email) <= 254 and EMAIL_RE.match(email) else None


def password_problem(password: str, email: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"Use a password of at least {MIN_PASSWORD} characters."
    if len(password) > MAX_PASSWORD:
        return "That password is too long."
    if password.lower() == email.lower() or password.lower().strip() in {"password123", "1234567890"}:
        return "Pick a password that is harder to guess."
    return None


# ---------------------------------------------------------------------------
# sessions and tokens
# ---------------------------------------------------------------------------

def _sha(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.add_session(_sha(token), user_id, timedelta(days=get_settings().session_days))
    return token


def end_session(token: str) -> None:
    db.delete_session(_sha(token))


def _secret() -> bytes:
    cfg = get_settings()
    if cfg.auth_secret:
        return cfg.auth_secret.encode("utf-8")
    path = cfg.storage_dir / ".auth_secret"
    if path.is_file():
        return path.read_bytes()
    cfg.ensure_dirs()
    key = secrets.token_bytes(32)
    path.write_bytes(key)
    try:
        path.chmod(0o600)
    except OSError:
        pass  # Windows: best effort
    return key


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def make_media_token(user_id: int) -> str:
    payload = f"{user_id}.{int(time.time()) + MEDIA_TOKEN_TTL_S}"
    return f"{payload}.{_b64url(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())}"


def verify_media_token(token: str) -> int | None:
    try:
        user_id, expires, signature = token.split(".")
        payload = f"{user_id}.{expires}"
        expected = _b64url(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected) or int(expires) < time.time():
            return None
        return int(user_id)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# brute-force throttle (in memory: resets when the server restarts)
# ---------------------------------------------------------------------------

LOGIN_WINDOW_S = 15 * 60
LOGIN_MAX_PER_EMAIL = 5
LOGIN_MAX_PER_IP = 30
_fails: dict[str, deque[float]] = defaultdict(deque)
_fails_lock = threading.Lock()


def _recent(key: str, now: float) -> deque[float]:
    q = _fails[key]
    while q and now - q[0] > LOGIN_WINDOW_S:
        q.popleft()
    return q


def login_blocked(email: str, ip: str) -> bool:
    now = time.time()
    with _fails_lock:
        return len(_recent(f"e:{email}", now)) >= LOGIN_MAX_PER_EMAIL or len(_recent(f"i:{ip}", now)) >= LOGIN_MAX_PER_IP


def note_login_failure(email: str, ip: str) -> None:
    now = time.time()
    with _fails_lock:
        _recent(f"e:{email}", now).append(now)
        _recent(f"i:{ip}", now).append(now)
        if len(_fails) > 5000:  # never grow without bound
            for k in [k for k, q in _fails.items() if not q or now - q[-1] > LOGIN_WINDOW_S]:
                del _fails[k]


def clear_login_failures(email: str) -> None:
    with _fails_lock:
        _fails.pop(f"e:{email}", None)


def reset_throttle() -> None:  # for tests
    with _fails_lock:
        _fails.clear()


# ---------------------------------------------------------------------------
# sign-up, login
# ---------------------------------------------------------------------------

def normalize_code(raw: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (raw or "").upper())


def new_invite(email: str | None = None, days: int = 7) -> str:
    """Create an invite code. The code is shown once; only its hash is stored."""
    groups = ["".join(secrets.choice(INVITE_ALPHABET) for _ in range(4)) for _ in range(3)]
    code = "SQ-" + "-".join(groups)
    db.add_invite(_sha(normalize_code(code)), normalize_email(email) if email else None, timedelta(days=days))
    return code


def signup(invite_code: str, email_raw: str, password: str) -> dict[str, Any]:
    email = normalize_email(email_raw)
    if email is None:
        raise HTTPException(status_code=422, detail="That doesn't look like an email address.")
    problem = password_problem(password, email)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    status, user_id = db.create_user_with_invite(_sha(normalize_code(invite_code)), email, hash_password(password))
    if status == "invalid":
        raise HTTPException(status_code=400, detail="That invite code isn't valid for this email, or it has expired.")
    if status == "exists" or user_id is None:
        raise HTTPException(status_code=409, detail="An account with that email already exists. Try signing in.")
    return db.get_user(user_id) or {}


def login(email_raw: str, password: str, ip: str) -> dict[str, Any]:
    email = normalize_email(email_raw) or (email_raw or "").strip().lower()[:254]
    if login_blocked(email, ip):
        raise HTTPException(
            status_code=429, detail="Too many sign-in attempts. Wait a few minutes and try again.",
            headers={"Retry-After": str(LOGIN_WINDOW_S)},
        )
    row = db.get_user_by_email(email)
    ok = bool(row) and verify_password(password, row["password_hash"]) and not row["disabled"]  # type: ignore[index]
    if not row:
        _burn_time()
    if not ok:
        note_login_failure(email, ip)
        raise HTTPException(status_code=401, detail="Wrong email or password.")
    clear_login_failures(email)
    return row  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def _unauthorized(detail: str = "Please sign in.") -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def current_user(request: Request) -> User:
    """The signed-in user (header token only). With accounts off: the built-in local admin."""
    if not get_settings().auth_enabled:
        return LOCAL_USER
    token = bearer_token(request)
    if token is None:
        raise _unauthorized()
    row = db.get_session_user(_sha(token))
    if row is None:
        raise _unauthorized("Your session has expired. Please sign in again.")
    return _to_user(row)


def media_user(request: Request, st: str | None = Query(None, description="Signed media token (from /api/auth/me)")) -> User:
    """Like current_user, but a media token in `?st=` is accepted too (for <video>, <img>, download links)."""
    if not get_settings().auth_enabled:
        return LOCAL_USER
    if bearer_token(request) is not None:
        return current_user(request)
    user_id = verify_media_token(st) if st else None
    row = db.get_user(user_id) if user_id is not None else None
    if row is None or row["disabled"]:
        raise _unauthorized()
    return _to_user(row)


def can_access(user: User, job: dict[str, Any]) -> bool:
    """Owners and admins may use a job; jobs from before accounts existed belong to admins."""
    if not get_settings().auth_enabled:
        return True
    return user.is_admin or job.get("user_id") == user.id


# ---------------------------------------------------------------------------
# quotas
# ---------------------------------------------------------------------------

def limit_for(user: User, kind: str) -> int | None:
    cfg = get_settings()
    if not cfg.auth_enabled or user.is_admin:
        return None
    own = user.video_limit if kind == "video" else user.chat_limit
    return own if own is not None else (cfg.daily_video_limit if kind == "video" else cfg.daily_chat_limit)


def quota_status(user: User, kind: str) -> dict[str, Any]:
    used, resets = db.usage_in_window(user.id, kind, QUOTA_WINDOW) if get_settings().auth_enabled else (0, None)
    return {"used": used, "limit": limit_for(user, kind), "resets_at": resets}


def _wait_phrase(resets_at: str | None) -> str:
    if not resets_at:
        return "later"
    minutes = max(1, int((datetime.fromisoformat(resets_at) - datetime.now(timezone.utc)).total_seconds() // 60))
    return f"in about {minutes} minute{'s' if minutes != 1 else ''}" if minutes < 90 else f"in about {round(minutes / 60)} hours"


def _quota_error(kind: str, limit: int, resets_at: str | None) -> HTTPException:
    noun = KINDS[kind][0] if limit == 1 else KINDS[kind][1]
    return HTTPException(
        status_code=429,
        detail=f"You've used your {limit} {noun} for the last 24 hours. More free up {_wait_phrase(resets_at)}.",
    )


def ensure_quota(user: User, kind: str) -> None:
    """Fail early (before an upload is read) when the user has nothing left."""
    limit = limit_for(user, kind)
    if limit is None:
        return
    status = quota_status(user, kind)
    if status["used"] >= limit:
        raise _quota_error(kind, limit, status["resets_at"])


def spend_quota(user: User, kind: str) -> None:
    """Use one unit, atomically. Raises 429 if the limit was reached in the meantime."""
    if not get_settings().auth_enabled:
        return
    limit = limit_for(user, kind)
    if not db.try_record_usage(user.id, kind, limit, QUOTA_WINDOW):
        raise _quota_error(kind, limit or 0, quota_status(user, kind)["resets_at"])


def ensure_no_other_active_job(user: User) -> None:
    cfg = get_settings()
    if cfg.auth_enabled and not user.is_admin and db.count_active_jobs(user.id) >= cfg.max_active_jobs_per_user:
        raise HTTPException(
            status_code=409, detail="You already have a video being processed. Wait for it to finish, then upload the next one."
        )


def user_payload(user: User) -> dict[str, Any]:
    return {
        "email": user.email,
        "is_admin": user.is_admin,
        "quota": {"videos": quota_status(user, "video"), "chats": quota_status(user, "chat")},
    }
