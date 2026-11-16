"""Settings of the signed-in account: its own Gemini API key (see aikeys.py for how it is kept private).

The key is only ever accepted here; no route returns it, only whether there is one and its last 4 characters.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .. import aikeys
from ..ai import AIError
from ..ai.gemini import check_key
from ..auth import User, ai_key_state, current_user
from ..config import get_settings

router = APIRouter(prefix="/api/account", tags=["account"])


class KeyBody(BaseModel):
    key: str = Field(max_length=300, repr=False)  # repr=False: never printed by a validation error or a debugger


def _need_accounts() -> None:
    if not get_settings().auth_enabled:
        raise HTTPException(status_code=404, detail="Accounts are not enabled on this server.")


@router.get("/ai-key")
def get_ai_key(response: Response, user: User = Depends(current_user)) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return ai_key_state(user)


@router.put("/ai-key")
def put_ai_key(body: KeyBody, response: Response, user: User = Depends(current_user)) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    _need_accounts()
    key = body.key.strip()
    if not aikeys.looks_valid(key):
        raise HTTPException(status_code=422, detail="That doesn't look like a Gemini API key. Copy the whole key from Google AI Studio.")
    if aikeys.too_many_tries(user.id):
        raise HTTPException(status_code=429, detail="Too many tries. Wait a few minutes and try again.")
    try:
        check_key(key)
    except AIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    aikeys.save(user.id, key)
    return ai_key_state(user)


@router.delete("/ai-key")
def delete_ai_key(response: Response, user: User = Depends(current_user)) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    _need_accounts()
    aikeys.remove(user.id)
    return ai_key_state(user)
