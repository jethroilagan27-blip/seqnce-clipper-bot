"""The admin page: who has an account, what their plan allows, and how much they use it.

An admin can change another account's plan, daily limits and beta access here. There is no pricing: plans are just
sets of limits (app/features.py).

Only admins (make one with `python -m app.admin make-admin EMAIL`) can use these routes; for everyone else they look
like they don't exist. Being an admin is a flag in the database, never decided by the email address alone: sign-up
doesn't verify addresses, so anyone could register one. Admin rights can't be given or taken from the website.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from .. import auth, db, features
from ..auth import User, current_user
from ..config import get_settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])

BETA = ("studio", "studio_ai_chat")  # the features that can be switched per account on the admin page
COUNTED = {"video": "videos", "edit": "changes", "ai": "ai", "ai_own": "ai_own"}  # activity kind -> name in the graphs


def require_admin(user: User = Depends(current_user)) -> User:
    if not get_settings().auth_enabled or not user.is_admin:
        raise HTTPException(status_code=404, detail="Not found")
    return user


def _account(row: dict[str, Any]) -> dict[str, Any]:
    """One account as the admin page shows it. Never a password hash or a key."""
    user = auth._to_user(row)
    allowed = auth.features_of(user)
    return {
        "id": row["id"],
        "email": row["email"],
        "is_admin": user.is_admin,
        "disabled": bool(row["disabled"]),
        "plan": row["plan"],
        "created_at": row["created_at"],
        "videos_stored": row["videos_stored"],
        "videos_24h": row["videos_recent"],
        "chats_24h": row["chats_recent"],
        "video_limit": row["video_limit"],  # set for this account only; null = what the plan says
        "chat_limit": row["chat_limit"],
        "limits": {"videos": auth.limit_for(user, "video"), "chats": auth.limit_for(user, "chat")},  # in force now
        **{key: bool(allowed[key]) for key in BETA},
    }


def _overview() -> list[dict[str, Any]]:
    since = (datetime.now(timezone.utc) - auth.QUOTA_WINDOW).isoformat(timespec="seconds")
    return db.user_overview(since)


def _plans() -> dict[str, dict[str, Any]]:
    return {
        name: {
            "videos": auth.plan_limit(name, "video"),
            "chats": auth.plan_limit(name, "chat"),
            **{key: features.PLANS[name][key] for key in BETA},
        }
        for name in features.PLAN_NAMES
    }


@router.get("/users")
def list_accounts(response: Response, _: User = Depends(require_admin)) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    now = datetime.now(timezone.utc)

    def ago(delta: timedelta) -> str:
        return (now - delta).isoformat(timespec="seconds")

    users = [_account(r) for r in _overview()]
    return {
        "totals": {
            "accounts": len(users),
            "new_24h": sum(u["created_at"] > ago(timedelta(hours=24)) for u in users),
            "new_7d": sum(u["created_at"] > ago(timedelta(days=7)) for u in users),
        },
        "plans": _plans(),
        "users": users,
    }


class AccountChange(BaseModel):
    """Only what is sent changes. A null limit or switch means "whatever the plan says"."""

    model_config = ConfigDict(extra="forbid")

    plan: Literal["standard", "pro", "max"] | None = None
    video_limit: int | None = Field(default=None, ge=0, le=10_000, strict=True)
    chat_limit: int | None = Field(default=None, ge=0, le=10_000, strict=True)
    studio: bool | None = None
    studio_ai_chat: bool | None = None


@router.patch("/users/{user_id}")
def change_account(
    change: AccountChange, response: Response, user_id: int = Path(ge=1), admin: User = Depends(require_admin)
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    row = db.get_user(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="That account doesn't exist.")
    if row["is_admin"]:
        raise HTTPException(status_code=400, detail="Admin accounts have everything and no limits: there is nothing to change.")

    sent = change.model_fields_set
    fields: dict[str, Any] = {}
    plan = change.plan or row["plan"]
    if change.plan:
        fields["plan"] = change.plan
    for key in ("video_limit", "chat_limit"):
        if key in sent:
            fields[key] = getattr(change, key)
    overrides = dict(auth._to_user(row).overrides)
    for key in BETA:
        if key in sent:
            value = getattr(change, key)
            if value is None or value == features.PLANS[plan][key]:
                overrides.pop(key, None)  # same as the plan: follow the plan, also after it changes
            else:
                overrides[key] = value
    if any(key in sent for key in BETA):
        fields["features_json"] = json.dumps(overrides) if overrides else None
    db.update_user(user_id, **fields)
    log.info("admin %s changed account %s: %s", admin.id, user_id, ", ".join(sorted(sent)) or "nothing")
    return next(_account(r) for r in _overview() if r["id"] == user_id)


@router.get("/stats")
def usage_stats(
    response: Response,
    days: int = Query(30, ge=1, le=365),
    tz: int = Query(0, ge=-840, le=840, description="The viewer's minutes ahead of UTC, so days start at their midnight"),
    user_id: int | None = Query(None, ge=1, description="Graph one account only"),
    _: User = Depends(require_admin),
) -> dict[str, Any]:
    """Per day: new videos, changes to videos, and requests sent to the AI (on the server's key, or the person's own)."""
    response.headers["Cache-Control"] = "no-store"
    offset = timedelta(minutes=tz)
    today = (datetime.now(timezone.utc) + offset).date()
    first = today - timedelta(days=days - 1)
    since = (datetime.combine(first, time(), timezone.utc) - offset).isoformat(timespec="seconds")

    def zero() -> dict[str, int]:
        return dict.fromkeys(COUNTED.values(), 0)

    series: dict[date, dict[str, int]] = {first + timedelta(days=i): zero() for i in range(days)}
    per_user: dict[int, dict[str, int]] = {}
    for who, kind, at in db.activity_since(since):
        name = COUNTED.get(kind)
        if name is None:
            continue
        if who is not None:
            per_user.setdefault(who, zero())[name] += 1
        if user_id is None or who == user_id:
            day = (datetime.fromisoformat(at) + offset).date()
            if day in series:
                series[day][name] += 1
    return {
        "days": [{"date": d.isoformat(), **counts} for d, counts in series.items()],
        "totals": {name: sum(c[name] for c in series.values()) for name in COUNTED.values()},
        "per_user": [{"user_id": who, **counts} for who, counts in per_user.items()],
    }
