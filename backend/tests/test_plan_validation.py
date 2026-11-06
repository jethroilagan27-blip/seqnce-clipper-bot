from __future__ import annotations

import math
from dataclasses import dataclass

import pytest

from app.plan.validate import PlanValidationError, fallback_clips, repair_and_validate


@dataclass
class P:  # stands in for ProposedClip
    start: float
    end: float
    purpose: str = "main_content"
    reason: str = "r"


# 100 s video, a sentence every 5 s: [0-5], [5-10], ...
SEGS = [{"start": float(i), "end": float(i + 5), "text": f"This is sentence number {i} here"} for i in range(0, 100, 5)]
DUR = 100.0


def run(clips, target=30.0, segs=SEGS, dur=DUR):
    return repair_and_validate(clips, dur, segs, target)


def test_valid_plan_passes_unchanged():
    clips, warns = run([P(0, 10, "hook"), P(40, 55), P(90, 100, "conclusion")], target=30)
    assert [(c.start, c.end) for c in clips] == [(0, 10), (40, 55), (90, 100)]
    assert [c.id for c in clips] == ["c1", "c2", "c3"]
    assert warns == []


def test_clamps_to_video_bounds():
    clips, warns = run([P(-5, 12), P(95, 130)], target=20)
    assert clips[0].start == 0 and clips[-1].end == 100
    assert any("clamped" in w for w in warns)


def test_drops_invalid_ranges():
    clips, warns = run([P(20, 10), P(math.nan, 5), P(float("inf"), 90), P(200, 210), P(30, 45)], target=15)
    assert [(c.start, c.end) for c in clips] == [(30, 45)]
    assert len([w for w in warns if "dropped" in w]) == 4


def test_drops_too_short_clips():
    clips, _ = run([P(10, 10.8), P(30, 45)], target=15)
    assert len(clips) == 1 and clips[0].start == 30


def test_snaps_edges_to_sentence_boundaries():
    clips, _ = run([P(10.4, 24.7)], target=15)
    assert (clips[0].start, clips[0].end) == (10.0, 25.0)


def test_does_not_snap_when_far_from_a_boundary():
    segs = [{"start": 0.0, "end": 30.0, "text": "one very long sentence indeed here"}]
    clips, _ = repair_and_validate([P(10.0, 20.0)], 30.0, segs, 10.0)
    assert (clips[0].start, clips[0].end) == (10.0, 20.0)


def test_sorts_chronologically_and_merges_duplicates_and_overlaps():
    clips, warns = run([P(50, 65, "example"), P(10, 25, "hook"), P(10, 25, "hook"), P(20, 35, "conclusion")], target=45)
    assert [(c.start, c.end) for c in clips] == [(10, 35), (50, 65)]
    assert clips[0].purpose in ("hook", "conclusion")  # higher-priority purpose kept
    assert any("merged" in w for w in warns)


def test_adjacent_clips_are_merged():
    clips, _ = run([P(10, 20), P(20.2, 30)], target=20)
    assert len(clips) == 1 and (clips[0].start, clips[0].end) == (10, 30)


def test_trims_over_budget_by_dropping_least_important_first():
    plan = [P(0, 20, "hook"), P(30, 50, "example"), P(60, 80, "main_content"), P(85, 100, "conclusion")]
    clips, warns = run(plan, target=40)  # limit = 50 s; 75 s proposed
    purposes = [c.purpose for c in clips]
    assert "example" not in purposes and "hook" in purposes and "conclusion" in purposes
    assert sum(c.end - c.start for c in clips) <= 50 + 1e-6
    assert any("dropped" in w for w in warns)


def test_single_overlong_clip_is_trimmed_at_a_sentence_end():
    clips, warns = run([P(0, 90)], target=20)  # limit 25 s
    assert clips[0].end == 25.0 and clips[0].start == 0.0
    assert any("trimmed" in w for w in warns)


def test_too_short_total_is_rejected_with_feedback():
    with pytest.raises(PlanValidationError) as ei:
        run([P(10, 15)], target=45)  # 5 s vs min 27 s
    assert "too short" in ei.value.errors[0]


def test_no_usable_clips_is_rejected():
    with pytest.raises(PlanValidationError) as ei:
        run([P(50, 40), P(500, 600)], target=30)
    assert "no usable clips" in ei.value.errors[0]


def test_short_video_below_target_is_accepted_if_mostly_used():
    segs = [{"start": 0.0, "end": 20.0, "text": "a short video with some words in it"}]
    clips, _ = repair_and_validate([P(0, 20)], 20.0, segs, 45.0)  # min = min(27, 12) = 12
    assert clips[0].end == 20.0


def test_output_times_are_always_inside_video_and_ordered():
    import random

    rnd = random.Random(7)
    for _ in range(300):
        props = [P(rnd.uniform(-20, 130), rnd.uniform(-20, 130), rnd.choice(["hook", "example", "conclusion", "main_content"])) for _ in range(rnd.randint(0, 6))]
        try:
            clips, _ = run(props, target=rnd.choice([15, 30, 60]))
        except PlanValidationError:
            continue
        assert clips
        for a, b in zip(clips, clips[1:]):
            assert a.end < b.start  # sorted, no overlap
        for c in clips:
            assert 0 <= c.start < c.end <= DUR
            assert c.end - c.start >= 1.5


def test_fallback_uses_opening_and_closing_of_long_videos():
    clips, _ = fallback_clips(SEGS, DUR, 30)
    assert clips[0].start == 0
    assert clips[-1].end == 100 and len(clips) == 2
    assert sum(c.end - c.start for c in clips) <= 30 * 1.25


def test_fallback_on_short_video_is_single_clip():
    segs = SEGS[:4]  # 20 s
    clips, _ = fallback_clips(segs, 20.0, 45)
    assert len(clips) == 1 and clips[0].start == 0
