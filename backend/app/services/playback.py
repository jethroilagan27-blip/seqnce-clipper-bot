"""Light copies for watching in the app.

A finished video is made for posting (1080x1920, several Mbps). Streaming that over a home upload connection stutters,
so every finished video also gets a small copy (short side 720, about 1.5 Mbps) that the in-app players use. The
download is always the full-quality file.

The copy sits next to its video as `<name>.play.mp4`. It is made right after the render, by the same worker, so a
player never has the file switched under it; a copy older than its video (a re-render) is ignored.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from ..config import get_settings
from . import media

log = logging.getLogger(__name__)

SHORT_SIDE = 720
MAX_KBPS = 1600


def path_for(video: Path) -> Path:
    return video.with_name(f"{video.stem}.play.mp4")


def best(video: Path) -> Path:
    """What a player should be sent: the light copy if there is an up-to-date one, else the video itself."""
    copy = path_for(video)
    try:
        return copy if copy.is_file() and copy.stat().st_mtime >= video.stat().st_mtime else video
    except OSError:
        return video


def make(video: Path) -> bool:
    """Make the light copy. Never raises: a missing copy only means playing the full video. False = no copy kept."""
    copy = path_for(video)
    part = video.with_name(f"{video.stem}.{uuid.uuid4().hex[:8]}.play.part.mp4")
    scale = f"scale='if(gt(iw,ih),-2,min({SHORT_SIDE},iw))':'if(gt(iw,ih),min({SHORT_SIDE},ih),-2)':flags=bicubic,format=yuv420p"
    try:
        before = video.stat()
        proc = media.run_tool(
            [get_settings().ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video), "-vf", scale,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-maxrate", f"{MAX_KBPS}k", "-bufsize", f"{MAX_KBPS * 2}k",
             "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(part)],
            timeout=60 * 60,
        )
        if proc.returncode != 0 or not part.is_file():
            log.warning("playback copy of %s failed: %s", video.name, proc.stderr.strip()[:300])
            return False
        if part.stat().st_size >= before.st_size * 0.85:  # already small: the video itself is the best thing to play
            copy.unlink(missing_ok=True)
            return False
        if video.stat().st_mtime != before.st_mtime:  # re-rendered while we were at it: this copy shows the old one
            return False
        part.replace(copy)
        return True
    except Exception:
        log.exception("playback copy of %s crashed", video.name)
        return False
    finally:
        part.unlink(missing_ok=True)


def delete(video: Path) -> None:
    path_for(video).unlink(missing_ok=True)
