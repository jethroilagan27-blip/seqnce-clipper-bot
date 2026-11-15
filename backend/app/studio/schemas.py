"""The Studio project document: scenes, each with clips, a voice-over, music and text.

Everything the editor page shows and everything the renderer needs is this one document (saved as JSON).
Clips, audio and pictures are referred to by asset id; the files themselves are uploaded separately.
All times are seconds; positions are fractions of the frame (see app/editing/overlays.py).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..editing.overlays import MAX_TEXTS, TextOverlay

FPS = 30
AUDIO_RATE = 48000
DEFAULT_IMAGE_S = 3.0
MAX_SCENES_HARD = 300  # a sanity limit; what an account may use is set by its plan (features.py)
MAX_VISUALS_PER_SCENE = 60
MAX_SCENE_SECONDS = 600

_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_FONT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,59}$")  # no commas or braces: it goes into a subtitle file

FrameShape = Literal["landscape", "vertical", "square"]  # the shape of the finished video

# frame size by (shape, quality height): "final" renders use 720 or 1080 (what the plan allows), previews use 360
_SIZES: dict[int, dict[str, tuple[int, int]]] = {
    1080: {"landscape": (1920, 1080), "vertical": (1080, 1920), "square": (1080, 1080)},
    720: {"landscape": (1280, 720), "vertical": (720, 1280), "square": (720, 720)},
    360: {"landscape": (640, 360), "vertical": (360, 640), "square": (360, 360)},
}


def frame_size(shape: str, height: int) -> tuple[int, int]:
    """Pixels (width, height) for a shape at 360, 720 or 1080 quality (anything else rounds down to one of these)."""
    quality = 1080 if height >= 1080 else 720 if height >= 720 else 360
    return _SIZES[quality][shape]


class StudioText(TextOverlay):
    """A text on a scene (times are counted from the start of the scene)."""

    font: str = ""  # "" = the default font
    anim: Literal["none", "zoom_in", "zoom_out"] = "none"  # slow zoom while it is on screen (title reveals)

    @field_validator("font")
    @classmethod
    def _font_name(cls, v: str) -> str:
        v = v.strip()
        if v and not _FONT.match(v):
            raise ValueError("font name has characters that aren't allowed")
        return v


class Visual(BaseModel):
    """One clip or picture shown in a scene, in order."""

    id: str = Field(pattern=_ID.pattern)
    asset_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    start: float = Field(default=0, ge=0, le=36000)  # where in the clip to begin (clips only)
    length: float | None = Field(default=None, gt=0, le=3600)  # seconds to use; None = to the end (pictures: 3 s)
    fit: Literal["blur", "crop", "fit"] = "blur"  # when its shape isn't the frame's: blurred copy behind / cut to fill / black bars
    zoom: Literal["none", "in", "out"] = "none"  # slow push-in / pull-out
    volume: float = Field(default=1.0, ge=0, le=2)  # the clip's own sound (0 = muted, e.g. movie clips under a voice-over)


class Voiceover(BaseModel):
    asset_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    volume: float = Field(default=1.0, ge=0, le=2)
    offset: float = Field(default=0, ge=0, le=MAX_SCENE_SECONDS)  # start this many seconds into the scene


class SceneMusic(BaseModel):
    asset_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    start: float = Field(default=0, ge=0, le=36000)  # which part of the track to play from
    volume: float = Field(default=0.6, ge=0, le=2)
    fade_in: float = Field(default=0, ge=0, le=30)
    fade_out: float = Field(default=0, ge=0, le=30)
    duck: bool = True  # lower by itself while the voice-over speaks (needs the "ducking" feature)


class BedMusic(BaseModel):
    """Music under the whole video (looped if it is shorter, faded out at the end)."""

    asset_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    start: float = Field(default=0, ge=0, le=36000)
    volume: float = Field(default=0.25, ge=0, le=2)
    fade_out: float = Field(default=3.0, ge=0, le=30)
    duck: bool = True  # lower by itself whenever anything in the video speaks (needs the "ducking" feature)


class Overlay(BaseModel):
    """A picture or a clip shown on top of the scene for a while: a poster, a flag, a map, a chart, a small video."""

    id: str = Field(pattern=_ID.pattern)
    asset_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    x: float = Field(default=0.5, ge=0, le=1)  # centre, as a fraction of the frame
    y: float = Field(default=0.5, ge=0, le=1)
    width: float = Field(default=0.4, ge=0.03, le=1.5)  # as a fraction of the frame's width
    start: float = Field(default=0, ge=0)  # seconds from the start of the scene
    end: float | None = Field(default=None, gt=0)  # None = until the end of the scene
    fade: bool = True
    anim: Literal["none", "pop", "zoom_in"] = "none"  # pop = grows in quickly; zoom_in = grows slowly all the time it is shown

    @model_validator(mode="after")
    def _order(self) -> "Overlay":
        if self.end is not None and self.end <= self.start:
            raise ValueError("an overlay must end after it starts")
        return self


class Shape(BaseModel):
    """A drawn highlight: a box around a number, a circle around a country, a map pin."""

    id: str = Field(pattern=_ID.pattern)
    kind: Literal["rect", "ellipse", "pin"] = "rect"
    x: float = Field(default=0.5, ge=0, le=1)  # centre, as a fraction of the frame
    y: float = Field(default=0.5, ge=0, le=1)
    w: float = Field(default=0.3, ge=0.01, le=1)  # width as a fraction of the frame's width
    h: float = Field(default=0.1, ge=0.01, le=1)  # height as a fraction of the frame's height (a pin's size is its width)
    color: str = "#ffd400"
    thickness: float = Field(default=0.4, ge=0, le=3)  # outline, as a % of the frame's width (0 = no outline)
    fill: float = Field(default=0, ge=0, le=1)  # 0 = outline only; 0.3 = like a highlighter pen
    start: float = Field(default=0, ge=0)
    end: float | None = Field(default=None, gt=0)
    fade: bool = True
    anim: Literal["none", "drop"] = "none"  # drop = falls in from above (the map-pin look)

    @field_validator("color")
    @classmethod
    def _color(cls, v: str) -> str:
        if not re.match(r"^#[0-9a-fA-F]{6}$", v):
            raise ValueError("color must look like #RRGGBB")
        return v.lower()

    @model_validator(mode="after")
    def _order(self) -> "Shape":
        if self.end is not None and self.end <= self.start:
            raise ValueError("a shape must end after it starts")
        return self


class Grid(BaseModel):
    """Several clips on screen at the same time, in rows and columns (every cell starts together)."""

    cols: int = Field(default=3, ge=1, le=6)
    rows: int = Field(default=2, ge=1, le=6)
    gap: int = Field(default=8, ge=0, le=60)  # pixels between the cells (measured on a 1920-wide frame)
    delay: float = Field(default=0, ge=0, le=120)  # seconds of the background (and the voice-over) before the cells appear together
    cells: list[Visual] = Field(default_factory=list, max_length=36)  # left to right, top to bottom


class Credits(BaseModel):
    """Rolling credits: the lines scroll up the screen. A line starting with "# " is a heading (bigger)."""

    lines: list[str] = Field(default_factory=list, max_length=300)
    size: float = Field(default=3.4, ge=1.5, le=10)  # % of the frame's width
    color: str = "#ffffff"
    font: str = ""
    seconds: float | None = Field(default=None, gt=1, le=600)  # how long the roll lasts; None = a comfortable reading speed

    @field_validator("lines")
    @classmethod
    def _lines(cls, v: list[str]) -> list[str]:
        return [re.sub(r"[\x00-\x1f\x7f]", " ", line)[:120] for line in v]

    @field_validator("color")
    @classmethod
    def _color(cls, v: str) -> str:
        if not re.match(r"^#[0-9a-fA-F]{6}$", v):
            raise ValueError("color must look like #RRGGBB")
        return v.lower()

    @field_validator("font")
    @classmethod
    def _font_name(cls, v: str) -> str:
        v = v.strip()
        if v and not _FONT.match(v):
            raise ValueError("font name has characters that aren't allowed")
        return v


class Scene(BaseModel):
    id: str = Field(pattern=_ID.pattern)
    name: str = Field(default="Scene", max_length=80)
    visuals: list[Visual] = Field(default_factory=list, max_length=MAX_VISUALS_PER_SCENE)
    voiceover: Voiceover | None = None
    music: SceneMusic | None = None
    texts: list[StudioText] = Field(default_factory=list, max_length=MAX_TEXTS)
    overlays: list[Overlay] = Field(default_factory=list, max_length=40)
    shapes: list[Shape] = Field(default_factory=list, max_length=40)
    grid: Grid | None = None  # when set, the scene shows these clips side by side instead of "visuals" one after another
    credits: Credits | None = None
    background: str = "#000000"  # shown when the scene has no clips (title cards, questions on black)
    min_duration: float | None = Field(default=None, gt=0, le=MAX_SCENE_SECONDS)  # at least this long
    fit_to_voiceover: bool = False  # give every clip / picture an equal share of the voice-over's length
    open_effect: Literal["none", "letterbox"] = "none"  # letterbox: starts as a narrow band that opens to the full frame
    open_s: float = Field(default=1.2, ge=0.3, le=5)
    fade_in: float = Field(default=0, ge=0, le=10)  # from black
    fade_out: float = Field(default=0, ge=0, le=10)  # to black
    transition_in: Literal["cut", "crossfade"] = "cut"  # how it follows the previous scene
    crossfade_s: float = Field(default=0.8, ge=0.1, le=5)

    @field_validator("background")
    @classmethod
    def _bg(cls, v: str) -> str:
        if not re.match(r"^#[0-9a-fA-F]{6}$", v):
            raise ValueError("background must look like #RRGGBB")
        return v.lower()

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return re.sub(r"[\x00-\x1f\x7f]", " ", v).strip() or "Scene"


class StudioDoc(BaseModel):
    title: str = Field(default="Untitled video", max_length=80)
    shape: FrameShape = "landscape"
    scenes: list[Scene] = Field(default_factory=list, max_length=MAX_SCENES_HARD)
    bed_music: BedMusic | None = None
    normalize_loudness: bool = True  # even out the volume of the finished video

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return re.sub(r"[\x00-\x1f\x7f]", " ", v).strip() or "Untitled video"

    @model_validator(mode="after")
    def _unique_scene_ids(self) -> "StudioDoc":
        ids = [s.id for s in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("two scenes have the same id")
        return self

    def asset_ids(self) -> set[str]:
        """Every asset the document refers to."""
        found: set[str] = set()
        for scene in self.scenes:
            found.update(v.asset_id for v in scene.visuals)
            found.update(o.asset_id for o in scene.overlays)
            if scene.grid:
                found.update(c.asset_id for c in scene.grid.cells)
            if scene.voiceover:
                found.add(scene.voiceover.asset_id)
            if scene.music:
                found.add(scene.music.asset_id)
        if self.bed_music:
            found.add(self.bed_music.asset_id)
        return found

    def without_assets(self, gone: set[str]) -> "StudioDoc":
        """A copy with every reference to the given assets removed (used when a file is deleted)."""
        scenes = []
        for s in self.scenes:
            scenes.append(
                s.model_copy(update={
                    "visuals": [v for v in s.visuals if v.asset_id not in gone],
                    "overlays": [o for o in s.overlays if o.asset_id not in gone],
                    "grid": s.grid.model_copy(update={"cells": [c for c in s.grid.cells if c.asset_id not in gone]}) if s.grid else None,
                    "voiceover": None if s.voiceover and s.voiceover.asset_id in gone else s.voiceover,
                    "music": None if s.music and s.music.asset_id in gone else s.music,
                })
            )
        bed = None if self.bed_music and self.bed_music.asset_id in gone else self.bed_music
        return self.model_copy(update={"scenes": scenes, "bed_music": bed})


# ---- limits for uploads -------------------------------------------------------

VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
FONT_SUFFIXES = {".ttf", ".otf"}
MAX_BATCH_BYTES = 400 * 1024 * 1024  # one upload request (the page sends files one or a few at a time)
MAX_ASSET_SECONDS = 60 * 60
