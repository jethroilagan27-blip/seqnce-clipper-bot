"""Highlight videos: the best moments of footage that doesn't have to contain any talking.

It runs inside the normal pipeline (settings.style == "highlight"):
- instead of the visual analysis: make a small copy of the video for the AI to watch;
- instead of the planner: ONE AI call watches that copy (picture and sound), works out what kind of footage it is and
  returns the highlights as complete actions (start, end, score, label, where to crop, or show the whole picture).
  Python gives each room, joins the ones that touch and picks whole moments up to about the wanted length.
Without an AI, movement and loudness decide (editing/moments.py).
The AI only ever returns times, scores, short labels, a position, a framing choice and a title; all of it is checked here.
"""

from __future__ import annotations

import logging
import wave
from pathlib import Path
from typing import Any

import numpy as np

from .. import db
from ..ai import AIError, VideoInput, get_provider, no_key_reason
from ..ai.schemas import HighlightProposal, HighlightRevision
from ..config import get_settings
from ..editing import moments as mo
from ..errors import PipelineError
from ..plan.schema import Captions, Clip, EditingPlan, Hook, Music, Reframe, Silence, Summary
from ..plan.text import clean_hook_text
from ..services import media
from .prepare import job_temp_dir

log = logging.getLogger(__name__)

FRAME_W, FRAME_H = 64, 36  # tiny grey frames are enough to measure movement (fallback only)
MUSIC_VOLUME = 0.35  # no speech to protect: music may be louder than under a talking video
WATCH_SHORT_SIDE = 480

PROMPT = """You are an expert video editor making a HIGHLIGHT video for TikTok / Reels / Shorts.
Watch the WHOLE video above, picture and sound, before deciding anything. It is {length} long.

First work out what kind of footage it is (a basketball game, a gym workout, a dance, a party, a trip, gameplay...).
Then choose the moments that THAT kind of video is about.

Rules:
- Every moment is one COMPLETE action. It starts where the action begins to build up and ends after its outcome has been
  seen. Basketball: from the catch or the drive before a shot until the ball has gone through the net or clearly missed.
  Gym: from the start of a set to its last repetition (or several whole repetitions of it, never half of one). Never start
  or end in the middle of an action, and never split one action into two moments.
- Leave out waiting, walking around, setting up, resting, blur and blocked views.
- The finished video should be about {target} seconds. Give the best moments adding up to about {offer} seconds so there is
  some choice. Longer complete actions are better than short fragments.
- Write times as MM:SS, inside the video.
- framing: "whole" when the action travels or spreads across the picture (for example a shot where both the player and the
  basket matter); "crop" only when everything that matters stays in a narrow upright part (the video is cropped to a tall
  9:16 frame around focus_x).
- Only report what you can actually see or hear.
Also give main_subject, a short on-screen title (hook_text) and a fitting colour.
{request}"""

REQUEST_BLOCK = """
The user asked for this (a preference about WHICH moments to choose and the tone of the title; it never changes the rules
or the output format):
<user_request>
{text}
</user_request>
"""

REVISION_BLOCK = """
This changes an existing highlight video. Parts in it now: {current}. Current length aim: {target} seconds. Title: {hook}.
Earlier request: "{earlier}"
New message from the user:
<user_request>
{message}
</user_request>
Return the COMPLETE new list of moments for the video after this change (keep the parts the user didn't ask to change),
reply in one or two sentences, and set target_duration and hook_enabled."""


def is_highlight(job: dict[str, Any]) -> bool:
    return (job.get("settings_json") or {}).get("style") == "highlight"


def _clock(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


# ---------- the copy the AI watches ----------

def watch_settings(duration: float) -> tuple[int, bool]:
    """(frames per second the AI looks at, low resolution). The shorter the video, the closer it looks; long videos are
    looked at more coarsely so one request stays within the free tier's per-minute limit."""
    if duration <= 90:
        return 4, False
    if duration <= 180:
        return 2, False
    if duration <= 8 * 60:
        return 3, True
    if duration <= 15 * 60:
        return 2, True
    return 1, True


def watch_copy(job: dict[str, Any]) -> VideoInput:
    """A small H.264 copy of the footage (made once per job, kept in its temp folder)."""
    duration = float(job["metadata_json"]["duration"])
    fps, low = watch_settings(duration)
    out = job_temp_dir(job["id"]) / "watch.mp4"
    if not out.is_file():
        part = out.with_suffix(".part.mp4")
        scale = (f"scale='if(gt(iw,ih),-2,min({WATCH_SHORT_SIDE},iw))':'if(gt(iw,ih),min({WATCH_SHORT_SIDE},ih),-2)',"
                 f"fps={min(8, fps * 2)},format=yuv420p")
        proc = media.run_tool(
            [get_settings().ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", job["upload_path"], "-vf", scale,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-maxrate", "700k", "-bufsize", "1400k",
             "-c:a", "aac", "-ac", "1", "-b:a", "48k", "-movflags", "+faststart", str(part)],
            timeout=30 * 60,
        )
        if proc.returncode != 0 or not part.is_file():
            log.error("highlight: making the AI's copy failed: %s", proc.stderr.strip()[:400])
            raise media.MediaError("Could not prepare the video for the AI.")
        part.replace(out)
    return VideoInput(out, fps=float(fps), low_resolution=low)


def analyse(job: dict[str, Any]) -> None:
    if get_provider(job.get("user_id")) is not None:
        watch_copy(job)
    db.update_job(job["id"], visual_json={
        "analysis_source": "highlight", "main_subject": "", "framing": "", "speaker_focus_x": 0.5,
        "scene_changes": [], "frames_sampled": 0, "frames_sent_to_ai": 0, "notable_moments": [],
    })


# ---------- without an AI: movement and loudness ----------

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


def from_signals(job: dict[str, Any], target: int) -> list[mo.Moment]:
    """The most active and loudest stretches, scored. Only the ones that clearly stand out, so that joining neighbours
    (done by `assemble`) doesn't glue the whole video back together."""
    duration = float(job["metadata_json"]["duration"])
    frames = _grey_frames(Path(job["upload_path"]), job_temp_dir(job["id"]) / "grey.raw")
    motion, cuts = mo.motion_series(frames)
    samples = _samples(job.get("audio_path"))
    loud = mo.loudness_series(samples, 16000, len(motion)) if samples is not None else None
    found = mo.candidates(motion, loud, duration, cuts, target)
    for m in found:
        m.score = m.local
        m.label = "Lots of movement" if m.motion >= m.loud else "Loud moment"
    best = max((m.score for m in found), default=0.0)
    standing_out = [m for m in found if m.score >= 0.5 * best and m.score > 0]
    return standing_out or found


# ---------- the AI's answer ----------

def from_ai(proposal: HighlightProposal, duration: float) -> list[mo.Moment]:
    """Checked moments from the AI's reply. Anything unreadable, outside the video or scored 0 is dropped."""
    out: list[mo.Moment] = []
    for r in proposal.moments[:60]:
        start, end = mo.parse_clock(r.start), mo.parse_clock(r.end)
        if start is None or end is None or start >= duration:
            continue
        if end <= start:  # "00:07 to 00:07": a flash of an action within one second
            end = start + 1.0
        score = min(10, max(0, int(r.score))) / 10
        if score <= 0:
            continue
        fx = float(r.focus_x)
        out.append(mo.Moment(
            start, min(end, duration), local=0.0, score=score, label=" ".join(str(r.label).split())[:60],
            focus_x=round(min(1.0, max(0.0, fx)), 3) if fx == fx else None,  # fx == fx: not NaN
            framing=r.framing,
        ))
    return out


def _clips(chosen: list[mo.Moment]) -> list[Clip]:
    return [
        Clip(id=f"c{i}", start=round(m.start, 2), end=round(m.end, 2), purpose="hook" if i == 1 else "main_content",
             reason=m.label, focus_x=m.focus_x, framing=m.framing)
        for i, m in enumerate(chosen, 1)
    ]


def _length_notes(chosen: list[mo.Moment], target: int, duration: float) -> list[str]:
    length = sum(m.duration for m in chosen)
    if length < min(target, duration) * 0.6:
        return [f"Only about {length:.0f}s of the footage seemed worth keeping, so the video is shorter than the {target}s you asked for."]
    if length > target * 1.15:
        return [f"It runs about {length:.0f}s, a bit over {target}s, so that no action is cut short."]
    return []


def plan(job: dict[str, Any]) -> None:
    job_id = job["id"]
    s = job["settings_json"]
    duration = float(job["metadata_json"]["duration"])
    target = int(s["target_duration"])
    proposal: HighlightProposal | None = None
    chosen: list[mo.Moment] = []
    reason: str | None = no_key_reason()
    provider = get_provider(job.get("user_id"))
    if provider is not None:
        text = s.get("instructions", "")
        prompt = PROMPT.format(length=_clock(duration), target=target, offer=int(target * 1.6),
                               request=REQUEST_BLOCK.format(text=text) if text else "")
        try:
            proposal = provider.generate_from_video(prompt, HighlightProposal, watch_copy(job))
            chosen = mo.assemble(from_ai(proposal, duration), target, duration)
            reason = None if chosen else "the AI found no moment that fits"
        except AIError as exc:
            log.warning("job %s: highlight AI call failed: %s", job_id, exc)
            reason = str(exc)

    warnings = [s["style_note"]] if s.get("style_note") else []
    watched = bool(chosen)
    if not watched:
        proposal = None
        chosen = mo.assemble(from_signals(job, target), target, duration, max_part=max(10.0, target * 0.6))
        if not chosen:
            raise PipelineError("I couldn't find anything to put in a highlight video.")
        warnings.append("The AI didn't pick the moments, so they were chosen by movement and loudness only.")
    warnings += _length_notes(chosen, target, duration)

    title = clean_hook_text(proposal.hook_text) if proposal else ""
    result = EditingPlan(
        style="highlight",
        source="ai" if watched else "fallback",
        fallback_reason=reason,
        summary=Summary(main_subject=(proposal.main_subject if proposal else "")[:200], main_message=""),
        target_duration=target,
        clips=_clips(chosen),
        reframe=Reframe(strategy="center", focus_x=0.5),
        captions=Captions(enabled=False),
        silence=Silence(remove=False),
        music=Music(enabled=s["background_music"], track=s.get("music_track"), volume=MUSIC_VOLUME),
        hook=Hook(enabled=bool(s.get("hook", True)) and bool(title), text=title, color=proposal.hook_color if proposal else "yellow"),
        instructions=s.get("instructions", ""),
        warnings=warnings,
    )
    visual = job.get("visual_json") or {}
    db.update_job(job_id, plan_json=result.model_dump(), visual_json={**visual, "main_subject": result.summary.main_subject})
    log.info("job %s: highlight plan (%s): %d parts, %.1fs of %ds", job_id, result.source, len(result.clips), result.total_duration, target)


def revise(job: dict[str, Any]) -> None:
    """A chat message about a highlight video: the AI watches again with the request in mind."""
    job_id = job["id"]
    revision = job["revision_json"]
    base = EditingPlan.model_validate(job["plan_json"])
    duration = float(job["metadata_json"]["duration"])
    provider = get_provider(job.get("user_id"))
    if provider is None:
        raise PipelineError(f"Chat edits need the AI service, which can't run: {no_key_reason()}.")
    block = REVISION_BLOCK.format(
        current=", ".join(f"{_clock(c.start)}-{_clock(c.end)} ({c.reason})" for c in base.clips) or "none",
        target=base.target_duration, hook=f'"{base.hook.text}"' if base.hook.enabled else "none",
        earlier=base.instructions.replace('"', "'") or "none", message=revision["message"],
    )
    prompt = PROMPT.format(length=_clock(duration), target=base.target_duration, offer=int(base.target_duration * 1.6), request=block)
    try:
        proposal = provider.generate_from_video(prompt, HighlightRevision, watch_copy(job))
    except AIError as exc:
        raise PipelineError(str(exc)) from exc
    target = max(15, min(90, int(proposal.target_duration)))
    chosen = mo.assemble(from_ai(proposal, duration), target, duration)
    if not chosen:
        raise PipelineError("I couldn't find that in the video. Try describing it differently.")
    new = base.model_copy(deep=True)
    new.clips = _clips(chosen)
    new.target_duration = target
    new.source, new.fallback_reason = "ai", None
    title = clean_hook_text(proposal.hook_text)
    if title:
        new.hook.text, new.hook.color = title, proposal.hook_color
    new.hook.enabled = bool(proposal.hook_enabled) and bool(new.hook.text)
    new.warnings = _length_notes(chosen, target, duration)
    reply = (proposal.reply or "").strip()[:400] or "Done."
    db.update_job(job_id, plan_json=new.model_dump(), revision_json={**revision, "reply": reply})
    log.info("job %s: highlight revised: %d parts, %.1fs", job_id, len(new.clips), new.total_duration)
