from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ai.schemas import PlanProposal, ProposedClip
from app.config import get_settings
from app.plan.preview import build_spec
from app.plan.schema import Captions, Clip, EditingPlan, Hook
from app.plan.validate import PlanValidationError, validate_manual_clips
from tests.test_upload_flow import _upload, _wait_done


def _c(s, e, purpose="main_content", reason=""):
    return SimpleNamespace(start=s, end=e, purpose=purpose, reason=reason)


# ---------- validate_manual_clips ----------

def test_manual_clips_keep_exact_positions_sort_and_merge():
    clips = validate_manual_clips([_c(20, 30), _c(2.123, 8.5), _c(8.54, 12)], 60)
    assert [(c.start, c.end) for c in clips] == [(2.123, 12), (20, 30)]  # touching clips merged, nothing snapped
    assert [c.id for c in clips] == ["c1", "c2"]


def test_manual_clips_are_clamped_to_the_video():
    clips = validate_manual_clips([_c(-5, 10), _c(50, 90)], 60)
    assert [(c.start, c.end) for c in clips] == [(0, 10), (50, 60)]


@pytest.mark.parametrize("bad,needle", [
    ([], "at least one clip"),
    ([_c(5, 5.4)], "shorter than"),
    ([_c(float("nan"), 9)], "invalid times"),
    ([_c(0, 59), _c(100, 290)], "maximum"),
])
def test_manual_clips_rejections(bad, needle):
    with pytest.raises(PlanValidationError) as exc:
        validate_manual_clips(bad, 300)
    assert needle in " ".join(exc.value.errors)


def test_manual_clips_count_limit():
    with pytest.raises(PlanValidationError):
        validate_manual_clips([_c(i * 3, i * 3 + 1.5) for i in range(31)], 600)


# ---------- build_spec (pure) ----------

def _plan(clips, **kw) -> EditingPlan:
    return EditingPlan(target_duration=30, clips=[Clip(id=f"c{i}", start=s, end=e, purpose="main_content")
                                                  for i, (s, e) in enumerate(clips, 1)], **kw)


def _transcript():
    words = [{"start": i * 0.5, "end": i * 0.5 + 0.4, "word": f"w{i}"} for i in range(40)]  # 20 s of speech
    return {"segments": [{"start": 0, "end": 20, "text": "x", "words": words}]}


META = {"duration": 20.0, "width": 1280, "height": 720}


def test_spec_maps_output_time_and_captions_and_hook():
    plan = _plan([(0, 4), (10, 14)], hook=Hook(enabled=True, text="Big title", color="red", duration_s=4.0),
                 captions=Captions(enabled=True, max_words_per_line=4))
    spec = build_spec(plan, _transcript(), META)
    assert len(spec["cuts"]) == 2 and spec["cuts"][1]["out_start"] == pytest.approx(
        spec["cuts"][0]["end"] - spec["cuts"][0]["start"], abs=0.01)
    assert spec["total"] == pytest.approx(sum(c["end"] - c["start"] for c in spec["cuts"]), abs=0.01)
    assert spec["pages"] and all(0 <= p["start"] < p["end"] <= spec["total"] + 0.5 for p in spec["pages"])
    assert spec["hook"] == {"enabled": True, "text": "Big title", "color": "red", "duration_s": 4.0, "pos": None}
    assert spec["captions_pos"] is None and spec["texts"] == []
    assert spec["source"] == {"width": 1280, "height": 720, "duration": 20.0}
    assert spec["reframe"]["focus_x"] == 0.5


def test_spec_without_captions_or_hook():
    spec = build_spec(_plan([(0, 4)], captions=Captions(enabled=False)), _transcript(), META)
    assert spec["pages"] == [] and spec["hook"]["enabled"] is False


def test_spec_hook_never_longer_than_the_video():
    plan = _plan([(0, 2)], hook=Hook(enabled=True, text="Hi", color="yellow", duration_s=8.0))
    assert build_spec(plan, _transcript(), META)["hook"]["duration_s"] <= 2.5


# ---------- API ----------

def _finished(client, sample_video, fake_provider, **form) -> str:
    fake_provider.plan_responses = [PlanProposal(
        main_subject="t", main_message="m", hook_text="Original hook", hook_color="yellow",
        clips=[ProposedClip(start=0.0, end=3.0, purpose="hook", reason="x")])]
    job_id = _upload(client, sample_video, **form).json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"
    return job_id


def _revise(client, job_id, body):
    r = client.post(f"/api/jobs/{job_id}/revisions", json=body)
    assert r.status_code == 202, r.text
    job = _wait_done(client, job_id)
    assert job["status"] == "completed"
    return job


def test_timeline_matches_what_the_renderer_used(client: TestClient, sample_video, fake_provider):
    """The preview must cut exactly where the final video was cut."""
    job_id = _finished(client, sample_video, fake_provider)
    spec = client.post(f"/api/jobs/{job_id}/timeline").json()
    rendered = json.loads((get_settings().temp_dir / job_id / "cuts.json").read_text())
    assert spec["total"] == rendered["total"]
    assert [(c["start"], c["end"], c["out_start"]) for c in spec["cuts"]] == \
           [(c["start"], c["end"], c["out_start"]) for c in rendered["cuts"]]
    assert spec["hook"]["text"] == "Original hook" and [p["text"] for p in spec["pages"]] == ["Hello world"]


def test_timeline_draft_does_not_change_anything(client, sample_video, fake_provider):
    job_id = _finished(client, sample_video, fake_provider)
    spec = client.post(f"/api/jobs/{job_id}/timeline",
                       json={"edit": {"clips": [{"start": 1.6, "end": 3.0}], "hook_text": "Draft"}}).json()
    assert spec["hook"]["text"] == "Draft" and spec["clips"][0]["start"] == 1.6
    assert spec["cuts"][0]["start"] == pytest.approx(1.5)  # starts at the first word inside the clip
    assert [p["text"] for p in spec["pages"]] == ["world"]
    again = client.post(f"/api/jobs/{job_id}/timeline").json()
    assert again["hook"]["text"] == "Original hook" and again["clips"][0]["start"] == 0.0
    assert client.get(f"/api/jobs/{job_id}").json()["current_version"] == 1


def test_timeline_for_an_older_version_and_errors(client, sample_video, fake_provider):
    job_id = _finished(client, sample_video, fake_provider)
    _revise(client, job_id, {"edit": {"hook_text": "Second"}})
    assert client.post(f"/api/jobs/{job_id}/timeline", json={"version": 1}).json()["hook"]["text"] == "Original hook"
    assert client.post(f"/api/jobs/{job_id}/timeline").json()["hook"]["text"] == "Second"
    assert client.post(f"/api/jobs/{job_id}/timeline", json={"version": 9}).status_code == 404
    assert client.post(f"/api/jobs/{job_id}/timeline", json={"edit": {"clips": [{"start": 1, "end": 1.2}]}}).status_code == 422
    assert client.post(f"/api/jobs/{'0' * 32}/timeline").status_code == 404


def test_timeline_available_before_a_plan_exists_is_409(client, sample_video):
    from app import db
    job_id = _upload(client, sample_video).json()["job_id"]
    _wait_done(client, job_id)
    db.update_job(job_id, status="running", stage="planning", plan_json=None)
    assert client.post(f"/api/jobs/{job_id}/timeline").status_code == 409


def test_manual_clip_edit_creates_a_version_and_renders_it(client, sample_video, fake_provider):
    job_id = _finished(client, sample_video, fake_provider)
    job = _revise(client, job_id, {"edit": {"clips": [{"start": 1.6, "end": 3.0, "purpose": "conclusion",
                                                      "reason": "Only the end"}], "hook_duration_s": 2.5}})
    assert job["current_version"] == 2
    v2 = client.get(f"/api/jobs/{job_id}/versions").json()["versions"][1]
    assert v2["source"] == "manual" and "edited the clips" in v2["message"]
    assert v2["plan"]["clips"] == [{"id": "c1", "start": 1.6, "end": 3.0, "purpose": "conclusion", "reason": "Only the end"}]
    assert v2["plan"]["hook"]["duration_s"] == 2.5
    assert [c["status"] for c in v2["changes"]["clips"]] == ["trimmed"]
    out = client.get(f"/api/jobs/{job_id}/result").json()["rendered"]
    assert out["duration"] == pytest.approx(1.5, abs=0.15)  # only the word "world"
    ass = (get_settings().temp_dir / job_id / "captions.ass").read_text(encoding="utf-8")
    assert ",Default,,0,0,0,,world" in ass and "Hello" not in ass  # captions only for what is still in the video
    spec = client.post(f"/api/jobs/{job_id}/timeline").json()
    rendered = json.loads((get_settings().temp_dir / job_id / "cuts.json").read_text())
    assert [(c["start"], c["end"]) for c in spec["cuts"]] == [(c["start"], c["end"]) for c in rendered["cuts"]]


def test_clip_edit_validation_over_the_api(client, sample_video, fake_provider):
    job_id = _finished(client, sample_video, fake_provider)
    url = f"/api/jobs/{job_id}/revisions"
    assert client.post(url, json={"edit": {"clips": []}}).status_code == 422
    assert client.post(url, json={"edit": {"clips": [{"start": 0, "end": 0.4}]}}).status_code == 422
    assert client.post(url, json={"edit": {"clips": [{"start": 0, "end": 3}], "remove_clips": ["c1"]}}).status_code == 422
    assert client.post(url, json={"edit": {"clips": [{"start": 0, "end": 3, "purpose": "bogus"}]}}).status_code == 422
    assert client.post(url, json={"edit": {"clips": [{"start": 0, "end": 3}]}}).status_code == 422  # identical: no-op
    assert client.post(url, json={"edit": {"hook_duration_s": 99}}).status_code == 422
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "completed"
