"""Stage 4 - build the validated editing plan.

Flow:  AI proposes clips  ->  Python repairs/validates  ->  (on failure) ask the
AI once more with the errors  ->  (still failing / no AI) deterministic fallback.
The AI never sees or sets anything except which parts of the transcript to keep.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import db
from ..ai import AIError, get_provider
from ..errors import PipelineError
from ..ai.schemas import PlanProposal
from ..plan.schema import Captions, EditingPlan, Music, Reframe, Silence, Summary
from ..plan.validate import PlanValidationError, fallback_clips, repair_and_validate
from .transcribe import load_transcript

log = logging.getLogger(__name__)

PROMPT = """You are an expert short-form video editor (TikTok / Reels / Shorts) editing a talking-head video.
Choose which parts of the transcript to KEEP so the final video is about {target}s long.

Video length: {duration:.0f}s. Spoken language: {language}.
Visual context: {visual}

Transcript, one line per segment as [start-end] text (seconds):
{transcript}

Rules:
- Return 1 to 5 clips. Every clip start/end MUST be copied from the segment timestamps above, so clips begin and end on full sentences.
- Total kept time should be close to {target}s (between {low:.0f}s and {high:.0f}s).
- Keep clips in chronological order and do not overlap them.
- Prioritise meaningful content over simply being short: a strong opening statement (hook), the key explanation(s), and a strong concluding statement.
- Cut repetition, rambling, false starts and filler ("um", "let me think"). Do NOT cut natural pauses between sentences inside a kept clip; they are handled later.
- purpose must be one of: hook, main_content, example, conclusion.
- reason: one short sentence on why the clip is worth keeping.
- main_subject and main_message: what the video is about and its one-sentence takeaway.
{feedback}"""


def format_transcript(segments: list[dict[str, Any]]) -> str:
    return "\n".join(f"[{s['start']:.2f}-{s['end']:.2f}] {s['text']}" for s in segments)


def build_plan(job: dict[str, Any], clips, warnings, source, reason, proposal: PlanProposal | None) -> EditingPlan:
    s = job["settings_json"]
    visual = job.get("visual_json") or {}
    focus = float(visual.get("speaker_focus_x", 0.5))
    use_focus = visual.get("analysis_source") == "ai"
    return EditingPlan(
        source=source,
        fallback_reason=reason,
        summary=Summary(
            main_subject=(proposal.main_subject if proposal else visual.get("main_subject", ""))[:200],
            main_message=(proposal.main_message if proposal else "")[:300],
        ),
        target_duration=s["target_duration"],
        clips=clips,
        reframe=Reframe(strategy="focus" if use_focus else "center", focus_x=focus if use_focus else 0.5),
        captions=Captions(enabled=s["captions"]),
        silence=Silence(remove=s["remove_silence"]),
        music=Music(enabled=s["background_music"], track=s.get("music_track")),
        warnings=warnings,
    )


def run(job: dict[str, Any]) -> None:
    job_id = job["id"]
    meta = job["metadata_json"]
    duration = float(meta["duration"])
    target = float(job["settings_json"]["target_duration"])
    transcript = load_transcript(job)
    segments = transcript["segments"]
    visual = job.get("visual_json") or {}

    plan: EditingPlan | None = None
    fallback_reason = "no API key configured"
    provider = get_provider()

    if provider is not None:
        visual_text = (
            f"{visual.get('main_subject', 'unknown')}, framing {visual.get('framing', 'unknown')}"
            if visual.get("analysis_source") == "ai"
            else "not available"
        )
        feedback = ""
        for attempt in (1, 2):  # attempt 2 = regeneration with validation errors
            prompt = PROMPT.format(
                target=int(target), low=target * 0.6, high=target * 1.25, duration=duration,
                language=transcript.get("language", "unknown"), visual=visual_text,
                transcript=format_transcript(segments), feedback=feedback,
            )
            try:
                proposal = provider.generate_structured(prompt, PlanProposal)
                clips, warnings = repair_and_validate(proposal.clips, duration, segments, target)
                plan = build_plan(job, clips, warnings, "ai", None, proposal)
                break
            except PlanValidationError as exc:
                log.warning("job %s: plan attempt %d invalid: %s", job_id, attempt, exc.errors)
                fallback_reason = "; ".join(exc.errors)
                feedback = "\nYour previous answer was rejected: " + "; ".join(exc.errors) + ". Fix this."
            except AIError as exc:
                log.warning("job %s: planning AI call failed: %s", job_id, exc)
                fallback_reason = str(exc)
                break

    if plan is None:
        log.warning("job %s: using fallback plan (%s)", job_id, fallback_reason)
        try:
            clips, warnings = fallback_clips(segments, duration, target)
        except PlanValidationError as exc:
            raise PipelineError(
                "There isn't enough speech in this video to build a short from it."
            ) from exc
        plan = build_plan(job, clips, warnings, "fallback", fallback_reason, None)

    db.update_job(job_id, plan_json=plan.model_dump())
    log.info(
        "job %s: plan ready (%s) %d clips, %.1fs of %.0fs target",
        job_id, plan.source, len(plan.clips), plan.total_duration, target,
    )
