"""Free text overlays and dragged caption/hook positions (shared by video mode and photo mode)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.ai.schemas import PlanProposal, ProposedClip
from app.config import get_settings
from app.editing import captions as cap
from app.editing.overlays import TextOverlay, ass_text_lines, chars_per_line, hex_to_ass, wrap_text
from tests.test_upload_flow import _upload, _wait_done


def test_text_overlay_validation_and_cleaning():
    t = TextOverlay(id="a", text="  Hello\x07 world \n\n\n\nbye  ", color="#FF00AA")
    assert t.text == "Hello  world \n\nbye" and t.color == "#ff00aa"
    for bad in ({"text": "   "}, {"text": ""}, {"x": 1.5}, {"size": 50}, {"color": "red"}, {"color": "#12345"},
                {"style": "neon"}, {"text": "x" * 201}):
        with pytest.raises(ValidationError):
            TextOverlay(id="a", **{"text": "ok", **bad})


def test_wrapping_is_by_estimated_width_and_keeps_explicit_breaks():
    assert chars_per_line(7) == int(90 / (7 * 0.56)) == 22
    wrapped = wrap_text("one two three four five six seven eight nine ten", 7)
    assert all(len(line) <= 22 for line in wrapped.split("\n")) and wrapped.count("\n") >= 2
    assert wrap_text("a\nb", 7) == "a\nb"
    assert "\n" in wrap_text("x" * 60, 7)  # a very long word is broken instead of running off the frame


def test_colours_become_ass_bgr():
    assert hex_to_ass("#ff0000") == "&H000000FF" and hex_to_ass("#00ff00") == "&H0000FF00" and hex_to_ass("#112233") == "&H00332211"


def test_ass_lines_position_size_timing_and_escaping():
    texts = [
        TextOverlay(id="1", text="Hi {\\evil} there", x=0.25, y=0.5, size=10, color="#ff0000", style="box", start=1, end=3),
        TextOverlay(id="2", text="late", start=50),  # starts after the video ends: skipped
        TextOverlay(id="3", text="plain", style="plain", fade=False),
    ]
    lines = ass_text_lines(texts, 1080, 1920, total=10)
    assert len(lines) == 2
    first = lines[0]
    assert "0:00:01.00,0:00:03.00,TextBox" in first and "\\pos(270,960)" in first and "\\fs108" in first
    assert "\\c&H000000FF" in first and "\\fad(150,150)" in first
    assert "\\evil" not in first.split("}", 1)[1] and "(evil)" in first.replace("\\", "")  # braces/backslashes can't inject tags
    assert "\\bord0" in lines[1] and "\\fad" not in lines[1] and "0:00:10.00" in lines[1]  # runs to the end


def test_render_ass_with_dragged_positions_and_texts():
    ass = cap.render_ass(
        [cap.Page(0.0, 1.0, "hello there")], 1080, 1920, hook=cap.HookTitle("Big one"), total=8,
        texts=[TextOverlay(id="1", text="mine")], caption_pos=(0.5, 0.7), hook_pos=(0.3, 0.1),
    )
    assert "Default,,0,0,0,,{\\an5\\pos(540,1344)}hello there" in ass
    assert "Hook,,0,0,0,,{\\an5\\pos(324,192)\\fad(" in ass and "BIG ONE" in ass
    assert "TextOutline" in ass and ass.count("Dialogue:") == 3
    plain = cap.render_ass([cap.Page(0.0, 1.0, "x")], hook=cap.HookTitle("T"), total=4)
    assert "\\pos" not in plain  # nothing dragged: the usual spots


# ---------- through the API and the renderer ----------

def _finished(client: TestClient, sample_video: Path, fake_provider) -> str:
    fake_provider.plan_responses = [PlanProposal(
        main_subject="t", main_message="m", hook_text="Original hook", hook_color="yellow",
        clips=[ProposedClip(start=0.0, end=3.0, purpose="hook", reason="x")])]
    job_id = _upload(client, sample_video).json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"
    return job_id


def _edit(client: TestClient, job_id: str, edit: dict) -> dict:
    r = client.post(f"/api/jobs/{job_id}/revisions", json={"edit": edit})
    assert r.status_code == 202, r.text
    job = _wait_done(client, job_id)
    assert job["status"] == "completed", job
    return job


def test_dragged_caption_hook_and_texts_reach_the_render(client: TestClient, sample_video: Path, fake_provider):
    job_id = _finished(client, sample_video, fake_provider)
    _edit(client, job_id, {
        "caption_x": 0.4, "caption_y": 0.3, "hook_x": 0.6, "hook_y": 0.8,
        "texts": [{"id": "t1", "text": "Sale today", "x": 0.5, "y": 0.5, "size": 9, "color": "#ffcc00", "style": "box",
                   "start": 0.5, "end": 2.0}],
    })
    v2 = client.get(f"/api/jobs/{job_id}/versions").json()["versions"][1]
    assert v2["plan"]["captions"]["x"] == 0.4 and v2["plan"]["hook"]["y"] == 0.8 and len(v2["plan"]["texts"]) == 1
    assert {s["field"] for s in v2["changes"]["settings"]} >= {"Caption position", "Hook position", "Text"}
    assert "moved the caption" in v2["message"] and "edited the text" in v2["message"]

    ass = (get_settings().temp_dir / job_id / "captions.ass").read_text(encoding="utf-8")
    assert "\\pos(432,576)" in ass  # caption centred at 40 % / 30 % of 1080x1920
    assert "\\pos(648,1536)" in ass and "SALE TODAY" not in ass and "Sale today" in ass
    assert "0:00:00.50,0:00:02.00,TextBox" in ass

    spec = client.post(f"/api/jobs/{job_id}/timeline").json()
    assert spec["captions_pos"] == {"x": 0.4, "y": 0.3} and spec["hook"]["pos"] == {"x": 0.6, "y": 0.8}
    assert spec["texts"][0]["text"] == "Sale today"
    assert client.get(f"/api/jobs/{job_id}/result").json()["rendered"]["width"] == 1080


def test_reset_positions_and_validation(client: TestClient, sample_video: Path, fake_provider):
    job_id = _finished(client, sample_video, fake_provider)
    _edit(client, job_id, {"caption_x": 0.5, "caption_y": 0.4})
    _edit(client, job_id, {"reset_positions": ["caption"]})
    assert client.get(f"/api/jobs/{job_id}/versions").json()["versions"][-1]["plan"]["captions"]["x"] is None

    url = f"/api/jobs/{job_id}/revisions"
    assert client.post(url, json={"edit": {"caption_x": 0.5}}).status_code == 422  # both coordinates or none
    assert client.post(url, json={"edit": {"hook_x": 2, "hook_y": 0.5}}).status_code == 422
    assert client.post(url, json={"edit": {"texts": [{"id": "a", "text": "x", "color": "red"}]}}).status_code == 422
    assert client.post(url, json={"edit": {"texts": [{"id": f"t{i}", "text": "x"} for i in range(31)]}}).status_code == 422
    assert client.post(url, json={"edit": {"reset_positions": ["caption"]}}).status_code == 422  # already at the default: no-op
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "completed"
