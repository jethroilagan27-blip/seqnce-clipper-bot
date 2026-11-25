"""The editing plan: the only thing the editor (Day 5) ever executes.

The AI proposes clips (`PlanProposal`, in app/ai/schemas.py). Everything else
here is filled in by our own code from user settings + visual analysis, so the
AI cannot invent options the editor doesn't support.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_serializer, model_validator

from ..editing.fixes import MAX_FIXES, CaptionFix
from ..editing.overlays import MAX_TEXTS, TextOverlay

Purpose = Literal["hook", "main_content", "example", "conclusion"]
MIN_TARGET_S, MAX_TARGET_S = 15, 600  # the finished length that can be asked for


class Clip(BaseModel):
    id: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    purpose: Purpose
    reason: str = ""
    focus_x: float | None = Field(default=None, ge=0, le=1)  # this clip's own 9:16 crop position (highlights)
    framing: Literal["crop", "whole"] | None = None  # highlights: crop around focus_x, or show the whole picture

    @property
    def duration(self) -> float:
        return self.end - self.start

    @model_serializer(mode="wrap")
    def _only_say_what_is_set(self, handler):
        data = handler(self)
        for key in ("focus_x", "framing"):  # talking videos have one crop for the whole plan: no per-clip fields
            if data.get(key) is None:
                data.pop(key, None)
        return data


class Summary(BaseModel):
    main_subject: str = ""
    main_message: str = ""


AspectRatio = Literal["9:16", "16:9"]
SIZES: dict[str, tuple[int, int]] = {"9:16": (1080, 1920), "16:9": (1920, 1080)}
SHAPE_NAMES = {"9:16": "upright (9:16)", "16:9": "landscape (16:9)"}


class Format(BaseModel):
    aspect_ratio: AspectRatio = "9:16"
    width: int = 1080
    height: int = 1920

    @model_validator(mode="after")
    def _size_follows_the_shape(self) -> "Format":
        self.width, self.height = SIZES[self.aspect_ratio]
        return self

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height


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
    fixes: list[CaptionFix] = Field(default_factory=list, max_length=MAX_FIXES)  # words the user corrected

    @model_serializer(mode="wrap")
    def _only_say_what_is_set(self, handler):
        data = handler(self)
        if not data.get("fixes"):
            data.pop("fixes", None)
        return data


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
    style: Literal["talking", "highlight"] = "talking"
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
