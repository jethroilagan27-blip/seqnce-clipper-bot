"""Finding the exciting parts of a video without needing speech. Pure functions on numbers: no files, no AI.

Two signals, measured every quarter second:
- movement: how much the picture changes between small grey frames;
- loudness: how loud the sound is (cheers, hits, music drops).
A sudden jump in the picture that doesn't last is a camera cut, not movement; it is noted and ignored as movement.

From those, candidate moments of a few seconds are proposed (spread over the whole video, so a quiet but important
stretch still gets looked at), and later the best-scoring ones are chosen up to the wanted length.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

import numpy as np

BIN_S = 0.25  # one measurement per quarter second (video is sampled at 4 fps)
CUT_DIFF = 28.0  # mean grey-level change that counts as a possible camera cut
MIN_MOMENT_S = 1.5
GAP_S = 0.4  # candidate moments keep this much distance from each other


@dataclass
class Moment:
    start: float
    end: float
    local: float  # 0..1 from movement + loudness
    motion: float = 0.0
    loud: float = 0.0
    score: float = 0.0  # final score used to choose (local, or mixed with the AI's opinion)
    label: str = ""
    focus_x: float | None = None  # where the action is, left (0) to right (1)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def motion_series(frames: np.ndarray) -> tuple[np.ndarray, list[float]]:
    """frames: (n, height, width) grey values. Returns (movement per bin, camera-cut times in seconds)."""
    n = len(frames)
    if n < 2:
        return np.zeros(n, dtype=np.float32), []
    diff = np.abs(np.diff(frames.astype(np.int16), axis=0)).mean(axis=(1, 2)).astype(np.float32)
    diff = np.concatenate([diff[:1], diff])  # same length as frames; diff[i] = change arriving at frame i
    cuts: list[float] = []
    cleaned = diff.copy()
    for i in range(1, n):
        around = np.concatenate([diff[max(0, i - 4):i], diff[i + 1:i + 5]])
        usual = float(np.median(around)) if len(around) else 0.0
        if diff[i] >= CUT_DIFF and diff[i] > 3 * usual + 5:
            cuts.append(round(i * BIN_S, 2))
            cleaned[i] = usual
    if len(cuts) and cleaned.size:
        cleaned[0] = cleaned[1] if n > 1 else 0.0
    return cleaned, cuts


def loudness_series(samples: np.ndarray, rate: int, bins: int) -> np.ndarray:
    """Loudness (RMS) per bin, `bins` long (padded with silence)."""
    out = np.zeros(bins, dtype=np.float32)
    step = int(rate * BIN_S)
    for i in range(min(bins, len(samples) // step if step else 0)):
        chunk = samples[i * step:(i + 1) * step]
        out[i] = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float32))))
    return out


def normalise(x: np.ndarray) -> np.ndarray:
    """Robust 0..1: relative to what is usual in THIS video. A flat signal says nothing (all zero)."""
    if x.size == 0:
        return x.astype(np.float32)
    lo, hi = np.percentile(x, 10), np.percentile(x, 97)
    if hi - lo < 1e-4 * max(1.0, abs(hi)):
        return np.zeros_like(x, dtype=np.float32)
    return np.clip((x - lo) / (hi - lo), 0, 1).astype(np.float32)


def clip_length(target: float) -> float:
    return float(min(3.5, max(2.0, target / 10)))


def _overlaps(a_start: float, a_end: float, taken: Sequence[Moment], gap: float) -> bool:
    return any(a_start < m.end + gap and a_end > m.start - gap for m in taken)


def _snap_to_cuts(start: float, end: float, cuts: Sequence[float]) -> tuple[float, float]:
    """Don't let a moment straddle a camera cut if the longer side is long enough on its own."""
    for c in cuts:
        if start + 0.2 < c < end - 0.2:
            before, after = c - start, end - c
            if before >= after and before >= MIN_MOMENT_S:
                end = c
            elif after > before and after >= MIN_MOMENT_S:
                start = c
    return start, end


def candidates(motion: np.ndarray, loud: np.ndarray | None, duration: float, cuts: Sequence[float], target: float) -> list[Moment]:
    """Up to ~40 non-overlapping moments worth looking at, in time order."""
    length = clip_length(target)
    wanted = int(min(40, max(24, np.ceil(target / length) * 2)))
    m = normalise(motion)
    a = normalise(loud) if loud is not None else None
    bins = len(m)
    if a is not None:
        a = np.resize(a, bins) if len(a) >= bins else np.concatenate([a, np.zeros(bins - len(a), dtype=np.float32)])
    combined = m if a is None or not a.any() else (0.55 * m + 0.45 * a if m.any() else a)

    def window(start: float, end: float) -> Moment:
        i, j = int(start / BIN_S), max(int(start / BIN_S) + 1, int(end / BIN_S))
        part = lambda s: float(s[i:j].mean()) if s is not None and len(s[i:j]) else 0.0  # noqa: E731
        # the average matters, but so does a single peak (a hit, a goal) inside the window
        peak = float(combined[i:j].max()) if len(combined[i:j]) else 0.0
        return Moment(round(start, 2), round(end, 2), round(0.7 * part(combined) + 0.3 * peak, 4), round(part(m), 4), round(part(a), 4))

    if duration <= length * 1.5:
        return [window(0.0, round(duration, 2))]
    # A video that is barely longer than the wanted result: look at all of it, in consecutive pieces.
    if duration <= target * 1.25:
        count = max(1, int(duration // length))
        step = duration / count
        return [window(k * step, min(duration, (k + 1) * step)) for k in range(count)]

    starts = np.arange(0.0, duration - length + 1e-6, BIN_S * 2)
    scored = [window(float(s), float(s) + length) for s in starts]
    chosen: list[Moment] = []

    def take(pool: Sequence[Moment]) -> None:
        for cand in sorted(pool, key=lambda c: -c.local):
            s, e = _snap_to_cuts(cand.start, cand.end, cuts)
            if not _overlaps(s, e, chosen, GAP_S):
                chosen.append(window(s, e))
                return

    sections = int(min(10, wanted // 2, max(1, duration // (length * 2))))
    span = duration / sections
    for k in range(sections):  # the best of every stretch of the video
        take([c for c in scored if k * span <= (c.start + c.end) / 2 < (k + 1) * span])
    while len(chosen) < wanted:  # then the best of what is left
        before = len(chosen)
        take([c for c in scored if not _overlaps(c.start, c.end, chosen, GAP_S)])
        if len(chosen) == before:
            break
    return sorted(chosen, key=lambda c: c.start)


def choose(moments: Sequence[Moment], target: float, duration: float) -> list[Moment]:
    """The best-scoring moments that add up to about `target` seconds, returned in the order they happen."""
    picked: list[Moment] = []
    total = 0.0
    for m in sorted(moments, key=lambda c: (-c.score, c.start)):
        if total >= target - 0.75:
            break
        if total + m.duration > target * 1.15 and picked:
            continue
        if _overlaps(m.start, m.end, picked, 0.0):
            continue
        picked.append(m)
        total += m.duration
    return sorted(picked, key=lambda c: c.start)
