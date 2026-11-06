from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import get_settings
from app.services.media import MediaError
from tests.test_upload_flow import _upload, _wait_done


def _video(path: Path, size: str, seconds: int = 3, extra: list[str] | None = None) -> Path:
    cmd = [get_settings().ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=25",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", str(seconds),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", *(extra or []), str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.mark.parametrize("size", ["720x1280", "720x720", "854x480", "1920x1080", "480x854"])
def test_any_source_shape_renders_1080x1920(client: TestClient, tmp_path: Path, size: str):
    job_id = _upload(client, _video(tmp_path / "v.mp4", size)).json()["job_id"]
    job = _wait_done(client, job_id)
    assert job["status"] == "completed", job
    r = client.get(f"/api/jobs/{job_id}/result").json()["rendered"]
    assert (r["width"], r["height"]) == (1080, 1920)


def test_ffmpeg_failure_marks_job_failed_and_cleans_up(client: TestClient, sample_video: Path, monkeypatch):
    def boom(*a, **k):
        raise MediaError("Rendering the video failed.")

    monkeypatch.setattr("app.pipeline.render.media.run_ffmpeg_with_progress", boom)
    job = _wait_done(client, _upload(client, sample_video).json()["job_id"])
    assert job["status"] == "failed" and job["error"] == "Rendering the video failed."
    assert job["has_output"] is False
    assert not list(get_settings().outputs_dir.iterdir())  # no partial/final file left behind


def test_unexpected_exception_is_hidden_from_user(client: TestClient, sample_video: Path, monkeypatch):
    def bug(*a, **k):
        raise RuntimeError(r"secret internal detail C:/Users/HP/private")

    monkeypatch.setattr("app.pipeline.visual.frames_svc.extract_frames", bug)
    job = _wait_done(client, _upload(client, sample_video).json()["job_id"])
    assert job["status"] == "failed"
    assert "secret" not in job["error"] and "Users" not in job["error"]


def test_render_output_is_verified_not_trusted(client: TestClient, sample_video: Path, monkeypatch):
    """If ffmpeg 'succeeds' but writes junk, the job must fail instead of serving it."""
    def fake_ffmpeg(cmd, cwd, total_s, on_progress, timeout=0):
        Path(cmd[-1]).write_bytes(b"not a video" * 5000)

    monkeypatch.setattr("app.pipeline.render.media.run_ffmpeg_with_progress", fake_ffmpeg)
    job = _wait_done(client, _upload(client, sample_video).json()["job_id"])
    assert job["status"] == "failed" and job["has_output"] is False
    assert not list(get_settings().outputs_dir.iterdir())


def test_interrupted_job_is_requeued_and_finishes(client: TestClient, sample_video: Path):
    job_id = _upload(client, sample_video).json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"
    db.update_job(job_id, status="running", stage="rendering", output_path=None)
    assert db.requeue_interrupted_jobs() == 1
    assert db.get_job(job_id)["status"] == "queued"
    assert _wait_done(client, job_id)["status"] == "completed"
    assert client.get(f"/api/jobs/{job_id}/result").status_code == 200


def test_two_jobs_run_one_after_another(client: TestClient, sample_video: Path):
    ids = [_upload(client, sample_video).json()["job_id"] for _ in range(3)]
    assert [_wait_done(client, i, timeout=90)["status"] for i in ids] == ["completed"] * 3
    assert len({client.get(f"/api/jobs/{i}/result").json()["rendered"]["size_bytes"] > 0 for i in ids}) == 1


def test_output_files_served_only_for_own_job(client: TestClient, sample_video: Path):
    a = _upload(client, sample_video).json()["job_id"]
    _wait_done(client, a)
    assert client.get(f"/api/videos/{'0' * 32}/preview").status_code == 404
    assert client.get(f"/api/videos/..%2F..%2Fsvb.sqlite3/preview").status_code in (404, 422)
