"""Sign-up (invite only, or open when OPEN_SIGNUP=true), sign-in, sign-out and "who am I" (with the signed media token)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import auth
from ..config import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupBody(BaseModel):
    invite_code: str = Field(default="", max_length=64)  # not needed when OPEN_SIGNUP=true
    email: str = Field(max_length=254)
    password: str = Field(max_length=auth.MAX_PASSWORD)


class LoginBody(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=auth.MAX_PASSWORD)


def _require_accounts() -> None:
    if not get_settings().auth_enabled:
        raise HTTPException(status_code=404, detail="Accounts are not enabled on this server.")


def _session_reply(row: dict[str, Any]) -> dict[str, Any]:
    user = auth._to_user(row)
    return {
        "token": auth.create_session(user.id),
        "media_token": auth.make_media_token(user.id),
        "user": auth.user_payload(user),
    }


@router.post("/signup", status_code=201)
def signup(body: SignupBody, request: Request) -> dict[str, Any]:
    """Create an account: with an invite code (made by `python -m app.admin invite`), or freely when OPEN_SIGNUP=true."""
    _require_accounts()
    return _session_reply(auth.signup(body.invite_code, body.email, body.password, auth.client_ip(request)))


@router.post("/login")
def login(body: LoginBody, request: Request) -> dict[str, Any]:
    _require_accounts()
    return _session_reply(auth.login(body.email, body.password, auth.client_ip(request)))


@router.post("/logout", status_code=204)
def logout(request: Request, user: auth.User = Depends(auth.current_user)) -> None:
    token = auth.bearer_token(request)
    if token and get_settings().auth_enabled:
        auth.end_session(token)


@router.get("/me")
def me(user: auth.User = Depends(auth.current_user)) -> dict[str, Any]:
    """The signed-in user, their remaining quota, and a fresh media token (valid 6 hours)."""
    enabled = get_settings().auth_enabled
    return {
        "auth_required": enabled,
        "user": auth.user_payload(user),
        "media_token": auth.make_media_token(user.id) if enabled else None,
    }
