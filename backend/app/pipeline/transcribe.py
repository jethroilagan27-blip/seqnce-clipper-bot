"""Stage 2 - local speech-to-text with faster-whisper.

Output (`transcript.json` in the job's temp dir):
{
  "language": "en", "language_probability": 0.99, "duration": 61.2, "model": "small",
  "segments": [ {"start": 0.0, "end": 4.5, "text": "...",
                 "words": [{"start": 0.0, "end": 0.4, "word": "Welcome"}, ...]} ]
}
Word-level times are kept for accurate captions (Day 5).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from .. import db, stages
from ..config import get_settings
from ..errors import PipelineError
from .prepare import job_temp_dir

log = logging.getLogger(__name__)

_model = None
_model_key: tuple[str, str, str] | None = None
_model_lock = threading.Lock()


def _get_model():
    """Load the Whisper model once per process (loading takes seconds)."""
    global _model, _model_key
    cfg = get_settings()
    key = (cfg.whisper_model, cfg.whisper_device, cfg.whisper_compute_type)
    with _model_lock:
        if _model is None or _model_key != key:
            from faster_whisper import WhisperModel

            log.info("loading whisper model %s on %s (%s)", *key)
            try:
                _model = WhisperModel(key[0], device=key[1], compute_type=key[2])
            except Exception as exc:
                log.exception("could not load whisper model")
                raise PipelineError(
                    "The speech model could not be loaded (first run needs a one-time download)."
                ) from exc
            _model_key = key
    return _model


def _load_wav(path: str):
    """Read our own 16 kHz mono PCM WAV as float32 samples.

    Passing an array means faster-whisper never decodes media itself (its
    decoder depends on PyAV, whose API changes between releases).
    """
    import wave

    import numpy as np

    with wave.open(path, "rb") as wf:
        if wf.getsampwidth() != 2 or wf.getframerate() != 16000 or wf.getnchannels() != 1:
            raise PipelineError("Unexpected audio format after preparation.")
        raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def transcript_path(job_id: str) -> Path:
    return job_temp_dir(job_id) / "transcript.json"


PARTIAL_NAME = "transcript.partial.json"
PARTIAL_EVERY_S = 1.5  # how often the in-progress transcript is saved for the live view


def load_partial(job_id: str) -> dict[str, Any] | None:
    """The transcript so far (text only), while transcription is still running."""
    path = get_settings().temp_dir / job_id / PARTIAL_NAME
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save_partial(job_id: str, info: Any, model_name: str, segments: list[dict[str, Any]]) -> None:
    """Write atomically so the API never reads a half-written file."""
    path = job_temp_dir(job_id) / PARTIAL_NAME
    tmp = path.with_suffix(".tmp")
    data = {
        "complete": False,
        "language": info.language,
        "duration": round(info.duration, 2),
        "model": model_name,
        "segments": [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in segments],
    }
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_transcript(job: dict[str, Any]) -> dict[str, Any]:
    path = job.get("transcript_path")
    if not path or not Path(path).is_file():
        raise PipelineError("The transcript is missing for this job.")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run(job: dict[str, Any]) -> None:
    job_id = job["id"]
    audio = job.get("audio_path")
    if not audio or not Path(audio).is_file():
        raise PipelineError(
            "This video has no audio track, so there is no speech to transcribe. "
            "Talking-head editing needs spoken audio."
        )

    cfg = get_settings()
    meta = job.get("metadata_json") or {}
    total = float(meta.get("duration") or 0)
    model = _get_model()

    segments_iter, info = model.transcribe(
        _load_wav(audio),
        language=cfg.whisper_language or None,
        vad_filter=True,
        word_timestamps=True,
        beam_size=5,
    )

    lo, hi = stages.STAGE_PROGRESS[stages.TRANSCRIBING], stages.STAGE_PROGRESS[stages.ANALYZING_VISUALS] - 1
    last_pct = lo
    segments: list[dict[str, Any]] = []
    last_save = 0.0
    for seg in segments_iter:  # lazy generator: this is where the work happens
        text = seg.text.strip()
        if not text:
            continue
        segments.append(
            {
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": text,
                "words": [
                    {"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word.strip()}
                    for w in (seg.words or [])
                ],
            }
        )
        now = time.monotonic()
        if len(segments) == 1 or now - last_save >= PARTIAL_EVERY_S:
            last_save = now
            try:
                _save_partial(job_id, info, cfg.whisper_model, segments)
            except OSError:
                log.warning("job %s: could not save the partial transcript", job_id)
        if total > 0:
            pct = lo + int((hi - lo) * min(seg.end / total, 1.0))
            if pct > last_pct:
                last_pct = pct
                db.update_job(job_id, progress=pct)

    if not segments:
        raise PipelineError("No speech was detected in this video.")

    out = {
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "duration": round(info.duration, 2),
        "model": cfg.whisper_model,
        "segments": segments,
    }
    path = transcript_path(job_id)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    db.update_job(job_id, transcript_path=str(path))
    log.info(
        "job %s: transcribed %d segments, language=%s",
        job_id, len(segments), info.language,
    )
