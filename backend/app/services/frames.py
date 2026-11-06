"""Frame sampling and scene detection with FFmpeg (all local, no AI cost)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings
from .media import MediaError, run_tool

log = logging.getLogger(__name__)


@dataclass
class Frame:
    time_s: float
    path: Path


def extract_frames(src: Path, out_dir: Path, interval_s: float, width: int) -> list[Frame]:
    """One downscaled JPEG every `interval_s` seconds. Frame i is at i*interval_s."""
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame_*.jpg"):
        old.unlink()

    proc = run_tool(
        [
            get_settings().ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(src),
            "-an",
            "-vf", f"fps=1/{interval_s},scale={width}:-2",
            "-q:v", "5",
            str(out_dir / "frame_%05d.jpg"),
        ],
        timeout=15 * 60,
    )
    if proc.returncode != 0:
        log.error("frame extraction failed: %s", proc.stderr.strip()[:500])
        raise MediaError("Could not extract frames from the video.")

    files = sorted(out_dir.glob("frame_*.jpg"))
    if not files:
        raise MediaError("No frames could be extracted from the video.")
    return [Frame(time_s=round(i * interval_s, 2), path=p) for i, p in enumerate(files)]


_PTS = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")


def detect_scenes(src: Path, threshold: float, max_scenes: int = 60) -> list[float]:
    """Timestamps (s) where the picture changes a lot. Best-effort: [] on failure."""
    proc = run_tool(
        [
            get_settings().ffmpeg, "-hide_banner", "-nostats", "-an",
            "-i", str(src),
            "-vf", f"scale=320:-2,select='gt(scene,{threshold})',showinfo",
            "-f", "null", "-",
        ],
        timeout=15 * 60,
    )
    if proc.returncode != 0:
        log.warning("scene detection failed: %s", proc.stderr.strip()[-300:])
        return []
    times = [round(float(m.group(1)), 2) for m in _PTS.finditer(proc.stderr)]
    return times[:max_scenes]


def select_frames(frames: list[Frame], max_n: int) -> list[Frame]:
    """Evenly spaced subset (always includes first and last) of at most `max_n`."""
    if max_n <= 0:
        return []
    if len(frames) <= max_n:
        return list(frames)
    if max_n == 1:
        return [frames[0]]
    step = (len(frames) - 1) / (max_n - 1)
    idx = sorted({round(i * step) for i in range(max_n)})
    return [frames[i] for i in idx]
