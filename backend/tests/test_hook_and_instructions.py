from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.ai.schemas import PlanProposal, ProposedClip
from app.config import get_settings
from app.editing import captions as cap
from app.plan.text import clean_hook_text, clean_instructions
from tests.test_upload_flow import _upload, _wait_done


def _proposal(**kw) -> PlanProposal:
    return PlanProposal(
        main_subject="t", main_message="m",
        clips=[ProposedClip(start=0.0, end=3.0, purpose="hook", reason="x")], **kw,
    )


def _plan(client: TestClient, job_id: str) -> dict:
    return client.get(f"/api/jobs/{job_id}/analysis").json()["plan"]


# ---------- text cleaning ----------

def test_hook_text_is_cleaned_and_limited():
    assert clean_hook_text("  Stop   doing THIS 🔥 now!  ") == "Stop doing THIS now!"
    assert clean_hook_text("one two three four five six seven eight nine ten") == "one two three four five six seven eight"
    assert len(clean_hook_text("word " * 30)) <= 60
    assert clean_hook_text("🔥🔥🔥") == "" and clean_hook_text(None) == ""
    assert clean_hook_text("Bakit hindi ka yumayaman?") == "Bakit hindi ka yumayaman?"


def test_instructions_are_normalised_and_capped():
    assert clean_instructions("  keep\n\nthe   pricing\x00 part ") == "keep the pricing part"
    assert len(clean_instructions("a" * 900)) == 500


# ---------- ASS output ----------

def test_ass_contains_hook_in_top_style_with_chosen_colour():
    ass = cap.render_ass([cap.Page(0.0, 1.0, "hi")], hook=cap.HookTitle("Big claim here", "red", 4.0), total=10.0)
    hook_line = [l for l in ass.splitlines() if ",Hook," in l and l.startswith("Dialogue")][0]
    assert "BIG CLAIM HERE" in hook_line and "\\fad(" in hook_line
    assert "0:00:00.00,0:00:04.00,Hook" in hook_line
    style = [l for l in ass.splitlines() if l.startswith("Style: Hook")][0]
    assert cap.HOOK_ASS_COLORS["red"] in style
    assert ",8," in style  # alignment 8 = top centre


def test_hook_is_cut_short_when_video_is_shorter_and_braces_cannot_inject():
    ass = cap.render_ass([], hook=cap.HookTitle("a {\\i1} b", "yellow", 4.0), total=2.0)
    line = [l for l in ass.splitlines() if ",Hook," in l and l.startswith("Dialogue")][0]
    assert "0:00:00.00,0:00:02.00,Hook" in line
    assert "{\\i1}" not in line


# ---------- pipeline ----------

def test_ai_hook_and_instructions_flow_into_plan_and_render(client: TestClient, sample_video: Path, fake_provider):
    fake_provider.plan_responses = [_proposal(hook_text="Nobody tells you this", hook_color="cyan")]
    job_id = _upload(client, sample_video, captions="false", instructions="make it  punchy").json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"

    plan = _plan(client, job_id)
    assert plan["hook"] == {"enabled": True, "text": "Nobody tells you this", "color": "cyan", "duration_s": 4.0}
    assert plan["instructions"] == "make it punchy"

    prompt = next(c["prompt"] for c in fake_provider.calls if c["model"] == "PlanProposal")
    assert "<user_request>\nmake it punchy\n</user_request>" in prompt

    t = get_settings().temp_dir / job_id  # captions are off, but the hook alone must still be burned in
    assert "ass=captions.ass" in (t / "filter.txt").read_text()
    assert "NOBODY TELLS YOU THIS" in (t / "captions.ass").read_text(encoding="utf-8")
    assert client.get(f"/api/jobs/{job_id}/result").json()["rendered"]["width"] == 1080


def test_hook_can_be_turned_off(client: TestClient, sample_video: Path, fake_provider):
    fake_provider.plan_responses = [_proposal(hook_text="Nobody tells you this")]
    job_id = _upload(client, sample_video, captions="false", hook="false").json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"
    assert _plan(client, job_id)["hook"]["enabled"] is False
    t = get_settings().temp_dir / job_id
    assert "ass=" not in (t / "filter.txt").read_text()


def test_unusable_ai_hook_is_dropped_with_a_note(client: TestClient, sample_video: Path, fake_provider):
    fake_provider.plan_responses = [_proposal(hook_text="🔥🔥")]
    job_id = _upload(client, sample_video).json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"
    plan = _plan(client, job_id)
    assert plan["hook"]["enabled"] is False
    assert any("hook" in w for w in plan["warnings"])


def test_no_prompt_block_without_instructions(client: TestClient, sample_video: Path, fake_provider):
    job_id = _upload(client, sample_video).json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"
    prompt = next(c["prompt"] for c in fake_provider.calls if c["model"] == "PlanProposal")
    assert "user_request" not in prompt


def test_fallback_plan_has_no_hook_but_still_renders(client: TestClient, sample_video: Path):
    job_id = _upload(client, sample_video).json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"
    assert _plan(client, job_id)["hook"]["enabled"] is False


def test_instructions_are_returned_with_job_settings(client: TestClient, sample_video: Path):
    job_id = _upload(client, sample_video, instructions="x" * 800).json()["job_id"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["settings"]["instructions"] == "x" * 500 and job["settings"]["hook"] is True
