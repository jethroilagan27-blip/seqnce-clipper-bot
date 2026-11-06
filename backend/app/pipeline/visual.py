"""Stage 3 - visual analysis.

Local, free: sample frames with FFmpeg + detect scene changes.
One AI call (≤ MAX_AI_FRAMES images) summarises framing and where the speaker
is, which the editor uses for the 9:16 crop. If the AI is unavailable the stage
degrades to a neutral centre-crop result instead of failing the job.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .. import db
from ..ai import AIError, LabeledImage, get_provider
from ..ai.schemas import VisualAnalysis
from ..config import get_settings
from ..services import frames as frames_svc
from .prepare import job_temp_dir
from .transcribe import load_transcript

log = logging.getLogger(__name__)

PROMPT = """You are helping automatically edit a talking-head video into a vertical 9:16 short.
The images above are frames sampled across the video (each preceded by its timestamp).

Video: {width}x{height}, {duration:.0f}s, {fps} fps.
Scene changes detected at (seconds): {scenes}.
Start of the transcript, for context: "{excerpt}"

Describe the visuals as structured JSON:
- main_subject: who/what the footage is about (short phrase)
- speaker_visible: is a person clearly visible and speaking to camera?
- framing: close_up | medium | wide | no_person
- speaker_focus_x: horizontal centre of the main speaker as a fraction of frame width (0 left .. 1 right); 0.5 if unsure
- suitable_for_vertical: would a centred 9:16 crop keep the speaker fully in frame?
- notable_moments: up to 6 visually interesting moments {{time_s, description}} using the frame timestamps
Only describe what you can see. Do not invent details."""


def neutral_analysis(reason: str) -> dict[str, Any]:
    return {
        "analysis_source": "fallback",
        "fallback_reason": reason,
        "main_subject": "unknown",
        "speaker_visible": True,
        "framing": "medium",
        "speaker_focus_x": 0.5,
        "suitable_for_vertical": True,
        "notable_moments": [],
    }


def clean_analysis(raw: VisualAnalysis, duration: float) -> dict[str, Any]:
    """Clamp model output into safe ranges."""
    data = raw.model_dump()
    data["speaker_focus_x"] = min(1.0, max(0.0, float(data["speaker_focus_x"])))
    data["notable_moments"] = [
        {"time_s": round(m["time_s"], 2), "description": m["description"][:200]}
        for m in data["notable_moments"][:6]
        if 0 <= m["time_s"] <= duration + 1
    ]
    data["analysis_source"] = "ai"
    return data


def run(job: dict[str, Any]) -> None:
    job_id = job["id"]
    cfg = get_settings()
    meta = job["metadata_json"]
    src = Path(job["upload_path"])
    frames_dir = job_temp_dir(job_id) / "frames"

    all_frames = frames_svc.extract_frames(src, frames_dir, cfg.frame_interval_s, cfg.frame_width)
    scenes = frames_svc.detect_scenes(src, cfg.scene_threshold)
    chosen = frames_svc.select_frames(all_frames, cfg.max_ai_frames)
    log.info(
        "job %s: %d frames sampled, %d scene changes, %d sent to AI",
        job_id, len(all_frames), len(scenes), len(chosen),
    )

    provider = get_provider()
    if provider is None:
        log.warning("job %s: GEMINI_API_KEY not set - using neutral visual analysis", job_id)
        result = neutral_analysis("no API key configured")
    else:
        try:
            excerpt = " ".join(s["text"] for s in load_transcript(job)["segments"])[:600]
        except Exception:
            excerpt = ""
        prompt = PROMPT.format(
            width=meta["width"], height=meta["height"], duration=meta["duration"],
            fps=meta["fps"], scenes=scenes[:20] or "none", excerpt=excerpt.replace('"', "'"),
        )
        images = [LabeledImage(f"Frame at {f.time_s:.1f}s:", f.path.read_bytes()) for f in chosen]
        try:
            result = clean_analysis(
                provider.generate_structured(prompt, VisualAnalysis, images), meta["duration"]
            )
        except AIError as exc:
            log.warning("job %s: visual AI failed (%s) - using neutral analysis", job_id, exc)
            result = neutral_analysis(str(exc))

    result["frames_sampled"] = len(all_frames)
    result["frames_sent_to_ai"] = len(chosen) if result["analysis_source"] == "ai" else 0
    result["scene_changes"] = scenes
    db.update_job(job_id, visual_json=result)
