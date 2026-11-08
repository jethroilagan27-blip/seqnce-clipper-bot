from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.ai import AIError
from app.ai.schemas import PlanProposal, ProposedClip, RevisionProposal
from app.config import get_settings
from app.plan.diff import diff_clips, diff_plans
from app.retention import purge_old_jobs
from tests.test_upload_flow import _upload, _wait_done


def _clip(i: str, s: float, e: float, purpose: str = "main_content") -> dict:
    return {"id": i, "start": s, "end": e, "purpose": purpose, "reason": ""}


# ---------- diff (pure) ----------

def test_diff_marks_kept_trimmed_added_removed():
    old = [_clip("c1", 0, 10), _clip("c2", 20, 30), _clip("c3", 40, 50)]
    new = [_clip("c1", 0, 10), _clip("c2", 21.5, 30), _clip("c3", 60, 70)]
    rows = diff_clips(old, new)
    by_status = {}
    for r in rows:
        by_status.setdefault(r["status"], []).append(r)
    assert [r["start"] for r in by_status["kept"]] == [0]
    assert by_status["trimmed"][0]["before"] == {"start": 20, "end": 30}
    assert [r["start"] for r in by_status["added"]] == [60]
    assert [r["start"] for r in by_status["removed"]] == [40]
    assert [r["start"] for r in rows] == sorted(r["start"] for r in rows)  # chronological


def test_diff_settings_and_unchanged_flag():
    base = {"clips": [_clip("c1", 0, 5)], "captions": {"enabled": True}, "target_duration": 45,
            "hook": {"enabled": True, "text": "Old", "color": "yellow"}}
    same = diff_plans(base, base)
    assert same["unchanged"] is True and same["settings"] == []
    changed = diff_plans(base, {**base, "captions": {"enabled": False}, "target_duration": 30,
                                "hook": {"enabled": True, "text": "New", "color": "red"}})
    fields = {s["field"] for s in changed["settings"]}
    assert fields == {"Captions", "Target length", "Hook text", "Hook colour"} and not changed["unchanged"]


# ---------- helpers ----------

def _finished_job(client: TestClient, sample_video: Path, fake_provider, **form) -> str:
    fake_provider.plan_responses = [PlanProposal(
        main_subject="t", main_message="m", hook_text="Original hook", hook_color="yellow",
        clips=[ProposedClip(start=0.0, end=3.0, purpose="hook", reason="x")])]
    job_id = _upload(client, sample_video, **form).json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"
    return job_id


def _revision(**kw) -> RevisionProposal:
    base = dict(reply="Done.", clips=[ProposedClip(start=0.0, end=3.0, purpose="hook", reason="x")],
                hook_enabled=True, hook_text="Original hook", hook_color="yellow",
                captions_enabled=True, target_duration=45)
    return RevisionProposal(**{**base, **kw})


def _post(client, job_id, body):
    r = client.post(f"/api/jobs/{job_id}/revisions", json=body)
    assert r.status_code == 202, r.text
    job = _wait_done(client, job_id)
    assert job["status"] == "completed"
    return job


def _versions(client, job_id) -> dict:
    return client.get(f"/api/jobs/{job_id}/versions").json()


# ---------- first render is version 1 ----------

def test_first_render_is_recorded_as_version_1(client, sample_video, fake_provider):
    job_id = _finished_job(client, sample_video, fake_provider, instructions="be punchy")
    v = _versions(client, job_id)
    assert v["current"] == 1 and len(v["versions"]) == 1
    first = v["versions"][0]
    assert first["source"] == "initial" and first["message"] == "be punchy" and first["has_output"]
    assert client.get(first["preview_url"].replace("http://testserver", "")).status_code == 200
    assert client.get(f"/api/jobs/{job_id}").json()["current_version"] == 1


# ---------- chat revision ----------

def test_chat_revision_creates_new_version_with_diff_and_new_video(client, sample_video, fake_provider):
    job_id = _finished_job(client, sample_video, fake_provider)
    fake_provider.revision_responses = [_revision(reply="New hook, in red.", hook_text="Brand new hook", hook_color="red")]
    job = _post(client, job_id, {"message": "  make the hook   more exciting "})

    assert job["current_version"] == 2 and job["revising"] is False and job["error"] is None
    prompt = next(c["prompt"] for c in fake_provider.calls if c["model"] == "RevisionProposal")
    assert "<user_request>\nmake the hook more exciting\n</user_request>" in prompt
    assert "Original hook" in prompt and "[0.00-3.00] Hello world" in prompt

    v = _versions(client, job_id)
    assert v["current"] == 2 and [x["version"] for x in v["versions"]] == [1, 2]
    two = v["versions"][1]
    assert two["source"] == "chat" and two["reply"] == "New hook, in red."
    assert two["plan"]["hook"]["text"] == "Brand new hook" and two["plan"]["hook"]["color"] == "red"
    assert {s["field"] for s in two["changes"]["settings"]} == {"Hook text", "Hook colour"}
    assert [c["status"] for c in two["changes"]["clips"]] == ["kept"]

    outs = get_settings().outputs_dir
    assert (outs / f"{job_id}.mp4").exists() and (outs / f"{job_id}_v2.mp4").exists()
    t = get_settings().temp_dir / job_id
    assert "BRAND NEW HOOK" in (t / "captions.ass").read_text(encoding="utf-8")
    # the result endpoint serves the new version, and the old one is still reachable
    assert client.get(f"/api/jobs/{job_id}/result").json()["plan"]["hook"]["text"] == "Brand new hook"
    assert client.get(f"/api/videos/{job_id}/preview?version=1").status_code == 200
    assert client.get(f"/api/videos/{job_id}/preview?version=99").status_code == 404


def test_chat_history_is_sent_to_the_ai_on_the_next_turn(client, sample_video, fake_provider):
    job_id = _finished_job(client, sample_video, fake_provider)
    fake_provider.revision_responses = [_revision(reply="Shortened.", hook_text="First"), _revision(hook_text="Second")]
    _post(client, job_id, {"message": "first request"})
    _post(client, job_id, {"message": "second request"})
    prompts = [c["prompt"] for c in fake_provider.calls if c["model"] == "RevisionProposal"]
    assert "User: first request" in prompts[1] and "You: Shortened." in prompts[1]
    assert "Earlier in this conversation" not in prompts[0]


def test_chat_that_changes_nothing_reuses_the_video(client, sample_video, fake_provider):
    job_id = _finished_job(client, sample_video, fake_provider)
    fake_provider.revision_responses = [_revision(reply="It already looks right.")]
    job = _post(client, job_id, {"message": "is this good?"})
    assert job["current_version"] == 2
    v = _versions(client, job_id)["versions"][1]
    assert v["changes"]["unchanged"] is True and v["reply"] == "It already looks right."
    assert not (get_settings().outputs_dir / f"{job_id}_v2.mp4").exists()  # no pointless re-render
    assert client.get(v["preview_url"]).status_code == 200


def test_ai_unavailable_keeps_current_version_and_reports_why(client, sample_video, fake_provider):
    job_id = _finished_job(client, sample_video, fake_provider)
    fake_provider.revision_error = AIError("The AI service is rate-limited right now (free-tier quota). Try again in a minute.")
    job = _post(client, job_id, {"message": "cut the intro"})
    assert job["error"] and "rate-limited" in job["error"]
    assert job["current_version"] == 1 and job["has_output"] and job["revising"] is False
    assert len(_versions(client, job_id)["versions"]) == 1
    assert client.get(f"/api/jobs/{job_id}/result").status_code == 200
    assert list(get_settings().outputs_dir.glob("*.partial.mp4")) == []
    # ...and the next request works normally
    fake_provider.revision_error = None
    fake_provider.revision_responses = [_revision(hook_text="Second try")]
    assert _post(client, job_id, {"message": "try again"})["error"] is None


def test_chat_without_any_provider_fails_gracefully(client, sample_video):
    job_id = _upload(client, sample_video).json()["job_id"]  # no fake provider => no key => fallback plan
    assert _wait_done(client, job_id)["status"] == "completed"
    job = _post(client, job_id, {"message": "make it better"})
    assert "GEMINI_API_KEY" in job["error"] and job["current_version"] == 1


def test_invalid_ai_revision_is_retried_once_then_rejected(client, sample_video, fake_provider):
    job_id = _finished_job(client, sample_video, fake_provider)
    bad = _revision(clips=[ProposedClip(start=50, end=40, purpose="hook", reason="backwards")])
    fake_provider.revision_responses = [bad, bad]
    job = _post(client, job_id, {"message": "do something odd"})
    assert "couldn't turn that request" in job["error"]
    assert len([c for c in fake_provider.calls if c["model"] == "RevisionProposal"]) == 2
    assert job["current_version"] == 1


def test_target_length_requested_by_ai_is_clamped(client, sample_video, fake_provider):
    job_id = _finished_job(client, sample_video, fake_provider)
    fake_provider.revision_responses = [_revision(target_duration=500, hook_text="Longer")]
    _post(client, job_id, {"message": "make it very long"})
    assert _versions(client, job_id)["versions"][1]["plan"]["target_duration"] == 90


# ---------- manual edits and restore ----------

def test_manual_edit_changes_hook_and_captions_without_ai(client, sample_video, fake_provider):
    job_id = _finished_job(client, sample_video, fake_provider)
    calls_before = len(fake_provider.calls)
    job = _post(client, job_id, {"edit": {"hook_text": "My own title", "hook_color": "green", "captions_enabled": False}})
    assert len(fake_provider.calls) == calls_before  # no AI involved
    assert job["current_version"] == 2
    v = _versions(client, job_id)["versions"][1]
    assert v["source"] == "manual" and "changed the hook text" in v["message"]
    assert v["plan"]["hook"] == {"enabled": True, "text": "My own title", "color": "green", "duration_s": 4.0,
                                 "x": None, "y": None}
    assert v["plan"]["captions"]["enabled"] is False
    ass = (get_settings().temp_dir / job_id / "captions.ass").read_text(encoding="utf-8")
    assert "MY OWN TITLE" in ass and "Hello world" not in ass


def test_manual_edit_validation(client, sample_video, fake_provider):
    job_id = _finished_job(client, sample_video, fake_provider)
    url = f"/api/jobs/{job_id}/revisions"
    assert client.post(url, json={"edit": {"remove_clips": ["c1"]}}).status_code == 422  # last clip must stay
    assert client.post(url, json={"edit": {"remove_clips": ["nope"]}}).status_code == 422
    assert client.post(url, json={"edit": {"hook_text": "🔥🔥"}}).status_code == 422
    assert client.post(url, json={"edit": {"hook_color": "purple"}}).status_code == 422
    assert client.post(url, json={"edit": {}}).status_code == 422  # nothing changes
    assert client.post(url, json={}).status_code == 422
    assert client.post(url, json={"message": "hi", "restore_version": 1}).status_code == 422
    assert client.post(url, json={"message": "   "}).status_code == 422
    assert client.post(url, json={"restore_version": 1}).status_code == 422  # already current
    assert client.post(url, json={"restore_version": 9}).status_code == 404
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "completed"  # nothing got queued


def test_restore_goes_back_instantly_without_rendering(client, sample_video, fake_provider):
    job_id = _finished_job(client, sample_video, fake_provider)
    _post(client, job_id, {"edit": {"hook_text": "Changed"}})
    outs = get_settings().outputs_dir
    files_before = sorted(p.name for p in outs.iterdir())
    job = _post(client, job_id, {"restore_version": 1})
    assert job["current_version"] == 3
    assert sorted(p.name for p in outs.iterdir()) == files_before  # no new render
    v3 = _versions(client, job_id)["versions"][2]
    assert v3["source"] == "restore" and v3["plan"]["hook"]["text"] == "Original hook"
    assert {s["field"] for s in v3["changes"]["settings"]} == {"Hook text"}
    assert client.get(f"/api/jobs/{job_id}/result").json()["plan"]["hook"]["text"] == "Original hook"


# ---------- guards ----------

def test_cannot_revise_while_another_revision_is_pending(client, sample_video, fake_provider):
    job_id = _finished_job(client, sample_video, fake_provider)
    assert db.start_revision(job_id, {"kind": "manual", "message": "x"}, "editing", 75) is True
    assert db.start_revision(job_id, {"kind": "manual", "message": "y"}, "editing", 75) is False
    r = client.post(f"/api/jobs/{job_id}/revisions", json={"message": "hello"})
    assert r.status_code in (202, 409)  # worker may already have finished it; never two at once


def test_revise_unfinished_or_unknown_job(client, sample_video):
    assert client.post(f"/api/jobs/{'0' * 32}/revisions", json={"message": "x"}).status_code == 404
    assert client.post("/api/jobs/not-an-id/revisions", json={"message": "x"}).status_code == 422
    job_id = _upload(client, sample_video).json()["job_id"]
    db.update_job(job_id, status="running", stage="rendering", output_path=None)
    assert client.post(f"/api/jobs/{job_id}/revisions", json={"message": "x"}).status_code == 409


def test_jobs_finished_before_versions_existed_are_backfilled(client, sample_video, fake_provider):
    job_id = _finished_job(client, sample_video, fake_provider)
    with db.connect() as conn:
        conn.execute("DELETE FROM plan_versions WHERE job_id = ?", (job_id,))
    v = _versions(client, job_id)
    assert v["current"] == 1 and len(v["versions"]) == 1 and v["versions"][0]["source"] == "initial"


def test_retention_removes_every_version_file_and_row(client, sample_video, fake_provider):
    job_id = _finished_job(client, sample_video, fake_provider)
    _post(client, job_id, {"edit": {"hook_text": "Another"}})
    outs = get_settings().outputs_dir
    assert (outs / f"{job_id}_v2.mp4").exists()
    old = "2000-01-01T00:00:00+00:00"
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET updated_at = ? WHERE id = ?", (old, job_id))
    assert purge_old_jobs(7) == 1
    assert not list(outs.iterdir())
    assert db.list_versions(job_id) == []
