from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings


def _upload(client: TestClient, path: Path, name: str | None = None, **form):
    with path.open("rb") as f:
        return client.post(
            "/api/videos/upload",
            files={"file": (name or path.name, f, "video/mp4")},
            data=form,
        )


def _wait_done(client: TestClient, job_id: str, timeout: float = 30) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish in time")


def test_health(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "ffmpeg": True, "auth_required": False}  # local use: no login


def test_upload_and_prepare(client: TestClient, sample_video: Path):
    r = _upload(client, sample_video, target_duration="30", captions="false")
    assert r.status_code == 201
    job_id = r.json()["job_id"]

    job = _wait_done(client, job_id)
    assert job["status"] == "completed", job
    assert job["settings"]["target_duration"] == 30
    assert job["settings"]["captions"] is False
    assert job["original"]["width"] == 640 and job["original"]["height"] == 360
    assert job["original"]["has_audio"] is True
    assert 2.5 < job["original"]["duration"] < 3.5
    assert "upload_path" not in job and "audio_path" not in job  # no server paths leak

    # prepare stage really produced Whisper-ready audio
    wav = get_settings().temp_dir / job_id / "audio.wav"
    assert wav.is_file() and wav.stat().st_size > 10_000

    # the full pipeline ran: a real 1080x1920 MP4 with audio is available
    assert job["has_output"] is True and job["progress"] == 100
    result = client.get(f"/api/jobs/{job_id}/result").json()
    assert (result["rendered"]["width"], result["rendered"]["height"]) == (1080, 1920)
    assert result["rendered"]["has_audio"] is True
    assert result["preview_url"] == f"/api/videos/{job_id}/preview"
    dl = client.get(f"/api/videos/{job_id}/download")
    assert dl.status_code == 200 and dl.content[4:8] == b"ftyp"
    assert "attachment" in dl.headers["content-disposition"]
    ranged = client.get(f"/api/videos/{job_id}/preview", headers={"Range": "bytes=0-99"})
    assert ranged.status_code == 206 and len(ranged.content) == 100  # seeking works


def test_video_without_audio_fails_with_clear_message(client: TestClient, silent_video: Path):
    job_id = _upload(client, silent_video).json()["job_id"]
    job = _wait_done(client, job_id)
    assert job["status"] == "failed"
    assert job["original"]["has_audio"] is False
    assert "no audio" in job["error"].lower()
    assert "Traceback" not in job["error"]


def test_rejects_non_mp4_extension(client: TestClient, sample_video: Path):
    r = _upload(client, sample_video, name="movie.avi")
    assert r.status_code == 415


def test_rejects_fake_mp4(client: TestClient, tmp_path: Path):
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"this is not a video at all" * 100)
    r = _upload(client, fake)
    assert r.status_code == 415
    assert list(get_settings().uploads_dir.iterdir()) == []  # partial file cleaned up


def test_rejects_oversized(client: TestClient, tmp_path: Path):
    big = tmp_path / "big.mp4"
    big.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * (6 * 1024 * 1024))
    r = _upload(client, big)
    assert r.status_code == 413
    assert list(get_settings().uploads_dir.iterdir()) == []


def test_rejects_invalid_settings(client: TestClient, sample_video: Path):
    assert _upload(client, sample_video, target_duration="5").status_code == 422


def test_filename_cannot_traverse(client: TestClient, sample_video: Path):
    r = _upload(client, sample_video, name="..\\..\\evil.mp4")
    assert r.status_code == 201
    job = client.get(f"/api/jobs/{r.json()['job_id']}").json()
    assert job["original_filename"] == "evil.mp4"
    assert [p.name for p in get_settings().uploads_dir.iterdir()] == [f"{job['id']}.mp4"]


def test_unknown_and_malformed_job_ids(client: TestClient):
    assert client.get("/api/jobs/" + "0" * 32).status_code == 404
    assert client.get("/api/jobs/..%2F..%2Fetc").status_code in (404, 422)
    assert client.get("/api/jobs/not-a-valid-id").status_code == 422


# ---------- filmstrip thumbnails ----------

def test_thumbnail_is_a_cached_jpeg(client: TestClient, sample_video: Path):
    job_id = _upload(client, sample_video).json()["job_id"]
    r = client.get(f"/api/videos/{job_id}/thumb", params={"t": 1.2, "h": 64})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content[:3] == b"\xff\xd8\xff" and len(r.content) > 300
    assert "max-age" in r.headers["cache-control"]

    cached = list((get_settings().temp_dir / job_id / "thumbs").glob("64_*.jpg"))
    assert len(cached) == 1
    before = cached[0].stat().st_mtime_ns
    assert client.get(f"/api/videos/{job_id}/thumb", params={"t": 1.3, "h": 64}).status_code == 200  # same half-second slot
    assert cached[0].stat().st_mtime_ns == before and len(list(cached[0].parent.iterdir())) == 1  # nothing re-made


def test_thumbnail_past_the_end_uses_the_last_frame_and_bad_input_is_rejected(client: TestClient, sample_video: Path):
    job_id = _upload(client, sample_video).json()["job_id"]
    assert client.get(f"/api/videos/{job_id}/thumb", params={"t": 500, "h": 48}).status_code == 200
    assert client.get(f"/api/videos/{job_id}/thumb", params={"t": 1, "h": 77}).status_code == 422  # unsupported size
    assert client.get(f"/api/videos/{job_id}/thumb", params={"t": -1, "h": 64}).status_code == 422
    assert client.get(f"/api/videos/{job_id}/thumb", params={"t": "nan", "h": 64}).status_code == 422
    assert client.get(f"/api/videos/{job_id}/thumb", params={"h": 64}).status_code == 422
    assert client.get(f"/api/videos/{'0' * 32}/thumb", params={"t": 1, "h": 64}).status_code == 404
    assert client.get("/api/videos/../../x/thumb", params={"t": 1}).status_code in (404, 422)
    names = [p.name for p in (get_settings().temp_dir / job_id / "thumbs").iterdir()]
    assert all(n.startswith("48_") or n.startswith("64_") for n in names)  # only server-made names on disk
