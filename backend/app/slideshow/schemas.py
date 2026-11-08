"""Settings and limits for photo mode."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field

from ..editing.overlays import MAX_TEXTS, TextOverlay

SIZES: dict[str, tuple[int, int]] = {"vertical": (1080, 1920), "landscape": (1920, 1080), "square": (1080, 1080)}
FPS = 30

MAX_PHOTOS = int(os.environ.get("SLIDESHOW_MAX_PHOTOS", "400"))
MAX_PHOTO_BYTES = 40 * 1024 * 1024
MAX_BATCH_BYTES = 600 * 1024 * 1024  # one upload request (the browser sends photos in small batches)
MAX_MUSIC_BYTES = 60 * 1024 * 1024
MAX_PROJECTS_PER_USER = int(os.environ.get("SLIDESHOW_MAX_PROJECTS_PER_USER", "5"))
MAX_TOTAL_SECONDS = 30 * 60
MUSIC_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


class SlideshowSettings(BaseModel):
    size: Literal["vertical", "landscape", "square"] = "vertical"
    seconds_per_photo: float = Field(default=2.5, ge=0.5, le=15)
    fit_music: bool = False  # stretch/shrink the time per photo so the video is as long as the music
    zoom: bool = True  # slow push-in / pull-out on each photo
    fade: bool = True  # a quick dip between photos instead of a hard cut
    fill: Literal["blur", "crop", "black"] = "blur"  # what to do when a photo isn't the video's shape
    music_volume: float = Field(default=1.0, ge=0, le=1)
    music_fade_out_s: float = Field(default=2.0, ge=0, le=10)
    texts: list[TextOverlay] = Field(default_factory=list, max_length=MAX_TEXTS)
