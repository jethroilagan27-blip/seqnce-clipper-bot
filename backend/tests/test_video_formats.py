"""Video mode accepts phone formats (MOV and friends), and makes a browser-friendly copy when the original can't be played."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.pipeline import prepare

from .test_upload_flow import _upload, _wait_done


def _encode(path: Path, *codec_args: str, container: str | None = None) -> Path:
    cmd = [get_settings().ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "3", *codec_args, "-c:a", "aac"]
    if container:
        cmd += ["-f", container]
    subprocess.run([*cmd, str(path)], check=True)
    return path


def _codec(path: Path) -> str:
    out = subprocess.run([get_settings().ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _wait_for(path: Path, timeout: float = 60) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if path.is_file():
            return True
        time.sleep(0.3)
    return False


def test_a_mov_file_is_accepted_edited_and_gets_a_browser_copy(client: TestClient, tmp_path: Path):
    mov = _encode(tmp_path / "phone.mov", "-c:v", "libx264", "-pix_fmt", "yuv420p", container="mov")
    r = _upload(client, mov)
    assert r.status_code == 201, r.text
    job_id = r.json()["job_id"]
    job = _wait_done(client, job_id)
    assert job["status"] == "completed" and job["original"]["width"] == 640
    uploads = list(get_settings().uploads_dir.iterdir())
    assert [p.suffix for p in uploads] == [".mov"]  # stored under a server-made name with its real extension
    web = prepare.web_copy_path(job_id)
    assert _wait_for(web), "a browser-friendly copy was made for the .mov"
    original = client.get(f"/api/videos/{job_id}/original")
    assert original.status_code == 200 and original.headers["content-type"] == "video/mp4"  # served the web copy
    assert _codec(web) == "h264"


def test_hevc_footage_from_a_phone_gets_an_h264_copy_the_page_can_play(client: TestClient, tmp_path: Path):
    encoders = subprocess.run([get_settings().ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    if "libx265" not in encoders:
        pytest.skip("this FFmpeg can't make HEVC test footage")
    hevc = _encode(tmp_path / "iphone.mov", "-c:v", "libx265", "-pix_fmt", "yuv420p", "-tag:v", "hvc1", container="mov")
    assert _codec(hevc) == "hevc"
    job_id = _upload(client, hevc).json()["job_id"]
    assert _wait_done(client, job_id, timeout=90)["status"] == "completed"
    web = prepare.web_copy_path(job_id)
    assert _wait_for(web, 90) and _codec(web) == "h264"


def test_a_plain_h264_mp4_needs_no_extra_copy(client: TestClient, sample_video: Path):
    job_id = _upload(client, sample_video).json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"
    time.sleep(0.5)
    assert not prepare.web_copy_path(job_id).exists()
    assert client.get(f"/api/videos/{job_id}/original").headers["content-type"] == "video/mp4"


def test_mkv_and_webm_are_checked_by_their_header(client: TestClient, tmp_path: Path):
    mkv = _encode(tmp_path / "clip.mkv", "-c:v", "libx264", "-pix_fmt", "yuv420p", container="matroska")
    assert _upload(client, mkv).status_code == 201
    fake = tmp_path / "fake.mkv"
    fake.write_bytes(b"this is only text, renamed" * 50)
    assert _upload(client, fake).status_code == 415


def test_other_files_are_still_refused_with_a_message_that_names_the_formats(client: TestClient, tmp_path: Path, sample_video: Path):
    for name in ("movie.avi", "notes.txt", "clip.exe"):
        r = _upload(client, sample_video, name=name)
        assert r.status_code == 415 and "MOV" in r.json()["detail"], name
    renamed = tmp_path / "fake.mov"
    renamed.write_bytes(b"this is not a video at all" * 100)
    assert _upload(client, renamed).status_code == 415
    assert list(get_settings().uploads_dir.iterdir()) == []  # nothing half-kept


def test_the_decision_about_a_browser_copy():
    from app.services.media import MediaInfo

    def info(codec: str) -> MediaInfo:
        return MediaInfo(3.0, 640, 360, 25.0, codec, True, "aac", 44100, 2, 1000)

    assert prepare.needs_web_copy(info("h264"), "a.mp4") is False
    assert prepare.needs_web_copy(info("h264"), "A.M4V") is False
    assert prepare.needs_web_copy(info("h264"), "a.mov") is True  # a MOV file: not every browser plays it
    assert prepare.needs_web_copy(info("hevc"), "a.mp4") is True
    assert prepare.needs_web_copy(info("vp9"), "a.webm") is True


def test_a_heavy_original_gets_a_light_preview_copy_too():
    from app.services.media import MediaInfo

    def info(w: int, h: int, seconds: float, mb: float) -> MediaInfo:
        return MediaInfo(seconds, w, h, 30.0, "h264", True, "aac", 48000, 2, int(mb * 1024 * 1024))

    assert prepare.needs_web_copy(info(576, 1024, 42, 7.4), "a.mp4") is False  # small enough to play as it is
    assert prepare.needs_web_copy(info(1920, 1080, 10, 1), "a.mp4") is True  # 1080p
    assert prepare.needs_web_copy(info(720, 1280, 10, 12), "a.mp4") is True  # about 10 Mbps
