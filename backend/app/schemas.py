"""Pydantic models for API requests/responses (never expose server paths)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .editing.overlays import MAX_TEXTS, TextOverlay


class EditSettings(BaseModel):
    """User-selected editing preferences, stored with the job."""

    target_duration: int = Field(default=45, ge=15, le=90, description="seconds")
    captions: bool = True
    remove_silence: bool = True
    background_music: bool = False
    music_track: str | None = Field(default=None, max_length=100)
    hook: bool = True
    instructions: str = Field(default="", max_length=500, description="Free-text request for the AI editor")


HookColorName = Literal["yellow", "white", "red", "cyan", "green", "pink", "orange"]


class ClipEdit(BaseModel):
    """One clip as drawn on the timeline (source-video seconds)."""

    start: float
    end: float
    purpose: Literal["hook", "main_content", "example", "conclusion"] = "main_content"
    reason: str = Field(default="", max_length=200)


class ManualEdit(BaseModel):
    """Hand edits applied to a version (no AI involved)."""

    hook_enabled: bool | None = None
    hook_text: str | None = Field(default=None, max_length=200)
    hook_color: HookColorName | None = None
    hook_duration_s: float | None = Field(default=None, ge=1, le=10)
    captions_enabled: bool | None = None
    # Dragged positions (centre of the block, fractions of the frame). Send both x and y of a pair.
    caption_x: float | None = Field(default=None, ge=0, le=1)
    caption_y: float | None = Field(default=None, ge=0, le=1)
    hook_x: float | None = Field(default=None, ge=0, le=1)
    hook_y: float | None = Field(default=None, ge=0, le=1)
    reset_positions: list[Literal["caption", "hook"]] = Field(default_factory=list)  # back to the default spot
    texts: list[TextOverlay] | None = Field(default=None, max_length=MAX_TEXTS, description="The complete list of free texts")
    remove_clips: list[str] = Field(default_factory=list, max_length=20)
    clips: list[ClipEdit] | None = Field(default=None, max_length=60, description="The complete new clip list")

    @model_validator(mode="after")
    def _one_way_to_change_clips(self) -> "ManualEdit":
        if self.clips is not None and self.remove_clips:
            raise ValueError("send either clips or remove_clips, not both")
        return self


class TimelineRequest(BaseModel):
    """Ask what a plan would look like, without saving anything."""

    version: int | None = Field(default=None, ge=1, description="Base version; default: the job's current plan")
    edit: ManualEdit | None = None


class RevisionRequest(BaseModel):
    """Exactly one of: a chat message, a hand edit, or a version to go back to."""

    message: str | None = Field(default=None, max_length=1000)
    edit: ManualEdit | None = None
    restore_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _exactly_one(self) -> "RevisionRequest":
        given = [self.message is not None, self.edit is not None, self.restore_version is not None]
        if sum(given) != 1:
            raise ValueError("send exactly one of message, edit, restore_version")
        return self


class RevisionStarted(BaseModel):
    version: int


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
    current_version: int = 1
    revising: bool = False  # a chat/manual revision is queued or running
    error: str | None = None  # for a finished job with an output: why the last revision failed
    created_at: str
    updated_at: str


class ResultOut(BaseModel):
    job_id: str
    version: int = 1
    original: VideoInfo | None
    rendered: VideoInfo | None
    plan: dict[str, Any] | None = None
    preview_url: str
    download_url: str
