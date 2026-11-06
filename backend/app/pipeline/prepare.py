"""Stage 1 - prepare the footage: confirm metadata and extract Whisper audio."""

from __future__ import annotations

import logging
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


def run(job: dict[str, Any]) -> None:
    job_id = job["id"]
    src = Path(job["upload_path"])

    info = media.probe(src)  # cheap; also guards against a file removed since upload
    db.update_job(job_id, metadata_json=info.to_dict())

    if not info.has_audio:
        # Not fatal here: the transcription stage decides what to do (it needs speech).
        log.warning("job %s: video has no audio track", job_id)
        return

    audio_path = job_temp_dir(job_id) / "audio.wav"
    media.extract_audio(src, audio_path)
    db.update_job(job_id, audio_path=str(audio_path))
    log.info("job %s: prepared (%.1fs, %dx%d)", job_id, info.duration, info.width, info.height)
