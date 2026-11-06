"""Thin, safe wrappers around ffprobe / ffmpeg.

Rules: arguments are always passed as a list (never through a shell), and the
only user-influenced value is a path that *we* generated, never a client path.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..errors import PipelineError

log = logging.getLogger(__name__)

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class MediaError(PipelineError):
    """A media file is unreadable/unsupported, or an ffmpeg step failed.

    The message is safe to show to end users.
    """


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    fps: float
    video_codec: str
    has_audio: bool
    audio_codec: str | None
    audio_sample_rate: int | None
    audio_channels: int | None
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_tool(cmd: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    log.debug("run: %s", " ".join(cmd))
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise MediaError(
            "FFmpeg is not installed or its path is wrong (set FFMPEG_PATH)."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError("Media processing timed out.") from exc


def _parse_fps(rate: str | None) -> float:
    if not rate or rate == "0/0":
        return 0.0
    try:
        return round(float(Fraction(rate)), 3)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _rotation(stream: dict[str, Any]) -> int:
    """Phones often store portrait video as landscape + a rotation flag."""
    for side in stream.get("side_data_list", []) or []:
        if "rotation" in side:
            return int(round(float(side["rotation"])))
    tag = (stream.get("tags") or {}).get("rotate")
    return int(tag) if tag else 0


def probe(path: Path) -> MediaInfo:
    """Return metadata for a media file or raise MediaError."""
    proc = run_tool(
        [
            get_settings().ffprobe,
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        timeout=60,
    )
    if proc.returncode != 0:
        log.warning("ffprobe failed for %s: %s", path.name, proc.stderr.strip()[:300])
        raise MediaError("This file could not be read as a video.")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise MediaError("This file could not be read as a video.") from exc

    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise MediaError("No video stream found in this file.")

    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    if abs(_rotation(video)) in (90, 270):
        width, height = height, width

    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or video.get("duration") or 0)
    if duration <= 0 or width <= 0 or height <= 0:
        raise MediaError("The video has no valid duration or resolution.")

    return MediaInfo(
        duration=round(duration, 3),
        width=width,
        height=height,
        fps=_parse_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        video_codec=video.get("codec_name", "unknown"),
        has_audio=audio is not None,
        audio_codec=audio.get("codec_name") if audio else None,
        audio_sample_rate=int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
        audio_channels=int(audio["channels"]) if audio and audio.get("channels") else None,
        size_bytes=int(fmt.get("size") or path.stat().st_size),
    )


def extract_audio(src: Path, dst: Path) -> None:
    """16 kHz mono WAV - the format Whisper wants."""
    proc = run_tool(
        [
            get_settings().ffmpeg,
            "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(src),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            str(dst),
        ],
        timeout=15 * 60,
    )
    if proc.returncode != 0 or not dst.exists():
        log.error("audio extraction failed: %s", proc.stderr.strip()[:500])
        raise MediaError("Could not extract audio from the video.")


def run_ffmpeg_with_progress(
    cmd: list[str],
    cwd: Path,
    total_s: float,
    on_progress,
    timeout: int = 30 * 60,
) -> None:
    """Run ffmpeg (cmd must include `-progress pipe:1 -nostats`), reporting 0..1.

    Raises MediaError on failure/timeout. stderr is captured to a file so a
    full pipe can never deadlock the process.
    """
    import threading

    log_path = cwd / "ffmpeg.log"
    with log_path.open("w", encoding="utf-8", errors="replace") as errf:
        try:
            proc = subprocess.Popen(
                cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=errf, text=True,
                encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
            )
        except FileNotFoundError as exc:
            raise MediaError("FFmpeg is not installed or its path is wrong (set FFMPEG_PATH).") from exc

        timed_out = threading.Event()

        def _kill() -> None:
            timed_out.set()
            proc.kill()

        timer = threading.Timer(timeout, _kill)
        timer.start()
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                key, _, value = line.strip().partition("=")
                if key in ("out_time_us", "out_time_ms") and value.lstrip("-").isdigit() and total_s > 0:
                    on_progress(min(max(int(value) / 1_000_000 / total_s, 0.0), 1.0))
            proc.wait()
        finally:
            timer.cancel()

    if timed_out.is_set():
        raise MediaError("Rendering took too long and was stopped.")
    if proc.returncode != 0:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-800:]
        log.error("ffmpeg failed (%s): %s", proc.returncode, tail)
        raise MediaError("Rendering the video failed.")
