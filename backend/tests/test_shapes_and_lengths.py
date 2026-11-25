"""Landscape (16:9) videos, and videos longer than 90 seconds."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import get_settings
from app.editing import captions as cap
from app.editing.cuts import Cut, frame_cuts
from app.editing.ffgraph import compute_crop
from app.pipeline.planner import max_clips
from app.pipeline.prepare import job_temp_dir
from app.pipeline.revise import clamp_target
from app.plan.schema import Format
from app.schemas import EditSettings
from app.services import media

UPRIGHT, WIDE = (1080, 1920), (1920, 1080)


def test_the_size_always_follows_the_shape():
    assert Format().size == UPRIGHT
    assert Format(aspect_ratio="16:9").size == WIDE
    assert Format(aspect_ratio="16:9", width=4000, height=10).size == WIDE


def test_a_landscape_frame_never_cuts_heads_off_an_upright_source():
    cuts = [Cut(0, 1, framing="crop", focus_x=0.2), Cut(1, 2)]
    assert [c.framing for c in frame_cuts(cuts, 1080, 1920, WIDE)] == ["whole", "whole"]
    assert [c.framing for c in frame_cuts(cuts, 1440, 1080, WIDE)] == ["whole", "whole"]  # 4:3
    assert [c.framing for c in frame_cuts(cuts, 1920, 1080, WIDE)] == [None, None]  # same shape: nothing to choose
    assert [c.framing for c in frame_cuts(cuts, 2560, 1080, WIDE)] == ["crop", None]  # very wide: the plan's choice
    assert frame_cuts(cuts, 1920, 1080, UPRIGHT) == cuts  # upright videos behave as before


def test_the_crop_has_the_shape_of_the_frame():
    assert (compute_crop(1920, 1080, 0.5, WIDE).w, compute_crop(1920, 1080, 0.5, WIDE).h) == (1920, 1080)
    ultra = compute_crop(2560, 1080, 1.0, WIDE)
    assert (ultra.w, ultra.h, ultra.x) == (1920, 1080, 640)
    assert compute_crop(1920, 1080, 0.5).w == 606  # upright by default


def test_lettering_is_the_same_size_upright_and_landscape():
    pages = [cap.Page(0, 1, "hello")]
    upright, wide = cap.render_ass(pages, *UPRIGHT), cap.render_ass(pages, *WIDE)
    assert "PlayResX: 1920" in wide and "Style: Default,Arial,76," in wide and "Style: Default,Arial,76," in upright
    assert "Style: Hook,Arial Black,113," in wide


def test_lengths_up_to_ten_minutes_are_accepted():
    assert EditSettings(target_duration=600).target_duration == 600
    for bad in (14, 601):
        with pytest.raises(ValueError):
            EditSettings(target_duration=bad)
    with pytest.raises(ValueError):
        EditSettings(aspect_ratio="4:3")
    assert (clamp_target(5), clamp_target(240), clamp_target(9000)) == (15, 240, 600)
    assert (max_clips(45), max_clips(180), max_clips(600)) == (5, 9, 30)


def _wait(c: TestClient, job_id: str, version: int = 1) -> dict:
    for _ in range(450):
        job = c.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed") and not job["revising"] and (job["current_version"] == version or job["error"]):
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def _upload(c: TestClient, path: Path, **data: str):
    with path.open("rb") as f:
        return c.post("/api/videos/upload", files={"file": ("a.mp4", f, "video/mp4")}, data=data)


def _output_size(job_id: str) -> tuple[int, int]:
    info = media.probe(Path(db.get_job(job_id)["output_path"]))  # type: ignore[index]
    return info.width, info.height


def test_a_landscape_video_is_rendered_and_can_be_switched_upright(client: TestClient, sample_video: Path):
    job_id = _upload(client, sample_video, aspect_ratio="16:9", target_duration="120").json()["job_id"]
    job = _wait(client, job_id)
    assert job["status"] == "completed", job["error"]
    assert job["settings"]["aspect_ratio"] == "16:9" and _output_size(job_id) == WIDE
    spec = client.post(f"/api/jobs/{job_id}/timeline", json={}).json()
    assert spec["format"] == {"aspect_ratio": "16:9", "width": 1920, "height": 1080}

    assert client.post(f"/api/jobs/{job_id}/revisions", json={"edit": {"aspect_ratio": "9:16"}}).status_code == 202
    assert _wait(client, job_id, 2)["current_version"] == 2
    assert _output_size(job_id) == UPRIGHT
    v2 = client.get(f"/api/jobs/{job_id}/versions").json()["versions"][1]
    assert "upright" in v2["message"] and {"field": "Shape", "before": "16:9", "after": "9:16"} in v2["changes"]["settings"]
    # asking for the shape it already has changes nothing
    assert client.post(f"/api/jobs/{job_id}/revisions", json={"edit": {"aspect_ratio": "9:16"}}).status_code == 422


def test_an_upright_source_in_a_landscape_video_is_shown_whole(client: TestClient, tmp_path: Path):
    tall = tmp_path / "tall.mp4"
    subprocess.run(
        [get_settings().ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=360x640:rate=25", "-f", "lavfi",
         "-i", "sine=frequency=440", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(tall)], check=True)
    job_id = _upload(client, tall, aspect_ratio="16:9").json()["job_id"]
    assert _wait(client, job_id)["status"] == "completed"
    assert _output_size(job_id) == WIDE
    assert "overlay=(W-w)/2" in (job_temp_dir(job_id) / "filter.txt").read_text(encoding="utf-8")
    cuts = client.post(f"/api/jobs/{job_id}/timeline", json={}).json()["cuts"]
    assert cuts and all(c["framing"] == "whole" for c in cuts)


def test_bad_shapes_and_lengths_are_refused_at_upload(client: TestClient, sample_video: Path):
    assert _upload(client, sample_video, aspect_ratio="4:3").status_code == 422
    assert _upload(client, sample_video, target_duration="601").status_code == 422
