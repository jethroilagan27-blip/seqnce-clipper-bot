"""Pydantic models for API requests/responses (never expose server paths)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EditSettings(BaseModel):
    """User-selected editing preferences, stored with the job."""

    target_duration: int = Field(default=45, ge=15, le=90, description="seconds")
    captions: bool = True
    remove_silence: bool = True
    background_music: bool = False
    music_track: str | None = Field(default=None, max_length=100)


class VideoInfo(BaseModel):
    duration: float
    width: int
    height: int
    fps: float
    video_codec: str
    has_audio: bool
    audio_codec: str | None = None
    size_bytes: int


class UploadResponse(BaseModel):
    job_id: str


class JobOut(BaseModel):
    id: str
    status: str  # queued | running | completed | failed
    stage: str
    progress: int
    original_filename: str
    settings: EditSettings
    original: VideoInfo | None = None
    has_output: bool = False
    error: str | None = None
    created_at: str
    updated_at: str


class ResultOut(BaseModel):
    job_id: str
    original: VideoInfo | None
    rendered: VideoInfo | None
    plan: dict[str, Any] | None = None
    preview_url: str
    download_url: str
