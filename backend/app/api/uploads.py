"""Uploads in pieces: /api/uploads (see chunked.py for what it is for and the safety rules).

1. POST   /api/uploads                  announce a file; the server decides whether this person may send it
2. PUT    /api/uploads/{id}/{piece}     send one piece (raw bytes, exactly the size the server announced)
3. GET    /api/uploads/{id}             which pieces have arrived (to carry on after a dropped connection)
4. the normal endpoint (video upload, Studio "from-upload") is then given the upload id instead of the file
5. DELETE /api/uploads/{id}             give up
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from .. import chunked
from ..auth import User, current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/uploads", tags=["uploads"])

UPLOAD_ID = r"^[0-9a-f]{32}$"


class CreateBody(BaseModel):
    purpose: str = Field(max_length=20)
    name: str = Field(min_length=1, max_length=400)
    size: int = Field(gt=0, le=50 * 1024 * 1024 * 1024)
    params: dict[str, str] = Field(default_factory=dict, max_length=5)


@router.post("", status_code=201)
def create_upload(body: CreateBody, user: User = Depends(current_user)) -> dict[str, Any]:
    return chunked.create(user, body.purpose, body.name, body.size, {k[:40]: v[:100] for k, v in body.params.items()})


@router.get("/{upload_id}")
def upload_status(upload_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
    return chunked.status(user, upload_id)


@router.put("/{upload_id}/{index}", status_code=204)
async def put_piece(upload_id: str, index: int, request: Request, user: User = Depends(current_user)) -> None:
    """Receive one piece. The login and the session are checked (the dependency runs) before any of the body is read."""
    dest, expected = chunked.piece_path(user, upload_id, index)
    declared = request.headers.get("content-length", "")
    if not declared.isdigit() or int(declared) != expected:
        raise HTTPException(status_code=413 if declared.isdigit() and int(declared) > expected else 422,
                            detail=f"This piece must be exactly {expected} bytes.")
    tmp = dest.with_suffix(".tmp")
    written = 0
    try:
        with tmp.open("wb") as out:
            async for block in request.stream():
                written += len(block)
                if written > expected:
                    raise HTTPException(status_code=413, detail=f"This piece must be exactly {expected} bytes.")
                await run_in_threadpool(out.write, block)
        if written != expected:
            raise HTTPException(status_code=422, detail="The piece was cut short. Send it again.")
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


@router.delete("/{upload_id}", status_code=204)
def cancel_upload(upload_id: str, user: User = Depends(current_user)) -> None:
    chunked.status(user, upload_id)  # 404 unless it is yours
    chunked.discard(upload_id)
