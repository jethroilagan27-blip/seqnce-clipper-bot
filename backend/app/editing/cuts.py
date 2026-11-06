"""Turn plan clips into precise source-time cut ranges.

Two jobs: (1) pad clip edges slightly so words aren't clipped, but never into a
neighbouring word; (2) optionally shorten long pauses *inside* a clip down to a
natural beat (we never remove pauses entirely).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from ..plan.schema import EditingPlan

PAD_IN_S = 0.12  # lead-in before the first word of a clip
PAD_OUT_S = 0.22  # tail after the last word of a clip
KEEP_PAUSE_S = 0.35  # a shortened pause keeps this much silence
MIN_PIECE_S = 0.25


@dataclass
class Cut:
    start: float  # source time (s)
    end: float
    out_start: float = 0.0  # position in the output timeline (filled by build_cuts)

    @property
    def duration(self) -> float:
        return self.end - self.start


def flatten_words(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    words = [w for seg in transcript["segments"] for w in seg.get("words", [])]
    words.sort(key=lambda w: w["start"])
    return words


def build_cuts(plan: EditingPlan, words: Sequence[dict[str, Any]], video_duration: float) -> list[Cut]:
    cuts: list[Cut] = []
    for clip in plan.clips:
        inside = [w for w in words if w["end"] > clip.start + 0.02 and w["start"] < clip.end - 0.02]
        if not inside:  # no word timing: use the clip as planned
            cuts.append(Cut(clip.start, min(clip.end, video_duration)))
            continue

        first, last = inside[0], inside[-1]
        prev = next((w for w in reversed(words) if w["end"] <= first["start"]), None)
        nxt = next((w for w in words if w["start"] >= last["end"]), None)

        lo = (prev["end"] + first["start"]) / 2 if prev else 0.0
        hi = (last["end"] + nxt["start"]) / 2 if nxt else video_duration
        start = max(first["start"] - PAD_IN_S, lo, 0.0)
        end = min(last["end"] + PAD_OUT_S, hi, video_duration)

        pieces: list[tuple[float, float]] = []
        piece_start = start
        if plan.silence.remove:
            for a, b in zip(inside, inside[1:]):
                gap = b["start"] - a["end"]
                if gap > plan.silence.max_pause_s:
                    keep = min(KEEP_PAUSE_S, gap)
                    pieces.append((piece_start, a["end"] + keep / 2))
                    piece_start = b["start"] - keep / 2
        pieces.append((piece_start, end))

        for s, e in pieces:
            if e - s >= MIN_PIECE_S:
                cuts.append(Cut(round(s, 3), round(e, 3)))

    # absolute positions in the output
    offset = 0.0
    for c in cuts:
        c.out_start = round(offset, 3)
        offset += c.duration
    return cuts


def total_duration(cuts: Sequence[Cut]) -> float:
    return sum(c.duration for c in cuts)
