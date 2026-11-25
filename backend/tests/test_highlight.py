"""Highlight videos: the best moments, with or without any talking."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.ai import AIError
from app.ai.schemas import HighlightProposal, HighlightRevision, RankedMoment
from app.config import get_settings
from app.editing import moments as mo
from app.editing.cuts import Cut
from app.editing.ffgraph import build_filtergraph, compute_crop
from app.pipeline import highlight
from app.pipeline.prepare import job_temp_dir

# ---------- finding moments (pure) ----------

def _video(seconds: float, busy: list[tuple[float, float]], cut_at: float | None = None) -> np.ndarray:
    """Grey frames at 4 fps: still, except noisy movement in the `busy` stretches and one hard cut."""
    rng = np.random.default_rng(1)
    frames = np.full((int(seconds * 4), 36, 64), 60, dtype=np.uint8)
    for a, b in busy:
        for i in range(int(a * 4), int(b * 4)):
            frames[i] = np.clip(60 + rng.integers(-18, 19, (36, 64)), 0, 255)
    if cut_at is not None:
        frames[int(cut_at * 4):] = np.clip(frames[int(cut_at * 4):].astype(int) + 120, 0, 255)
    return frames


def test_a_camera_cut_is_noticed_and_not_counted_as_movement():
    motion, cuts = mo.motion_series(_video(20, [], cut_at=10))
    assert cuts == [10.0]
    assert motion.max() < 5  # nothing actually moves


def test_movement_and_loud_sound_stand_out():
    motion, _ = mo.motion_series(_video(60, [(20, 28)]))
    assert motion[int(24 * 4)] > 10 > motion[int(5 * 4)]
    sound = np.zeros(16000 * 60, dtype=np.float32)
    sound[16000 * 40:16000 * 43] = 0.8
    loud = mo.loudness_series(sound, 16000, len(motion))
    assert loud[int(41 * 4)] > 0.7 and loud[int(5 * 4)] == 0
    found = mo.candidates(motion, loud, 60, [], target=15)
    best = sorted(found, key=lambda m: -m.local)[:5]
    assert any(20 <= m.start < 28 for m in best) and any(38 <= m.start < 43 for m in best)


def test_candidates_cover_the_whole_video_without_overlapping():
    motion, _ = mo.motion_series(_video(600, [(100, 110)]))
    found = mo.candidates(motion, None, 600, [], target=45)
    assert 20 <= len(found) <= 40
    assert all(a.end <= b.start + 1e-6 for a, b in zip(found, found[1:]))
    assert found[0].start < 120 and found[-1].end > 480  # quiet parts get looked at too
    assert all(mo.MIN_MOMENT_S <= m.duration <= 3.6 for m in found)


def test_a_flat_or_tiny_video_still_gives_moments():
    flat = np.zeros((40, 36, 64), dtype=np.uint8)  # 10 s of black
    motion, cuts = mo.motion_series(flat)
    assert cuts == [] and not mo.normalise(motion).any()
    assert mo.candidates(motion, None, 10, [], target=45)
    assert len(mo.candidates(motion[:8], None, 2.0, [], target=45)) == 1


def test_a_moment_does_not_straddle_a_camera_cut():
    assert mo._snap_to_cuts(10.0, 13.5, [12.5]) == (10.0, 12.5)
    assert mo._snap_to_cuts(10.0, 13.5, [10.8]) == (10.8, 13.5)
    assert mo._snap_to_cuts(10.0, 12.0, [11.0]) == (10.0, 12.0)  # neither side is long enough alone


def test_choosing_takes_the_best_up_to_the_wanted_length_in_time_order():
    pool = [mo.Moment(i * 5, i * 5 + 3, 0, score=s) for i, s in enumerate([0.1, 0.9, 0.2, 0.8, 0.7, 0.95, 0.3])]
    chosen = mo.choose(pool, target=9, duration=40)
    assert [m.start for m in chosen] == [5, 15, 25]  # the three best, as they happen
    assert sum(m.duration for m in mo.choose(pool, target=60, duration=40)) == 21  # everything there is


# ---------- the AI's opinion ----------

def _moments(n: int) -> list[mo.Moment]:
    return [mo.Moment(i * 5.0, i * 5.0 + 3, local=0.5, motion=0.6, loud=0.1) for i in range(n)]


def test_the_ai_opinion_is_clamped_and_unknown_ids_ignored():
    proposal = HighlightProposal(
        main_subject="x", hook_text="t", hook_color="red",
        moments=[RankedMoment(id=1, score=999, label="  big    jump ", focus_x=7),
                 RankedMoment(id=2, score=0, label="blur", focus_x=0.5),
                 RankedMoment(id=99, score=10, label="ghost", focus_x=0.5)],
    )
    ranked = highlight.rank(_moments(3), proposal)
    assert ranked[0].score <= 1 and ranked[0].focus_x == 1.0 and ranked[0].label == "big jump"
    assert ranked[1].score == 0  # the AI said it's no good
    assert 0 < ranked[2].score < ranked[0].score and ranked[2].focus_x is None  # skipped by the AI


def test_without_an_ai_the_signals_decide():
    ranked = highlight.rank(_moments(2), None)
    assert [m.score for m in ranked] == [0.5, 0.5] and ranked[0].label


# ---------- the filter graph ----------

def test_each_piece_can_have_its_own_crop_and_silence_replaces_missing_sound():
    cuts = [Cut(0, 2, 0.0, 0.0), Cut(3, 5, 2.0, 1.0)]
    crops = [compute_crop(1920, 1080, 0.0), compute_crop(1920, 1080, 1.0)]
    g = build_filtergraph(cuts, crops[0], captions=False, music=False, music_volume=0.3, total=4, crops=crops, has_audio=False)
    assert "crop=606:1080:0:0[v0]" in g and f"crop=606:1080:{crops[1].x}:0[v1]" in g and crops[1].x > 1000
    assert g.count("anullsrc") == 2 and "[0:a]" not in g
    assert "[vcat]scale=1080:1920" in g
    with pytest.raises(ValueError):
        build_filtergraph(cuts, crops[0], captions=False, music=False, music_volume=0.3, total=4, crops=crops[:1])


# ---------- the whole pipeline, with real FFmpeg ----------

@pytest.fixture
def match_video(tmp_path: Path) -> Path:
    """60 quiet, still seconds with two loud, busy stretches: 20-28 s and 44-52 s."""
    out = tmp_path / "match.mp4"
    busy = "between(t,20,28)+between(t,44,52)"
    subprocess.run(
        [get_settings().ffmpeg, "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=0x224466:s=640x360:r=25:d=60",
         "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=60",
         "-f", "lavfi", "-i", "sine=frequency=700:sample_rate=44100:duration=60",
         "-filter_complex", f"[0:v][1:v]overlay=enable='{busy}'[v];[2:a]volume='if({busy},1,0.02)':eval=frame[a]",
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "60", str(out)],
        check=True,
    )
    return out


def _upload(c: TestClient, path: Path, **form) -> str:
    with path.open("rb") as f:
        r = c.post("/api/videos/upload", files={"file": (path.name, f, "video/mp4")}, data=form)
    assert r.status_code == 201, r.text
    return r.json()["job_id"]


def _wait(c: TestClient, job_id: str, version: int | None = None) -> dict:
    for _ in range(600):
        job = c.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed") and not job["revising"] and (version is None or job["current_version"] == version or job["error"]):
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def _in_busy(clip: dict) -> float:
    return sum(max(0.0, min(clip["end"], b) - max(clip["start"], a)) for a, b in ((20, 28), (44, 52)))


def test_a_highlight_picks_the_busy_loud_parts_without_any_ai_or_speech(client: TestClient, match_video: Path):
    job_id = _upload(client, match_video, style="highlight", target_duration="15")
    job = _wait(client, job_id)
    assert job["status"] == "completed", job["error"]
    result = client.get(f"/api/jobs/{job_id}/result").json()
    plan = result["plan"]
    assert plan["style"] == "highlight" and plan["source"] == "fallback" and plan["captions"]["enabled"] is False
    assert 12 <= result["rendered"]["duration"] <= 18.5
    assert (result["rendered"]["width"], result["rendered"]["height"]) == (1080, 1920)
    busy = sum(_in_busy(c) for c in plan["clips"])
    assert busy >= 0.7 * sum(c["end"] - c["start"] for c in plan["clips"]), plan["clips"]
    assert any("movement and loudness only" in w for w in plan["warnings"])
    # the editor pages work without any words
    assert client.post(f"/api/jobs/{job_id}/timeline", json={}).json()["pages"] == []
    assert client.get(f"/api/jobs/{job_id}/analysis").json()["transcript"]["segments"] == []


class FakeHighlightAI:
    """Loves moments in `favourite` seconds, hates the rest, and says the action is on the right."""

    def __init__(self, favourite: tuple[float, float]):
        self.favourite = favourite
        self.calls: list[dict] = []
        self.target = 15
        self.fail: str | None = None

    def generate_structured(self, prompt, response_model, images=None):
        self.calls.append({"prompt": prompt, "model": response_model.__name__, "images": len(images or [])})
        if self.fail:
            raise AIError(self.fail)
        ranked = []
        for i, img in enumerate(images, 1):
            start = float(img.label.split("(")[1].split("s")[0])
            good = self.favourite[0] - 1 <= start < self.favourite[1]
            ranked.append(RankedMoment(id=i, score=10 if good else 1, label="great play" if good else "waiting", focus_x=0.9))
        common = dict(main_subject="a match", moments=ranked, hook_text="What a finish", hook_color="cyan")
        if response_model is HighlightRevision:
            return HighlightRevision(**common, reply="Now it shows the second half.", target_duration=self.target, hook_enabled=False)
        return HighlightProposal(**common)


@pytest.fixture
def ai(monkeypatch: pytest.MonkeyPatch):
    fake = FakeHighlightAI((44, 52))
    monkeypatch.setattr("app.pipeline.highlight.get_provider", lambda *a, **k: fake)
    return fake


def test_the_ai_chooses_and_the_crop_follows_it_then_chat_changes_it(client: TestClient, ai: FakeHighlightAI, match_video: Path):
    job_id = _upload(client, match_video, style="highlight", target_duration="15", instructions="the second goal")
    job = _wait(client, job_id)
    assert job["status"] == "completed", job["error"]
    [call] = ai.calls  # ONE AI request for the whole highlight
    assert call["model"] == "HighlightProposal" and call["images"] >= 10 and "the second goal" in call["prompt"]
    plan = client.get(f"/api/jobs/{job_id}/result").json()["plan"]
    assert plan["source"] == "ai" and plan["hook"]["text"] == "What a finish" and plan["hook"]["enabled"]
    assert all(c["focus_x"] == 0.9 for c in plan["clips"])
    assert sum(1 for c in plan["clips"] if 43 <= c["start"] < 52) >= 2 and plan["clips"][0]["purpose"] == "hook"
    cuts = json.loads((job_temp_dir(job_id) / "cuts.json").read_text())["cuts"]
    assert all(c["focus_x"] == 0.9 for c in cuts)
    assert "crop=202:360:" in (job_temp_dir(job_id) / "filter.txt").read_text().split("[v0]")[0]  # per-piece crop

    ai.favourite, ai.target = (20, 28), 20
    assert client.post(f"/api/jobs/{job_id}/revisions", json={"message": "show the first goal instead"}).status_code == 202
    job = _wait(client, job_id, version=2)
    assert job["status"] == "completed" and job["current_version"] == 2, job["error"]
    assert ai.calls[-1]["model"] == "HighlightRevision" and "show the first goal instead" in ai.calls[-1]["prompt"]
    v2 = client.get(f"/api/jobs/{job_id}/versions").json()["versions"][-1]
    assert v2["reply"] == "Now it shows the second half." and v2["plan"]["target_duration"] == 20 and v2["plan"]["hook"]["enabled"] is False
    assert sum(1 for c in v2["plan"]["clips"] if 19 <= c["start"] < 28) >= 2


def test_a_hand_trim_keeps_the_crop_position(client: TestClient, ai: FakeHighlightAI, match_video: Path):
    job_id = _upload(client, match_video, style="highlight", target_duration="15")
    _wait(client, job_id)
    clips = client.get(f"/api/jobs/{job_id}/result").json()["plan"]["clips"]
    first = clips[0]
    edit = {"clips": [{"start": first["start"] + 0.3, "end": first["end"] + 0.5, "purpose": "hook"}]}
    spec = client.post(f"/api/jobs/{job_id}/timeline", json={"edit": edit}).json()
    assert spec["cuts"][0]["focus_x"] == 0.9


def test_when_the_ai_fails_the_highlight_is_still_made(client: TestClient, ai: FakeHighlightAI, match_video: Path):
    ai.fail = "The AI service is rate-limited right now."
    job_id = _upload(client, match_video, style="highlight", target_duration="15")
    job = _wait(client, job_id)
    assert job["status"] == "completed", job["error"]
    plan = client.get(f"/api/jobs/{job_id}/result").json()["plan"]
    assert plan["source"] == "fallback" and "rate-limited" in plan["fallback_reason"] and plan["hook"]["enabled"] is False


def test_an_unknown_style_is_refused(client: TestClient, sample_video: Path):
    with sample_video.open("rb") as f:
        r = client.post("/api/videos/upload", files={"file": ("a.mp4", f, "video/mp4")}, data={"style": "cinema"})
    assert r.status_code == 422


@pytest.mark.live_ai
def test_live_gemini_picks_the_moments_asked_for(client: TestClient, tmp_path: Path):
    """The real AI: a red ball bounces on the right during 20-28 s of an otherwise empty video (no sound at all)."""
    out = tmp_path / "ball.mp4"
    subprocess.run(
        [get_settings().ffmpeg, "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=0x1d5c2f:s=640x360:r=25:d=60",
         "-f", "lavfi", "-i", "color=c=red:s=70x70:r=25:d=60",
         "-filter_complex", "[0:v][1:v]overlay=x=470+40*sin(5*t):y=140+90*sin(8*t):enable='between(t,20,28)'",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "60", str(out)],
        check=True,
    )
    job_id = _upload(client, out, style="highlight", target_duration="15", instructions="only the moments where the red square is bouncing")
    job = _wait(client, job_id)
    assert job["status"] == "completed", job["error"]
    plan = client.get(f"/api/jobs/{job_id}/result").json()["plan"]
    print("LIVE PLAN", plan["source"], plan["fallback_reason"], plan["hook"], [(c["start"], c["end"], c["focus_x"], c["reason"]) for c in plan["clips"]])
    assert plan["source"] == "ai", plan["fallback_reason"]
    inside = [c for c in plan["clips"] if c["start"] < 28 and c["end"] > 20]
    assert inside and sum(c["focus_x"] > 0.6 for c in inside if c["focus_x"] is not None) >= 1
