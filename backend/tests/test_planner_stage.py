from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.ai.schemas import PlanProposal, ProposedClip
from tests.test_upload_flow import _upload, _wait_done


def _plan(client: TestClient, job_id: str) -> dict:
    return client.get(f"/api/jobs/{job_id}/analysis").json()["plan"]


def test_no_key_gives_labelled_fallback_plan(client: TestClient, sample_video: Path):
    job_id = _upload(client, sample_video, target_duration="15").json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"
    plan = _plan(client, job_id)
    assert plan["source"] == "fallback" and plan["fallback_reason"]
    assert plan["clips"][0]["start"] == 0
    assert plan["captions"]["enabled"] is True and plan["target_duration"] == 15


def test_ai_plan_is_validated_and_settings_come_from_user(client: TestClient, sample_video: Path, fake_provider):
    fake_provider.plan_responses = [
        PlanProposal(main_subject="topic", main_message="msg",
                     clips=[ProposedClip(start=0.2, end=2.9, purpose="hook", reason="good")])
    ]
    job_id = _upload(client, sample_video, captions="false", remove_silence="false").json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"
    plan = _plan(client, job_id)
    assert plan["source"] == "ai"
    assert (plan["clips"][0]["start"], plan["clips"][0]["end"]) == (0.0, 3.0)  # snapped to the sentence
    assert plan["summary"]["main_message"] == "msg"
    assert plan["captions"]["enabled"] is False and plan["silence"]["remove"] is False
    assert plan["reframe"]["strategy"] == "focus" and plan["reframe"]["focus_x"] == 1.0  # from visual AI, clamped
    assert len([c for c in fake_provider.calls if c["model"] == "PlanProposal"]) == 1


def test_invalid_plan_triggers_one_regeneration_with_feedback(client: TestClient, sample_video: Path, fake_provider):
    bad = PlanProposal(main_subject="t", main_message="m",
                       clips=[ProposedClip(start=50, end=40, purpose="hook", reason="backwards")])
    good = PlanProposal(main_subject="t", main_message="m",
                        clips=[ProposedClip(start=0, end=3, purpose="hook", reason="ok")])
    fake_provider.plan_responses = [bad, good]
    job_id = _upload(client, sample_video).json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"
    plan_calls = [c for c in fake_provider.calls if c["model"] == "PlanProposal"]
    assert len(plan_calls) == 2
    assert "rejected" in plan_calls[1]["prompt"] and "no usable clips" in plan_calls[1]["prompt"]
    assert _plan(client, job_id)["source"] == "ai"


def test_two_bad_answers_fall_back_instead_of_failing(client: TestClient, sample_video: Path, fake_provider):
    bad = PlanProposal(main_subject="t", main_message="m", clips=[])
    fake_provider.plan_responses = [bad, bad]
    job_id = _upload(client, sample_video).json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"
    plan = _plan(client, job_id)
    assert plan["source"] == "fallback" and "no usable clips" in plan["fallback_reason"]
    assert len([c for c in fake_provider.calls if c["model"] == "PlanProposal"]) == 2  # never a third call
