"""Stage 5 - EDITING: turn the validated plan into concrete render inputs.

Writes into the job's temp dir:  cuts.json, captions.ass, filter.txt
(the FFmpeg run itself is the next stage, render.py).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .. import db
from ..config import get_settings
from ..editing import captions as cap
from ..editing import cuts as cuts_mod
from ..editing.ffgraph import ASS_NAME, OUT_H, OUT_W, build_filtergraph, compute_crop
from ..errors import PipelineError
from ..plan.schema import EditingPlan
from .prepare import job_temp_dir
from .transcribe import load_transcript

log = logging.getLogger(__name__)

MUSIC_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


def list_music() -> list[str]:
    d = get_settings().music_dir
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_file() and p.suffix.lower() in MUSIC_SUFFIXES)


def resolve_music(track: str | None) -> Path | None:
    """Return a music file from storage/music, or None. Only plain file names are accepted."""
    available = list_music()
    if not available:
        return None
    name = track if track in available else available[0]  # membership check = no path traversal
    return get_settings().music_dir / name


def run(job: dict[str, Any]) -> None:
    job_id = job["id"]
    meta = job["metadata_json"]
    plan = EditingPlan.model_validate(job["plan_json"])
    transcript = load_transcript(job)
    words = cuts_mod.flatten_words(transcript)
    work = job_temp_dir(job_id)

    cuts = cuts_mod.build_cuts(plan, words, float(meta["duration"]))
    if not cuts:
        raise PipelineError("The editing plan did not leave any footage to render.")
    total = cuts_mod.total_duration(cuts)

    warnings = list(plan.warnings)
    music = None
    if plan.music.enabled:
        music = resolve_music(plan.music.track)
        if music is None:
            warnings.append("Background music was requested but no music files were found; skipped.")

    captions_on = plan.captions.enabled
    pages: list[cap.Page] = []
    if captions_on:
        out_words = cap.remap_words(words, cuts)
        pages = cap.build_pages(out_words, plan.captions.max_words_per_line)
        if not pages:
            captions_on = False
            warnings.append("No caption text could be aligned; captions skipped.")

    hook_on = plan.hook.enabled and bool(plan.hook.text.strip())
    texts_on = bool(plan.texts)
    if captions_on or hook_on or texts_on:
        title = cap.HookTitle(plan.hook.text, plan.hook.color, plan.hook.duration_s) if hook_on else None
        cap_pos = (plan.captions.x, plan.captions.y) if plan.captions.x is not None and plan.captions.y is not None else None
        hook_pos = (plan.hook.x, plan.hook.y) if plan.hook.x is not None and plan.hook.y is not None else None
        (work / ASS_NAME).write_text(
            cap.render_ass(
                pages, OUT_W, OUT_H, hook=title, total=total,
                texts=plan.texts, caption_pos=cap_pos, hook_pos=hook_pos,
            ),
            encoding="utf-8",
        )

    crop = compute_crop(int(meta["width"]), int(meta["height"]), plan.reframe.focus_x)
    graph = build_filtergraph(
        cuts, crop, captions=captions_on or hook_on or texts_on, music=music is not None,
        music_volume=plan.music.volume, total=total,
    )
    (work / "filter.txt").write_text(graph, encoding="utf-8")
    (work / "cuts.json").write_text(
        json.dumps({"total": round(total, 3), "cuts": [vars(c) for c in cuts], "music": music.name if music else None,
                    "captions": captions_on, "hook": hook_on}, indent=1),
        encoding="utf-8",
    )

    if warnings != plan.warnings:
        plan.warnings = warnings
        db.update_job(job_id, plan_json=plan.model_dump())
    log.info("job %s: edit prepared, %d cuts, %.1fs, captions=%s hook=%s music=%s",
             job_id, len(cuts), total, captions_on, hook_on, bool(music))
