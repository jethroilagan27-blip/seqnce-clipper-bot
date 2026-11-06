"""Stage 6 - RENDERING: run FFmpeg once, then verify the file we produced."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .. import db, stages
from ..config import get_settings
from ..editing.ffgraph import OUT_H, OUT_W
from ..services import media
from .editor import resolve_music
from .prepare import job_temp_dir

log = logging.getLogger(__name__)


def run(job: dict[str, Any]) -> None:
    job_id = job["id"]
    cfg = get_settings()
    work = job_temp_dir(job_id)
    spec = json.loads((work / "cuts.json").read_text(encoding="utf-8"))
    total = float(spec["total"])
    music = resolve_music(job["plan_json"]["music"].get("track")) if spec.get("music") else None

    partial = cfg.outputs_dir / f"{job_id}.partial.mp4"
    final = cfg.outputs_dir / f"{job_id}.mp4"
    partial.unlink(missing_ok=True)

    cmd = [cfg.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1",
           "-i", job["upload_path"]]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
    cmd += [
        "-/filter_complex", "filter.txt",
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
        "-profile:v", "high", "-r", "30",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-movflags", "+faststart",
        "-t", f"{total:.3f}",
        str(partial),
    ]

    lo = stages.STAGE_PROGRESS[stages.RENDERING]
    hi = stages.STAGE_PROGRESS[stages.COMPLETED] - 1
    last = lo

    def on_progress(frac: float) -> None:
        nonlocal last
        pct = lo + int((hi - lo) * frac)
        if pct > last:
            last = pct
            db.update_job(job_id, progress=pct)

    try:
        media.run_ffmpeg_with_progress(cmd, work, total, on_progress)
        info = _verify(partial, total)
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    partial.replace(final)
    db.update_job(job_id, output_path=str(final), output_metadata_json=info.to_dict())
    log.info("job %s: rendered %.1fs, %.1f MB", job_id, info.duration, info.size_bytes / 1e6)


def _verify(path: Path, expected: float) -> media.MediaInfo:
    """Never trust a 'successful' ffmpeg exit: check the file is what we asked for."""
    if not path.is_file() or path.stat().st_size < 10_000:
        raise media.MediaError("The rendered video is missing or empty.")
    info = media.probe(path)
    if (info.width, info.height) != (OUT_W, OUT_H):
        raise media.MediaError("The rendered video has the wrong resolution.")
    if not info.has_audio:
        raise media.MediaError("The rendered video has no audio.")
    if abs(info.duration - expected) > max(1.0, expected * 0.03):
        raise media.MediaError("The rendered video has an unexpected length.")
    return info
