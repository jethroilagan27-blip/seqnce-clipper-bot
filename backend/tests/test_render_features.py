from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from tests.test_upload_flow import _upload, _wait_done


def _music(name="bed.wav"):
    d = get_settings().music_dir
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    subprocess.run([get_settings().ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=220:sample_rate=44100", "-t", "1", str(p)], check=True)
    return p


def _volume_db(path: Path) -> float:
    """Mean volume of a file in dB, via ffmpeg's volumedetect."""
    r = subprocess.run([get_settings().ffmpeg, "-hide_banner", "-i", str(path), "-vn", "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True)
    line = [l for l in r.stderr.splitlines() if "mean_volume" in l][0]
    return float(line.split("mean_volume:")[1].split("dB")[0])


def test_music_is_mixed_and_looped_under_speech(client: TestClient, sample_video: Path):
    _music()
    job_id = _upload(client, sample_video, background_music="true", music_track="bed.wav").json()["job_id"]
    job = _wait_done(client, job_id)
    assert job["status"] == "completed", job
    spec = (get_settings().temp_dir / job_id / "cuts.json").read_text()
    assert '"music": "bed.wav"' in spec  # a 1 s file was looped to cover the 3 s output
    assert (get_settings().temp_dir / job_id / "filter.txt").read_text().count("amix") == 1
    assert client.get(f"/api/jobs/{job_id}/result").json()["rendered"]["has_audio"] is True


def test_music_requested_but_missing_is_skipped_with_warning(client: TestClient, sample_video: Path):
    job_id = _upload(client, sample_video, background_music="true").json()["job_id"]
    job = _wait_done(client, job_id)
    assert job["status"] == "completed"
    plan = client.get(f"/api/jobs/{job_id}/analysis").json()["plan"]
    assert any("no music files" in w for w in plan["warnings"])


def test_music_track_name_cannot_escape_music_folder(client: TestClient, sample_video: Path):
    _music()
    secret = get_settings().storage_dir / "secret.wav"
    secret.write_bytes(b"x")
    job_id = _upload(client, sample_video, background_music="true", music_track="..\secret.wav").json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"
    spec = (get_settings().temp_dir / job_id / "cuts.json").read_text()
    assert "secret" not in spec and '"music": "bed.wav"' in spec  # unknown name -> safe default


def test_captions_off_means_no_subtitle_filter(client: TestClient, sample_video: Path):
    job_id = _upload(client, sample_video, captions="false").json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"
    t = get_settings().temp_dir / job_id
    assert "ass=" not in (t / "filter.txt").read_text() and not (t / "captions.ass").exists()


def test_captions_on_burns_in_ass_file(client: TestClient, sample_video: Path):
    job_id = _upload(client, sample_video).json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"
    t = get_settings().temp_dir / job_id
    assert "ass=captions.ass" in (t / "filter.txt").read_text()
    assert "Dialogue:" in (t / "captions.ass").read_text(encoding="utf-8")


def test_music_endpoint_lists_tracks(client: TestClient):
    assert client.get("/api/music").json() == {"tracks": []}
    _music("a.wav"); _music("b.wav")
    get_settings().music_dir.joinpath("notes.txt").write_text("ignore me")
    assert client.get("/api/music").json() == {"tracks": ["a.wav", "b.wav"]}


def test_retention_deletes_old_jobs_and_files(client: TestClient, sample_video: Path):
    from app import db
    from app.retention import purge_old_jobs

    job_id = _upload(client, sample_video).json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "completed"
    cfg = get_settings()
    out = cfg.outputs_dir / f"{job_id}.mp4"
    assert out.exists() and (cfg.temp_dir / job_id).exists()

    assert purge_old_jobs(7) == 0 and out.exists()  # fresh job is kept
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET updated_at = '2020-01-01T00:00:00+00:00' WHERE id = ?", (job_id,))
    assert purge_old_jobs(7) == 1
    assert not out.exists() and not (cfg.temp_dir / job_id).exists()
    assert not list(cfg.uploads_dir.iterdir())
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def _band_db(path: Path, hz: int) -> float:
    r = subprocess.run([get_settings().ffmpeg, "-hide_banner", "-i", str(path), "-vn", "-af",
                        f"bandpass=f={hz}:width_type=q:w=15,bandpass=f={hz}:width_type=q:w=15,volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    line = [l for l in r.stderr.splitlines() if "mean_volume" in l][0]
    return float(line.split("mean_volume:")[1].split("dB")[0])


def test_music_is_actually_audible_but_below_speech(client: TestClient, sample_video: Path):
    """The test clip's 'speech' is a 440 Hz tone and the music a 220 Hz tone, so energy
    at 220 Hz can only come from the music."""
    _music()
    outs = {}
    for label, form in (("plain", {}), ("music", {"background_music": "true", "music_track": "bed.wav"})):
        job_id = _upload(client, sample_video, **form).json()["job_id"]
        assert _wait_done(client, job_id)["status"] == "completed"
        outs[label] = get_settings().outputs_dir / f"{job_id}.mp4"

    music_220 = _band_db(outs["music"], 220)
    plain_220 = _band_db(outs["plain"], 220)
    speech_440 = _band_db(outs["music"], 440)
    assert music_220 > plain_220 + 20, (music_220, plain_220)  # clearly present
    assert music_220 < speech_440 - 8, (music_220, speech_440)  # but well under the speech
