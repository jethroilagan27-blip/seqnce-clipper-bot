"""Stage 1 - prepare the footage: confirm metadata and extract Whisper audio."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from .. import db
from ..config import get_settings
from ..services import media

log = logging.getLogger(__name__)


def job_temp_dir(job_id: str) -> Path:
    d = get_settings().temp_dir / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def web_copy_path(job_id: str) -> Path:
    return get_settings().temp_dir / job_id / "web.mp4"


def needs_web_copy(info: media.MediaInfo, filename: str) -> bool:
    """Browsers play H.264 in an MP4; phone footage is often HEVC, or a MOV / MKV, which many browsers can't show.
    And a big original (1080p+ or several Mbps) would stutter over the internet: the in-app preview gets a light copy."""
    heavy = max(info.width, info.height) > 1280 or info.size_bytes * 8 > 2_500_000 * max(info.duration, 0.1)
    if heavy:
        return True
    return info.video_codec != "h264" or Path(filename).suffix.lower() not in (".mp4", ".m4v")


def make_web_copy(src: Path, dst: Path) -> bool:
    """A 720p H.264 + AAC copy for the in-browser preview (the edit itself always comes from the original). Never raises."""
    part = dst.with_suffix(".part.mp4")
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        proc = media.run_tool(
            [get_settings().ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
             "-vf", "scale=-2:'min(720,ih)',format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
             "-maxrate", "2M", "-bufsize", "4M",
             "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(part)],
            timeout=60 * 60,
        )
        if proc.returncode != 0 or not part.is_file():
            log.warning("web copy failed: %s", proc.stderr.strip()[:300])
            return False
        part.replace(dst)
        return True
    except Exception:  # a missing preview copy must never fail the edit
        log.exception("web copy crashed")
        return False
    finally:
        part.unlink(missing_ok=True)


def run(job: dict[str, Any]) -> None:
    job_id = job["id"]
    src = Path(job["upload_path"])

    info = media.probe(src)  # cheap; also guards against a file removed since upload
    db.update_job(job_id, metadata_json=info.to_dict())
    if needs_web_copy(info, job.get("original_filename") or src.name):
        # in the background: the edit does not wait for it, the page uses it once it exists
        threading.Thread(target=make_web_copy, args=(src, web_copy_path(job_id)), name=f"webcopy-{job_id[:8]}", daemon=True).start()

    if not info.has_audio:
        # Not fatal here: the transcription stage decides what to do (it needs speech).
        log.warning("job %s: video has no audio track", job_id)
        return

    audio_path = job_temp_dir(job_id) / "audio.wav"
    media.extract_audio(src, audio_path)
    db.update_job(job_id, audio_path=str(audio_path))
    log.info("job %s: prepared (%.1fs, %dx%d)", job_id, info.duration, info.width, info.height)
