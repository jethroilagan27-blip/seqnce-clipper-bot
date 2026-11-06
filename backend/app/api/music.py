"""List the music tracks the user has placed in storage/music."""

from __future__ import annotations

from fastapi import APIRouter

from ..pipeline.editor import list_music

router = APIRouter(prefix="/api/music", tags=["music"])


@router.get("")
def get_music() -> dict[str, list[str]]:
    return {"tracks": list_music()}
