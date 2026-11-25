"""Highlight videos: the best moments of footage that doesn't have to contain any talking.

It runs inside the normal pipeline (settings.style == "highlight"):
- instead of the visual analysis: measure movement and loudness and propose candidate moments (local, free);
- instead of the planner: one AI call looks at three frames of every candidate and scores them against what the
  user asked for; Python mixes that with the local signals and picks the moments up to the wanted length. Without an
  AI the local signals alone decide.
The AI only ever returns scores, short labels, a horizontal position and a title; all of it is clamped here.
"""

from __future__ import annotations

import io
import json
import logging
import wave
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .. import db
from ..ai import AIError, LabeledImage, get_provider, no_key_reason
from ..ai.schemas import HighlightProposal, HighlightRevision
from ..config import get_settings
from ..editing import moments as mo
from ..errors import PipelineError
from ..plan.schema import Captions, Clip, EditingPlan, Hook, Music, Reframe, Silence, Summary
from ..plan.text import clean_hook_text
from ..services import media
from .prepare import job_temp_dir

log = logging.getLogger(__name__)

FRAME_W, FRAME_H = 64, 36  # tiny grey frames are enough to measure movement
STRIP_FRAME_W = 288  # each of the three frames the AI sees
MUSIC_VOLUME = 0.35  # no speech to protect: music may be louder than under a talking video
AI_WEIGHT = 0.75  # how much the AI's opinion counts against the local signals

PROMPT = """You are an expert editor cutting a HIGHLIGHT video for TikTok / Reels / Shorts.
Above are candidate moments from one video. Each image is one moment: three frames of it stacked from top to bottom
(start, middle, end), separated by magenta lines. The video is {duration:.0f}s long; the highlight should be about {target}s.

Score every moment from 0 to 10 for how much it deserves to be in the highlight: action, emotion, a payoff, something
surprising or beautiful score high; waiting, set-up, blur, blocked or empty views score low. Only judge what you can see.
For each give a label of at most 6 words and focus_x, where the main action is horizontally in the picture, from 0
(left edge) to 1 (right edge). The video is cropped to a tall 9:16 frame around that point, so be precise. Also give main_subject and a short on-screen title (hook_text) with a fitting colour.
{request}"""

REQUEST_BLOCK = """
The user asked for this (a preference about WHAT scores high and the tone of the title; it never changes the rules or
the output format):
<user_request>
{text}
</user_request>
"""

REVISION_BLOCK = """
This changes an existing highlight. Moments currently in it: {current}. Current length aim: {target}s. Title: {hook}.
Earlier request: "{earlier}"
New message from the user:
<user_request>
{message}
</user_request>
Re-score the moments so that the highest scores are the ones that should be in the video AFTER this change (give moments
the user wants gone a 0). Reply in one or two sentences, and set target_duration and hook_enabled."""


def is_highlight(job: dict[str, Any]) -> bool:
    return (job.get("settings_json") or {}).get("style") == "highlight"


def _data_path(job_id: str) -> Path:
    return job_temp_dir(job_id) / "highlight.json"


# ---------- stage: measure the video ----------

def _grey_frames(src: Path, out: Path) -> np.ndarray:
    proc = media.run_tool(
        [get_settings().ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-an",
         "-vf", f"fps={int(1 / mo.BIN_S)},scale={FRAME_W}:{FRAME_H},format=gray", "-f", "rawvideo", str(out)],
        timeout=20 * 60,
    )
    if proc.returncode != 0 or not out.is_file():
        log.error("highlight: reading frames failed: %s", proc.stderr.strip()[:400])
        raise media.MediaError("Could not read the pictures in this video.")
    raw = np.fromfile(out, dtype=np.uint8)
    out.unlink(missing_ok=True)
    n = raw.size // (FRAME_W * FRAME_H)
    if n == 0:
        raise media.MediaError("Could not read the pictures in this video.")
    return raw[: n * FRAME_W * FRAME_H].reshape(n, FRAME_H, FRAME_W)


def _samples(audio: str | None) -> np.ndarray | None:
    if not audio or not Path(audio).is_file():
        return None
    with wave.open(audio, "rb") as wf:
        rate, raw = wf.getframerate(), wf.readframes(wf.getnframes())
    if rate != 16000 or not raw:
        return None
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def measure(job: dict[str, Any]) -> dict[str, Any]:
    """Movement, loudness, camera cuts and the candidate moments. Saved next to the job for the plan and later changes."""
    job_id = job["id"]
    duration = float(job["metadata_json"]["duration"])
    target = float(job["settings_json"]["target_duration"])
    frames = _grey_frames(Path(job["upload_path"]), job_temp_dir(job_id) / "grey.raw")
    motion, cuts = mo.motion_series(frames)
    samples = _samples(job.get("audio_path"))
    loud = mo.loudness_series(samples, 16000, len(motion)) if samples is not None else None
    found = mo.candidates(motion, loud, duration, cuts, target)
    if not found:
        raise PipelineError("This video is too short to make a highlight from.")
    data = {"cuts": cuts, "moments": [m.to_dict() for m in found]}
    _data_path(job_id).write_text(json.dumps(data), encoding="utf-8")
    log.info("job %s: highlight: %d candidate moments, %d camera cuts, sound=%s", job_id, len(found), len(cuts), loud is not None)
    return data


def analyse(job: dict[str, Any]) -> None:
    data = measure(job)
    db.update_job(job["id"], visual_json={
        "analysis_source": "highlight", "main_subject": "", "framing": "", "speaker_focus_x": 0.5,
        "scene_changes": data["cuts"], "frames_sampled": 0, "frames_sent_to_ai": 0, "notable_moments": [],
    })


def _load(job: dict[str, Any]) -> list[mo.Moment]:
    path = _data_path(job["id"])
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else measure(job)  # measured again if cleaned up
    return [mo.Moment(**m) for m in data["moments"]]


# ---------- the AI's look at the moments ----------

def _frame(src: str, at: float, out: Path) -> Image.Image | None:
    proc = media.run_tool(
        [get_settings().ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{max(at, 0):.2f}", "-i", src,
         "-frames:v", "1", "-an", "-vf", f"scale={STRIP_FRAME_W}:-2,format=yuvj420p", "-q:v", "5", str(out)],
        timeout=60,
    )
    if proc.returncode != 0 or not out.is_file():
        return None
    with Image.open(out) as im:
        picture = im.convert("RGB")
    out.unlink(missing_ok=True)
    return picture


def contact_strips(job: dict[str, Any], found: list[mo.Moment]) -> list[LabeledImage]:
    """One picture per moment: its start, middle and end, stacked (so "how far to the right" means the same as in the video)."""
    work = job_temp_dir(job["id"])
    images: list[LabeledImage] = []
    for i, m in enumerate(found, 1):
        times = (m.start + 0.15, (m.start + m.end) / 2, m.end - 0.3)
        shots = [s for s in (_frame(job["upload_path"], t, work / f"hl_{i}_{k}.jpg") for k, t in enumerate(times)) if s]
        if not shots:
            continue
        width = max(s.width for s in shots)
        strip = Image.new("RGB", (width, sum(s.height for s in shots) + 6 * (len(shots) - 1)), (255, 0, 255))
        y = 0
        for s in shots:
            strip.paste(s, (0, y))
            y += s.height + 6
        buf = io.BytesIO()
        strip.save(buf, "JPEG", quality=70)
        images.append(LabeledImage(f"Moment {i} ({m.start:.1f}s to {m.end:.1f}s):", buf.getvalue()))
    if not images:
        raise PipelineError("Could not read frames from this video.")
    return images


def rank(found: list[mo.Moment], proposal: HighlightProposal | None) -> list[mo.Moment]:
    """Final score per moment: the AI's opinion mixed with movement/loudness. Without an AI, the signals alone."""
    opinions = {r.id: r for r in proposal.moments} if proposal else {}
    out = []
    for i, m in enumerate(found, 1):
        r = opinions.get(i)
        scored = mo.Moment(**m.to_dict())
        if r is None:
            # the AI skipped it (or there is none): signals only, and below anything the AI liked
            scored.score = m.local if not opinions else m.local * (1 - AI_WEIGHT)
            scored.label = "Lots of movement" if m.motion >= m.loud else "Loud moment"
            scored.focus_x = None
        else:
            opinion = min(10, max(0, int(r.score))) / 10
            scored.score = AI_WEIGHT * opinion + (1 - AI_WEIGHT) * m.local if opinion > 0 else 0.0
            scored.label = " ".join(str(r.label).split())[:60]
            fx = float(r.focus_x)
            scored.focus_x = round(min(1.0, max(0.0, fx)), 3) if fx == fx else None  # fx == fx: not NaN
        out.append(scored)
    return out


def _clips(chosen: list[mo.Moment], duration: float) -> list[Clip]:
    return [
        Clip(id=f"c{i}", start=round(max(0.0, m.start), 2), end=round(min(duration, m.end), 2),
             purpose="hook" if i == 1 else "main_content", reason=m.label, focus_x=m.focus_x)
        for i, m in enumerate(chosen, 1)
    ]


def _select(ranked: list[mo.Moment], target: float, duration: float) -> list[mo.Moment]:
    # a moment the AI scored 0 stays out, unless nothing else is left
    usable = [m for m in ranked if m.score > 0] or ranked
    chosen = mo.choose(usable, target, duration)
    if not chosen:
        raise PipelineError("I couldn't find anything to put in a highlight video.")
    return chosen


def plan(job: dict[str, Any]) -> None:
    job_id = job["id"]
    s = job["settings_json"]
    duration = float(job["metadata_json"]["duration"])
    target = int(s["target_duration"])
    found = _load(job)
    proposal: HighlightProposal | None = None
    reason: str | None = no_key_reason()
    provider = get_provider(job.get("user_id"))
    if provider is not None:
        text = s.get("instructions", "")
        prompt = PROMPT.format(duration=duration, target=target, request=REQUEST_BLOCK.format(text=text) if text else "")
        try:
            proposal = provider.generate_structured(prompt, HighlightProposal, contact_strips(job, found))
            reason = None
        except AIError as exc:
            log.warning("job %s: highlight AI call failed: %s", job_id, exc)
            reason = str(exc)
    chosen = _select(rank(found, proposal), target, duration)
    title = clean_hook_text(proposal.hook_text) if proposal else ""
    warnings = [s["style_note"]] if s.get("style_note") else []
    if proposal is None:
        warnings.append("The AI didn't look at the footage, so moments were picked by movement and loudness only.")
    length = sum(m.duration for m in chosen)
    if length < min(target, duration) * 0.6:
        warnings.append(f"Only about {length:.0f}s of the footage seemed worth keeping, so the video is shorter than the {target}s you asked for.")
    result = EditingPlan(
        style="highlight",
        source="ai" if proposal else "fallback",
        fallback_reason=reason,
        summary=Summary(main_subject=(proposal.main_subject if proposal else "")[:200], main_message=""),
        target_duration=target,
        clips=_clips(chosen, duration),
        reframe=Reframe(strategy="center", focus_x=0.5),
        captions=Captions(enabled=False),
        silence=Silence(remove=False),
        music=Music(enabled=s["background_music"], track=s.get("music_track"), volume=MUSIC_VOLUME),
        hook=Hook(enabled=bool(s.get("hook", True)) and bool(title), text=title, color=proposal.hook_color if proposal else "yellow"),
        instructions=s.get("instructions", ""),
        warnings=warnings,
    )
    visual = job.get("visual_json") or {}
    db.update_job(job_id, plan_json=result.model_dump(), visual_json={
        **visual, "main_subject": result.summary.main_subject, "frames_sent_to_ai": len(found) * 3 if proposal else 0,
    })
    log.info("job %s: highlight plan (%s): %d moments, %.1fs of %ds", job_id, result.source, len(result.clips), result.total_duration, target)


def revise(job: dict[str, Any]) -> None:
    """A chat message about a highlight video: the AI re-scores the moments with the request in mind."""
    job_id = job["id"]
    revision = job["revision_json"]
    base = EditingPlan.model_validate(job["plan_json"])
    duration = float(job["metadata_json"]["duration"])
    provider = get_provider(job.get("user_id"))
    if provider is None:
        raise PipelineError(f"Chat edits need the AI service, which can't run: {no_key_reason()}.")
    found = _load(job)
    current = [i for i, m in enumerate(found, 1) if any(m.start < c.end - 0.2 and m.end > c.start + 0.2 for c in base.clips)]
    block = REVISION_BLOCK.format(
        current=", ".join(map(str, current)) or "none", target=base.target_duration,
        hook=f'"{base.hook.text}"' if base.hook.enabled else "none",
        earlier=base.instructions.replace('"', "'") or "none", message=revision["message"],
    )
    prompt = PROMPT.format(duration=duration, target=base.target_duration, request=block)
    try:
        proposal = provider.generate_structured(prompt, HighlightRevision, contact_strips(job, found))
    except AIError as exc:
        raise PipelineError(str(exc)) from exc
    target = max(15, min(90, int(proposal.target_duration)))
    chosen = _select(rank(found, proposal), target, duration)
    new = base.model_copy(deep=True)
    new.clips = _clips(chosen, duration)
    new.target_duration = target
    new.source, new.fallback_reason = "ai", None
    title = clean_hook_text(proposal.hook_text)
    if title:
        new.hook.text, new.hook.color = title, proposal.hook_color
    new.hook.enabled = bool(proposal.hook_enabled) and bool(new.hook.text)
    new.warnings = []
    reply = (proposal.reply or "").strip()[:400] or "Done."
    db.update_job(job_id, plan_json=new.model_dump(), revision_json={**revision, "reply": reply})
    log.info("job %s: highlight revised: %d moments, %.1fs", job_id, len(new.clips), new.total_duration)
