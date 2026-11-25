"""Watching in the app uses a light copy; downloading gives the full-quality video."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.services import media, playback


def _clip(path: Path, size: str = "1080x1920", seconds: int = 4) -> Path:
    # noisy picture: expensive to compress, like real footage
    subprocess.run(
        [get_settings().ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=30:d={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:d={seconds}", "-vf", "noise=alls=30:allf=t",
         "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "9M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )
    return path


def test_the_light_copy_is_small_and_keeps_the_shape(tmp_path: Path):
    video = _clip(tmp_path / "v.mp4")
    assert playback.best(video) == video  # none yet
    assert playback.make(video) is True
    copy = playback.path_for(video)
    info = media.probe(copy)
    assert (info.width, info.height) == (720, 1280) and info.has_audio
    assert copy.stat().st_size < video.stat().st_size / 3
    assert info.size_bytes * 8 / info.duration < 2_500_000
    assert playback.best(video) == copy
    assert not list(tmp_path.glob("*.part.mp4"))
    playback.delete(video)
    assert playback.best(video) == video


def test_a_wide_video_is_scaled_by_its_short_side(tmp_path: Path):
    video = _clip(tmp_path / "w.mp4", "1920x1080", 2)
    assert playback.make(video)
    info = media.probe(playback.path_for(video))
    assert (info.width, info.height) == (1280, 720)


def test_a_copy_older_than_its_video_is_not_used(tmp_path: Path):
    video = _clip(tmp_path / "v.mp4", seconds=2)
    assert playback.make(video)
    later = time.time() + 60
    os.utime(video, (later, later))  # re-rendered
    assert playback.best(video) == video


def test_an_already_small_video_is_played_as_it_is(tmp_path: Path):
    video = tmp_path / "s.mp4"
    subprocess.run([get_settings().ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=360x640:d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    assert playback.make(video) is False and playback.best(video) == video and not playback.path_for(video).exists()


def test_a_broken_file_never_raises(tmp_path: Path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"nope" * 100)
    assert playback.make(junk) is False and playback.best(junk) == junk
    assert playback.make(tmp_path / "missing.mp4") is False


def test_the_player_gets_the_light_copy_and_the_download_the_full_video(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 200)
    source = tmp_path / "talk.mp4"
    subprocess.run(
        [get_settings().ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=720x1280:r=30:d=4",
         "-f", "lavfi", "-i", "sine=frequency=440:d=4", "-vf", "noise=alls=25:allf=t", "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "3M",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source)],
        check=True,
    )
    with source.open("rb") as f:
        job_id = client.post("/api/videos/upload", files={"file": ("talk.mp4", f, "video/mp4")}).json()["job_id"]
    for _ in range(600):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "completed", job["error"]
    watch = client.get(f"/api/videos/{job_id}/preview")
    full = client.get(f"/api/videos/{job_id}/download")
    assert watch.status_code == full.status_code == 200
    assert len(watch.content) < len(full.content) * 0.6
    rendered = client.get(f"/api/jobs/{job_id}/result").json()["rendered"]
    assert (rendered["width"], rendered["height"]) == (1080, 1920)  # the download keeps full size
    assert rendered["size_bytes"] * 8 / rendered["duration"] < 6_500_000  # and is capped


def test_older_videos_can_be_given_light_copies_once(client: TestClient):
    from app import admin

    cfg = get_settings()
    _clip(cfg.outputs_dir / ("a" * 32 + ".mp4"), seconds=2)
    assert admin.make_light_copies() == (1, 1)
    assert admin.make_light_copies() == (0, 1)  # nothing left to do, and copies are not copied
