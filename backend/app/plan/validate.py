"""Turn untrusted AI clip suggestions into a safe, consistent clip list.

Philosophy: *repair* what is mechanically fixable (clamp, snap to sentence
boundaries, sort, merge duplicates, trim to length) and *reject* what is
semantically wrong (nothing usable, far too short) so the planner can ask the
AI again with the error messages.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from ..errors import PipelineError
from .schema import Clip

MIN_CLIP_S = 1.5  # shorter clips are dropped as unusable
SNAP_S = 1.0  # snap a clip edge to a sentence boundary if one is this close
MERGE_GAP_S = 0.3  # clips closer than this are merged (also removes overlaps/duplicates)
MIN_RATIO = 0.6  # accepted total length, as a fraction of target...
MAX_RATIO = 1.25  # ...and above (the max is enforced by trimming)

PRIORITY = {"hook": 3, "conclusion": 3, "main_content": 2, "example": 1}


class PlanValidationError(PipelineError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("The AI's editing plan was not usable: " + "; ".join(errors))


def _nearest(value: float, candidates: Sequence[float], tolerance: float) -> float:
    best = min(candidates, key=lambda c: abs(c - value), default=None)
    return best if best is not None and abs(best - value) <= tolerance else value


def _total(clips: list[dict[str, Any]]) -> float:
    return sum(c["end"] - c["start"] for c in clips)


def repair_and_validate(
    proposed: Sequence[Any],
    video_duration: float,
    segments: Sequence[dict[str, Any]],
    target: float,
) -> tuple[list[Clip], list[str]]:
    """Return (clips, warnings) or raise PlanValidationError.

    `proposed` items need .start .end .purpose .reason (e.g. ProposedClip).
    `segments` are transcript segments with 'start'/'end'.
    """
    warnings: list[str] = []
    seg_starts = [float(s["start"]) for s in segments]
    seg_ends = [float(s["end"]) for s in segments]

    # 1-3: sanity, clamp, snap to sentence boundaries
    clips: list[dict[str, Any]] = []
    for i, p in enumerate(proposed, 1):
        try:
            start, end = float(p.start), float(p.end)
        except (TypeError, ValueError):
            warnings.append(f"clip {i}: non-numeric times, dropped")
            continue
        if not (math.isfinite(start) and math.isfinite(end)) or end <= start:
            warnings.append(f"clip {i}: invalid range {start}-{end}, dropped")
            continue
        if start >= video_duration:
            warnings.append(f"clip {i}: starts after the end of the video, dropped")
            continue
        clamped_start, clamped_end = max(0.0, start), min(video_duration, end)
        if (clamped_start, clamped_end) != (start, end):
            warnings.append(f"clip {i}: clamped to the video length")
        start, end = clamped_start, clamped_end
        start = _nearest(start, seg_starts, SNAP_S)
        end = _nearest(end, seg_ends, SNAP_S)
        if end - start < MIN_CLIP_S:
            warnings.append(f"clip {i}: shorter than {MIN_CLIP_S}s, dropped")
            continue
        clips.append({"start": start, "end": end, "purpose": p.purpose, "reason": (p.reason or "")[:200]})

    # 4: chronological order, merge overlaps/duplicates/near-touching clips
    clips.sort(key=lambda c: (c["start"], c["end"]))
    merged: list[dict[str, Any]] = []
    for c in clips:
        if merged and c["start"] - merged[-1]["end"] <= MERGE_GAP_S:
            prev = merged[-1]
            prev["end"] = max(prev["end"], c["end"])
            if PRIORITY[c["purpose"]] > PRIORITY[prev["purpose"]]:
                prev["purpose"] = c["purpose"]
            warnings.append("merged overlapping/adjacent clips")
        else:
            merged.append(dict(c))
    clips = merged

    # 5: trim down to the maximum accepted length
    limit = target * MAX_RATIO
    while clips and _total(clips) > limit:
        if len(clips) > 1:
            victim = min(clips, key=lambda c: (PRIORITY[c["purpose"]], c["end"] - c["start"]))
            clips.remove(victim)
            warnings.append(f"dropped a '{victim['purpose']}' clip to fit the target length")
        else:
            only = clips[0]
            wanted_end = only["start"] + limit
            inside = [e for e in seg_ends if only["start"] + MIN_CLIP_S < e <= wanted_end]
            only["end"] = max(inside) if inside else wanted_end
            warnings.append("trimmed the only clip to fit the target length")
            break

    # 6: final checks that need the AI to try again
    errors: list[str] = []
    if not clips:
        errors.append("no usable clips remained after validation")
    else:
        min_total = min(target * MIN_RATIO, video_duration * 0.6)
        if _total(clips) < min_total:
            errors.append(
                f"total length {_total(clips):.0f}s is too short; aim for about {target:.0f}s"
            )
    if errors:
        raise PlanValidationError(errors)

    result = [
        Clip(id=f"c{i}", start=round(c["start"], 2), end=round(c["end"], 2),
             purpose=c["purpose"], reason=c["reason"])
        for i, c in enumerate(clips, 1)
    ]
    return result, list(dict.fromkeys(warnings))  # de-duplicated, order kept


MIN_MANUAL_CLIP_S = 1.0
MAX_MANUAL_TOTAL_S = 180.0  # 3 minutes: the longest short we let a hand edit produce
MAX_CLIPS = 30


def validate_manual_clips(proposed: Sequence[Any], video_duration: float) -> list[Clip]:
    """Hand-made clip list (from the timeline editor). Unlike the AI path nothing is snapped or
    trimmed to a target length: the user's exact positions are kept, only made safe.

    Raises PlanValidationError (user-safe messages) when the list can't be used."""
    errors: list[str] = []
    items: list[dict[str, Any]] = []
    for i, p in enumerate(proposed, 1):
        try:
            start, end = float(p.start), float(p.end)
        except (TypeError, ValueError):
            errors.append(f"clip {i} has invalid times")
            continue
        if not (math.isfinite(start) and math.isfinite(end)):
            errors.append(f"clip {i} has invalid times")
            continue
        start, end = max(0.0, start), min(video_duration, end)
        if end - start < MIN_MANUAL_CLIP_S:
            errors.append(f"clip {i} is shorter than {MIN_MANUAL_CLIP_S:g}s")
            continue
        items.append({"start": start, "end": end, "purpose": p.purpose, "reason": (p.reason or "")[:200]})
    if len(proposed) > MAX_CLIPS:
        errors.append(f"too many clips (max {MAX_CLIPS})")
    if errors:
        raise PlanValidationError(errors)
    if not items:
        raise PlanValidationError(["at least one clip has to stay in the video"])

    items.sort(key=lambda c: (c["start"], c["end"]))
    merged: list[dict[str, Any]] = []
    for c in items:
        if merged and c["start"] <= merged[-1]["end"] + 0.05:  # overlapping or touching
            merged[-1]["end"] = max(merged[-1]["end"], c["end"])
        else:
            merged.append(dict(c))
    total = _total(merged)
    if total > MAX_MANUAL_TOTAL_S:
        raise PlanValidationError([f"the video would be {total:.0f}s long; the maximum is {MAX_MANUAL_TOTAL_S:.0f}s"])
    return [
        Clip(id=f"c{i}", start=round(c["start"], 3), end=round(c["end"], 3), purpose=c["purpose"], reason=c["reason"])
        for i, c in enumerate(merged, 1)
    ]


_FILLERS = {"um", "uh", "hmm", "so", "okay", "ok", "yeah", "well"}


def _is_filler(text: str) -> bool:
    words = [w.strip(".,!?").lower() for w in text.split()]
    return len(words) < 3 or all(w in _FILLERS for w in words[:2]) and len(words) < 6


def fallback_clips(
    segments: Sequence[dict[str, Any]], video_duration: float, target: float
) -> tuple[list[Clip], list[str]]:
    """Deterministic plan with no AI: the opening of the video plus, when the
    video is much longer than the target, its closing. Skips filler sentences."""
    usable = [s for s in segments if not _is_filler(s["text"])] or list(segments)

    head_budget = target * (0.7 if video_duration > target * 1.5 else 1.0)
    head, used = [], 0.0
    for s in usable:
        length = s["end"] - s["start"]
        if used + length > head_budget and head:
            break
        head.append(s)
        used += length

    tail: list[dict[str, Any]] = []
    if video_duration > target * 1.5:
        tail_budget, used_tail = target * 0.3, 0.0
        for s in reversed(usable):
            length = s["end"] - s["start"]
            if s["start"] <= head[-1]["end"] or (used_tail + length > tail_budget and tail):
                break
            tail.insert(0, s)
            used_tail += length

    class _P:  # tiny stand-in matching the ProposedClip attributes
        def __init__(self, start: float, end: float, purpose: str, reason: str) -> None:
            self.start, self.end, self.purpose, self.reason = start, end, purpose, reason

    proposals = [_P(head[0]["start"], head[-1]["end"], "hook", "Opening of the video")]
    if tail:
        proposals.append(_P(tail[0]["start"], tail[-1]["end"], "conclusion", "Closing of the video"))
    return repair_and_validate(proposals, video_duration, segments, target)
