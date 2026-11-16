"""Very long file names (typical for downloaded clips) must not lose their extension and get refused."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.filenames import keep_extension

from .test_studio import _new, make_clip, make_tone, png

LONG = ("The Greatest Showman Movie Clip - A Million Dreams (2018) Movieclips Coming Soon - Rotten Tomatoes Coming Soon "
        "(1080p, 60fps, best quality, from the official trailer channel)")


def test_a_long_name_is_shortened_but_keeps_its_extension():
    assert keep_extension("short.mp4") == "short.mp4"
    cut = keep_extension(LONG + ".mp4")
    assert len(cut) == 120 and cut.endswith(".mp4") and cut.startswith("The Greatest Showman")
    assert keep_extension("x" * 300) == "x" * 120  # no extension: plain cut
    assert keep_extension(("y" * 200) + "." + ("z" * 50)) == "y" * 120  # a dot far from the end is not an extension: plain cut
    assert keep_extension("a" * 130 + ".MOV").endswith(".MOV")
    assert len(keep_extension("é" * 200 + ".webm")) == 120


def test_studio_accepts_a_clip_with_a_very_long_name(client: TestClient, tmp_path: Path):
    pid = _new(client)
    data = make_clip(tmp_path / "c.mp4", "red", 1, audio=False).read_bytes()
    r = client.post(f"/api/studio/projects/{pid}/assets", files=[("files", (LONG + ".mp4", data, "video/mp4"))])
    assert r.status_code == 200 and r.json()["rejected"] == [], r.text
    name = r.json()["added"][0]["name"]
    assert name.endswith(".mp4") and len(name) == 120
    audio = make_tone(tmp_path / "t.wav").read_bytes()
    r = client.post(f"/api/studio/projects/{pid}/assets", files=[("files", (LONG + ".wav", audio, "audio/wav"))])
    assert r.json()["added"] and r.json()["added"][0]["kind"] == "audio"
    r = client.post(f"/api/studio/projects/{pid}/assets", files=[("files", (LONG + ".png", png(), "image/png"))])
    assert r.json()["added"] and r.json()["added"][0]["kind"] == "image"


def test_video_mode_accepts_a_long_name_and_still_refuses_other_types(client: TestClient, tmp_path: Path, sample_video: Path):
    data = sample_video.read_bytes()
    r = client.post("/api/videos/upload", files={"file": (LONG + ".mp4", data, "video/mp4")})
    assert r.status_code == 201, r.text
    job = client.get(f"/api/jobs/{r.json()['job_id']}").json()
    assert job["original_filename"].endswith(".mp4") and len(job["original_filename"]) <= 120
    assert client.post("/api/videos/upload", files={"file": (LONG + ".txt", data, "video/mp4")}).status_code == 415


def test_a_long_music_name_is_accepted_for_photo_mode(client: TestClient, tmp_path: Path):
    pid = client.post("/api/slideshows").json()["id"]
    tone = make_tone(tmp_path / "t.wav").read_bytes()
    r = client.post(f"/api/slideshows/{pid}/music", files={"file": (LONG + ".wav", tone, "audio/wav")})
    assert r.status_code == 200, r.text
    assert r.json()["music"]["name"].endswith(".wav")
