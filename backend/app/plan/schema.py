"""The editing plan: the only thing the editor (Day 5) ever executes.

The AI proposes clips (`PlanProposal`, in app/ai/schemas.py). Everything else
here is filled in by our own code from user settings + visual analysis, so the
AI cannot invent options the editor doesn't support.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..editing.overlays import MAX_TEXTS, TextOverlay

Purpose = Literal["hook", "main_content", "example", "conclusion"]


class Clip(BaseModel):
    id: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    purpose: Purpose
    reason: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start


class Summary(BaseModel):
    main_subject: str = ""
    main_message: str = ""


class Format(BaseModel):
    aspect_ratio: Literal["9:16"] = "9:16"
    width: int = 1080
    height: int = 1920


class Reframe(BaseModel):
    strategy: Literal["center", "focus"] = "center"
    focus_x: float = Field(default=0.5, ge=0, le=1)  # horizontal speaker position, 0..1


class Captions(BaseModel):
    enabled: bool = True
    max_words_per_line: int = Field(default=4, ge=1, le=8)
    max_lines: int = Field(default=2, ge=1, le=3)
    # Where the user dragged the caption block (centre, fractions of the frame). None = the default spot.
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)


class Silence(BaseModel):
    remove: bool = True
    max_pause_s: float = Field(default=0.6, ge=0.2, le=3.0)


HookColor = Literal["yellow", "white", "red", "cyan", "green", "pink", "orange"]
HOOK_COLORS: tuple[str, ...] = ("yellow", "white", "red", "cyan", "green", "pink", "orange")


class Hook(BaseModel):
    """Big title text shown at the top for the first seconds of the short."""

    enabled: bool = False
    text: str = Field(default="", max_length=80)
    color: HookColor = "yellow"
    duration_s: float = Field(default=4.0, ge=1, le=10)
    x: float | None = Field(default=None, ge=0, le=1)  # dragged position (centre); None = default
    y: float | None = Field(default=None, ge=0, le=1)


class Music(BaseModel):
    enabled: bool = False
    track: str | None = None
    volume: float = Field(default=0.12, ge=0, le=1)


class EditingPlan(BaseModel):
    version: Literal[1] = 1
    source: Literal["ai", "fallback"] = "ai"
    fallback_reason: str | None = None
    summary: Summary = Field(default_factory=Summary)
    format: Format = Field(default_factory=Format)
    target_duration: int
    clips: list[Clip]
    reframe: Reframe = Field(default_factory=Reframe)
    captions: Captions = Field(default_factory=Captions)
    silence: Silence = Field(default_factory=Silence)
    music: Music = Field(default_factory=Music)
    hook: Hook = Field(default_factory=Hook)
    texts: list[TextOverlay] = Field(default_factory=list, max_length=MAX_TEXTS)  # free text the user placed
    instructions: str = ""  # the user's free-text request, echoed back in the UI
    warnings: list[str] = Field(default_factory=list)

    @property
    def total_duration(self) -> float:
        return sum(c.duration for c in self.clips)
