"""The admin page's data: who has an account and what they have used. Read-only.

Only admins (make one with `python -m app.admin make-admin EMAIL`) can read it; for everyone else the route looks
like it doesn't exist. Being an admin is a flag in the database, never decided by the email address alone: sign-up
doesn't verify addresses, so anyone could register one.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

from .. import auth, db
from ..auth import User, current_user
from ..config import get_settings

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin(user: User = Depends(current_user)) -> User:
    if not get_settings().auth_enabled or not user.is_admin:
        raise HTTPException(status_code=404, detail="Not found")
    return user


@router.get("/users")
def list_accounts(response: Response, _: User = Depends(require_admin)) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    now = datetime.now(timezone.utc)

    def ago(delta: timedelta) -> str:
        return (now - delta).isoformat(timespec="seconds")

    rows = db.user_overview(ago(auth.QUOTA_WINDOW))
    users = [
        {
            "id": r["id"],
            "email": r["email"],
            "is_admin": bool(r["is_admin"]),
            "disabled": bool(r["disabled"]),
            "plan": r["plan"],
            "created_at": r["created_at"],
            "videos_stored": r["videos_stored"],
            "videos_24h": r["videos_recent"],
            "chats_24h": r["chats_recent"],
        }
        for r in rows
    ]
    return {
        "totals": {
            "accounts": len(users),
            "new_24h": sum(u["created_at"] > ago(timedelta(hours=24)) for u in users),
            "new_7d": sum(u["created_at"] > ago(timedelta(days=7)) for u in users),
        },
        "users": users,
    }
