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
from app.ai.schemas import HighlightProposal, HighlightRevision, WatchedMoment
from app.config import get_settings
from app.editing import moments as mo
from app.editing.cuts import Cut
from app.editing.ffgraph import build_filtergraph, compute_crop
from app.pipeline import highlight
from app.pipeline.prepare import job_temp_dir
from app.services import media

# ---------- finding moments without an AI (pure) ----------

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
    best = sorted(found, key=lambda m: -m.local)[:4]
    assert any(m.start < 28 and m.end > 20 for m in best) and any(m.start < 43 and m.end > 40 for m in best)


def test_candidates_cover_the_whole_video_without_overlapping():
    motion, _ = mo.motion_series(_video(600, [(100, 110)]))
    found = mo.candidates(motion, None, 600, [], target=45)
    assert 20 <= len(found) <= 40
    assert all(a.end <= b.start + 1e-6 for a, b in zip(found, found[1:]))
    assert found[0].start < 120 and found[-1].end > 480  # quiet parts get looked at too
    assert all(mo.MIN_MOMENT_S <= m.duration <= 6.01 for m in found)


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


# ---------- whole actions ----------

def test_times_are_read_the_way_the_ai_writes_them():
    assert mo.parse_clock("01:15") == 75 and mo.parse_clock("0:07.5") == 7.5 and mo.parse_clock("1:02:03") == 3723
    assert mo.parse_clock("42") == 42 and mo.parse_clock("12.5s") == 12.5
    for junk in ("", "soon", "1:2:3:4", "-3", "nan", "inf", "1::2"):
        assert mo.parse_clock(junk) is None, junk


def _m(start: float, end: float, score: float, **kw) -> mo.Moment:
    return mo.Moment(start, end, 0.0, score=score, **kw)


def test_each_action_gets_room_and_actions_that_touch_are_one_part():
    # a shot seen as two pieces with a small hole in it (the bug: "cut, then it comes back near the basket")
    [one] = mo.whole_actions([_m(10, 12, 0.9, label="shot", focus_x=0.3), _m(14, 15, 0.7, label="goes in", focus_x=0.8)], 60)
    assert one.start == pytest.approx(9.4) and one.end == pytest.approx(16.2) and one.label == "shot"
    assert one.framing == "whole"  # they needed different crops: show it all
    assert len(mo.whole_actions([_m(10, 12, 0.9), _m(20, 22, 0.7)], 60)) == 2  # far enough apart: two parts


def test_parts_are_never_tiny_never_outside_the_video_and_never_overlap():
    [tiny] = mo.whole_actions([_m(0, 0.5, 1.0)], 60)
    assert tiny.start == 0 and tiny.duration >= mo.MIN_PART_S
    [last] = mo.whole_actions([_m(59.5, 60, 1.0)], 60)
    assert last.end == 60 and last.duration >= mo.MIN_PART_S
    [huge] = mo.whole_actions([_m(10, 200, 1.0)], 300)
    assert huge.duration == mo.MAX_PART_S and huge.end == 201.0  # the result is kept
    long_run = mo.whole_actions([_m(0, 30, 0.9), _m(29, 60, 0.8)], 90)
    assert all(a.end <= b.start for a, b in zip(long_run, long_run[1:]))
    assert mo.whole_actions([_m(5, 5, 1), _m(70, 80, 1)], 60) == []


def test_assembling_takes_the_best_whole_moments_and_cuts_none_of_them_short():
    found = [_m(i * 20, i * 20 + 6, s, label=str(i)) for i, s in enumerate([0.2, 0.9, 0.3, 0.8, 0.7, 0.95])]
    chosen = mo.assemble(found, target=20, duration=140)
    assert [m.label for m in chosen] == ["1", "3", "5"]  # the three best, in the order they happen
    assert all(m.duration == pytest.approx(7.6) for m in chosen)  # whole, with their lead-in and result
    [long_one] = mo.assemble([_m(10, 38, 1.0)], target=15, duration=60)
    assert long_one.duration > 28  # a long set is shown completely rather than chopped
    assert len(mo.assemble(found, target=90, duration=140)) == 6


# ---------- the AI's answer ----------

def _watched(start: str, end: str, score: int = 8, fx: float = 0.5, framing: str = "crop", label: str = "play") -> WatchedMoment:
    return WatchedMoment(start=start, end=end, score=score, label=label, focus_x=fx, framing=framing)


def test_the_ai_reply_is_checked_before_it_is_used():
    proposal = HighlightProposal(main_subject="x", hook_text="t", hook_color="red", moments=[
        _watched("00:05", "00:09", score=999, fx=7, label="  big    dunk "),
        _watched("00:20", "00:20"),  # within one second
        _watched("00:30", "00:35", score=0),  # not worth it
        _watched("whenever", "00:35"), _watched("02:00", "02:05"),  # unreadable / outside a 60 s video
        _watched("00:55", "01:30", framing="whole"),
    ])
    got = highlight.from_ai(proposal, 60)
    assert [(m.start, m.end) for m in got] == [(5, 9), (20, 21), (55, 60)]
    assert got[0].score == 1.0 and got[0].focus_x == 1.0 and got[0].label == "big dunk" and got[2].framing == "whole"


def test_longer_videos_are_watched_more_coarsely():
    assert highlight.watch_settings(40) == (4, False) and highlight.watch_settings(150) == (2, False)
    for seconds in (300, 700, 1800):
        fps, low = highlight.watch_settings(seconds)
        assert low and seconds * (66 * fps + 32) < 250_000  # stays inside one minute's allowance


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


def test_a_piece_can_show_the_whole_picture_next_to_cropped_ones():
    cuts = [Cut(0, 2, 0.0, 0.2), Cut(3, 5, 2.0, 0.8, framing="whole")]
    crops = [compute_crop(1920, 1080, 0.2), compute_crop(1920, 1080, 0.8)]
    g = build_filtergraph(cuts, crops[0], captions=True, music=False, music_volume=0.3, total=4, crops=crops)
    assert f"crop=606:1080:{crops[0].x}:0,scale=1080:1920" in g  # the cropped piece reaches the output size on its own
    assert "force_original_aspect_ratio=decrease" in g and "boxblur" in g and "overlay=(W-w)/2:(H-h)/2" in g
    assert "[vcat]fps=30,ass=captions.ass[vout]" in g  # nothing is cropped a second time


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


def test_without_an_ai_the_busy_loud_stretches_are_shown_in_long_pieces(client: TestClient, match_video: Path):
    job_id = _upload(client, match_video, style="highlight", target_duration="15")
    job = _wait(client, job_id)
    assert job["status"] == "completed", job["error"]
    result = client.get(f"/api/jobs/{job_id}/result").json()
    plan = result["plan"]
    assert plan["style"] == "highlight" and plan["source"] == "fallback" and plan["captions"]["enabled"] is False
    assert (result["rendered"]["width"], result["rendered"]["height"]) == (1080, 1920)
    assert all(c["end"] - c["start"] >= mo.MIN_PART_S for c in plan["clips"])  # no choppy two-second bits
    assert any(c["start"] < 28 and c["end"] > 20 for c in plan["clips"]) and any(c["start"] < 52 and c["end"] > 44 for c in plan["clips"])
    assert any("movement and loudness only" in w for w in plan["warnings"])
    # the editor pages work without any words
    assert client.post(f"/api/jobs/{job_id}/timeline", json={}).json()["pages"] == []
    assert client.get(f"/api/jobs/{job_id}/analysis").json()["transcript"]["segments"] == []


class FakeHighlightAI:
    """"Watches" the video and reports the actions it was told about."""

    def __init__(self):
        self.moments = [_watched("00:44", "00:52", score=10, fx=0.9, framing="crop", label="great play")]
        self.calls: list[dict] = []
        self.target = 15
        self.fail: str | None = None

    def generate_from_video(self, prompt, response_model, video):
        info = media.probe(video.path)
        self.calls.append({"prompt": prompt, "model": response_model.__name__, "size": (info.width, info.height),
                           "seconds": info.duration, "audio": info.has_audio, "fps": video.fps})
        if self.fail:
            raise AIError(self.fail)
        common = dict(main_subject="a match", moments=self.moments, hook_text="What a finish", hook_color="cyan")
        if response_model is HighlightRevision:
            return HighlightRevision(**common, reply="Now it shows the first goal.", target_duration=self.target, hook_enabled=False)
        return HighlightProposal(**common)


@pytest.fixture
def ai(monkeypatch: pytest.MonkeyPatch):
    fake = FakeHighlightAI()
    monkeypatch.setattr("app.pipeline.highlight.get_provider", lambda *a, **k: fake)
    return fake


def test_the_ai_watches_the_video_and_its_whole_moments_are_used(client: TestClient, ai: FakeHighlightAI, match_video: Path):
    job_id = _upload(client, match_video, style="highlight", target_duration="15", instructions="the second goal")
    job = _wait(client, job_id)
    assert job["status"] == "completed", job["error"]
    [call] = ai.calls  # ONE AI request for the whole highlight
    assert call["model"] == "HighlightProposal" and "the second goal" in call["prompt"] and "01:00" in call["prompt"]
    assert call["size"] == (640, 360) and abs(call["seconds"] - 60) < 1 and call["audio"] and call["fps"] == 4  # all of it, with sound
    plan = client.get(f"/api/jobs/{job_id}/result").json()["plan"]
    assert plan["source"] == "ai" and plan["hook"]["text"] == "What a finish" and plan["hook"]["enabled"]
    [clip] = plan["clips"]  # ONE uncut part for one action
    assert clip["start"] == pytest.approx(43.4) and clip["end"] == 53.0 and clip["focus_x"] == 0.9 and clip["framing"] == "crop"
    cuts = json.loads((job_temp_dir(job_id) / "cuts.json").read_text())["cuts"]
    assert len(cuts) == 1 and cuts[0]["focus_x"] == 0.9

    ai.moments = [_watched("00:20", "00:28", framing="whole", label="first goal"), _watched("00:44", "00:48", fx=0.9)]
    ai.target = 20
    assert client.post(f"/api/jobs/{job_id}/revisions", json={"message": "show the first goal too"}).status_code == 202
    job = _wait(client, job_id, version=2)
    assert job["status"] == "completed" and job["current_version"] == 2, job["error"]
    assert ai.calls[-1]["model"] == "HighlightRevision" and "show the first goal too" in ai.calls[-1]["prompt"]
    assert "00:43-00:53" in ai.calls[-1]["prompt"]  # it is told what is in the video now
    v2 = client.get(f"/api/jobs/{job_id}/versions").json()["versions"][-1]
    assert v2["reply"] == "Now it shows the first goal." and v2["plan"]["target_duration"] == 20 and v2["plan"]["hook"]["enabled"] is False
    first = v2["plan"]["clips"][0]
    assert first["start"] <= 20 and first["end"] >= 28 and first["framing"] == "whole"
    result = client.get(f"/api/jobs/{job_id}/result").json()
    assert (result["rendered"]["width"], result["rendered"]["height"]) == (1080, 1920)  # whole + cropped parts joined fine


def test_a_hand_trim_keeps_the_crop_and_framing(client: TestClient, ai: FakeHighlightAI, match_video: Path):
    ai.moments = [_watched("00:44", "00:52", fx=0.9, framing="whole")]
    job_id = _upload(client, match_video, style="highlight", target_duration="15")
    _wait(client, job_id)
    first = client.get(f"/api/jobs/{job_id}/result").json()["plan"]["clips"][0]
    edit = {"clips": [{"start": first["start"] + 0.3, "end": first["end"] + 0.5, "purpose": "hook"}]}
    spec = client.post(f"/api/jobs/{job_id}/timeline", json={"edit": edit}).json()
    assert spec["cuts"][0]["focus_x"] == 0.9 and spec["cuts"][0]["framing"] == "whole"


def test_when_the_ai_fails_or_finds_nothing_the_highlight_is_still_made(client: TestClient, ai: FakeHighlightAI, match_video: Path):
    ai.fail = "The AI service is rate-limited right now."
    job = _wait(client, _upload(client, match_video, style="highlight", target_duration="15"))
    assert job["status"] == "completed", job["error"]
    plan = client.get(f"/api/jobs/{job['id']}/result").json()["plan"]
    assert plan["source"] == "fallback" and "rate-limited" in plan["fallback_reason"] and plan["hook"]["enabled"] is False
    ai.fail, ai.moments = None, []
    job = _wait(client, _upload(client, match_video, style="highlight", target_duration="15"))
    plan = client.get(f"/api/jobs/{job['id']}/result").json()["plan"]
    assert plan["source"] == "fallback" and "no moment" in plan["fallback_reason"]


def test_an_unknown_style_is_refused(client: TestClient, sample_video: Path):
    with sample_video.open("rb") as f:
        r = client.post("/api/videos/upload", files={"file": ("a.mp4", f, "video/mp4")}, data={"style": "cinema"})
    assert r.status_code == 422


@pytest.mark.live_ai
def test_live_gemini_picks_whole_actions(client: TestClient, tmp_path: Path):
    """The real AI: in an otherwise still 40 s video, a ball flies across into a "basket" during 12-18 s (no sound)."""
    out = tmp_path / "shot.mp4"
    subprocess.run(
        [get_settings().ffmpeg, "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=0x1d5c2f:s=640x360:r=25:d=40",
         "-f", "lavfi", "-i", "color=c=orange:s=44x44:r=25:d=40",
         "-filter_complex",
         "[0:v]drawbox=x=540:y=190:w=70:h=14:color=white:t=fill[court];"
         "[court][1:v]overlay=x='if(lt(t,12),40,min(40+(t-12)*90,553))':y='if(lt(t,12),290,if(lt(t,17.7),290-270*sin((t-12)/5.7*2.4),150+(t-17.7)*120))'",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "40", str(out)],
        check=True,
    )
    job_id = _upload(client, out, style="highlight", target_duration="15", instructions="the basketball shot: the orange ball flying into the basket")
    job = _wait(client, job_id)
    assert job["status"] == "completed", job["error"]
    plan = client.get(f"/api/jobs/{job_id}/result").json()["plan"]
    print("LIVE PLAN", plan["source"], plan["fallback_reason"], plan["hook"],
          [(c["start"], c["end"], c.get("framing"), c.get("focus_x"), c["reason"]) for c in plan["clips"]])
    assert plan["source"] == "ai", plan["fallback_reason"]
    assert any(c["start"] <= 13 and c["end"] >= 17 for c in plan["clips"]), plan["clips"]  # the whole flight in one uncut part
