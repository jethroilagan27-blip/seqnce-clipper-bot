from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.services import frames as frames_svc
from tests.test_upload_flow import _upload, _wait_done


def test_select_frames_even_and_capped():
    fr = [frames_svc.Frame(i * 3.0, Path(f"f{i}.jpg")) for i in range(100)]
    chosen = frames_svc.select_frames(fr, 12)
    assert len(chosen) == 12
    assert chosen[0] is fr[0] and chosen[-1] is fr[-1]
    assert [c.time_s for c in chosen] == sorted(c.time_s for c in chosen)
    assert frames_svc.select_frames(fr[:5], 12) == fr[:5]
    assert frames_svc.select_frames(fr, 0) == []


def test_extract_frames_and_scenes(sample_video: Path, tmp_path: Path):
    frames = frames_svc.extract_frames(sample_video, tmp_path / "fr", interval_s=1.0, width=320)
    assert 2 <= len(frames) <= 4  # 3 s clip @ 1 fps
    assert frames[0].time_s == 0 and frames[1].time_s == 1.0
    assert all(f.path.stat().st_size > 500 for f in frames)
    assert isinstance(frames_svc.detect_scenes(sample_video, 0.35), list)


def test_full_analysis_without_ai_key_degrades_gracefully(client: TestClient, sample_video: Path):
    job_id = _upload(client, sample_video).json()["job_id"]
    job = _wait_done(client, job_id)
    assert job["status"] == "completed", job

    tr_file = get_settings().temp_dir / job_id / "transcript.json"
    data = json.loads(tr_file.read_text(encoding="utf-8"))
    assert data["language"] == "en"
    assert data["segments"][0]["text"] == "Hello world"
    assert data["segments"][0]["words"][1]["word"] == "world"

    analysis = client.get(f"/api/jobs/{job_id}/analysis").json()
    assert analysis["transcript"]["segments"][0]["start"] == 0.0
    assert analysis["visual"]["analysis_source"] == "fallback"
    assert analysis["visual"]["speaker_focus_x"] == 0.5
    assert analysis["visual"]["frames_sent_to_ai"] == 0
    assert str(get_settings().storage_dir) not in json.dumps(analysis)  # no server paths leak


def test_visual_analysis_with_ai_is_clamped_and_budgeted(
    client: TestClient, sample_video: Path, fake_provider
):
    job_id = _upload(client, sample_video).json()["job_id"]
    job = _wait_done(client, job_id)
    assert job["status"] == "completed", job

    visual = client.get(f"/api/jobs/{job_id}/analysis").json()["visual"]
    assert visual["analysis_source"] == "ai"
    assert visual["speaker_focus_x"] == 1.0  # model said 1.7 -> clamped
    vis_calls = [c for c in fake_provider.calls if c["model"] == "VisualAnalysis"]
    assert len(vis_calls) == 1  # exactly one AI call for the visual stage
    assert 1 <= vis_calls[0]["n_images"] <= get_settings().max_ai_frames
    assert visual["frames_sent_to_ai"] == vis_calls[0]["n_images"]


def test_ai_failure_does_not_kill_job(client: TestClient, sample_video: Path, monkeypatch: pytest.MonkeyPatch):
    from app.ai import AIError

    class Broken:
        name = "broken"

        def generate_structured(self, *a, **k):
            raise AIError("quota exceeded")

    monkeypatch.setattr("app.pipeline.visual.get_provider", lambda: Broken())
    job_id = _upload(client, sample_video).json()["job_id"]
    job = _wait_done(client, job_id)
    assert job["status"] == "completed"
    visual = client.get(f"/api/jobs/{job_id}/analysis").json()["visual"]
    assert visual["analysis_source"] == "fallback"
    assert visual["fallback_reason"] == "quota exceeded"


def test_no_speech_fails_clearly(client: TestClient, sample_video: Path, monkeypatch: pytest.MonkeyPatch):
    class Silent:
        def transcribe(self, *a, **k):
            from types import SimpleNamespace
            return iter([]), SimpleNamespace(language="en", language_probability=0.5, duration=3.0)

    monkeypatch.setattr("app.pipeline.transcribe._get_model", lambda: Silent())
    job = _wait_done(client, _upload(client, sample_video).json()["job_id"])
    assert job["status"] == "failed"
    assert "no speech" in job["error"].lower()


# ---------- live transcript while Whisper is still working ----------

class _SlowWhisper:
    """Yields three segments, pausing between them so a client can look in the middle."""

    def __init__(self, gate_after_first, release):
        self.gate_after_first, self.release = gate_after_first, release

    def transcribe(self, audio, **kwargs):
        from types import SimpleNamespace as NS

        def gen():
            for i, text in enumerate([" One.", " Two.", " Three."]):
                if i == 1:
                    self.gate_after_first.set()  # first segment has been produced and saved
                    assert self.release.wait(20)  # hold here until the test has looked
                w = [NS(start=i, end=i + 0.9, word=text)]
                yield NS(start=float(i), end=i + 1.0, text=text, words=w)

        return gen(), NS(language="en", language_probability=0.9, duration=3.0)


def test_transcript_is_available_while_transcribing(client: TestClient, sample_video: Path, monkeypatch):
    import threading

    first_done, release = threading.Event(), threading.Event()
    monkeypatch.setattr("app.pipeline.transcribe._get_model", lambda: _SlowWhisper(first_done, release))
    monkeypatch.setattr("app.pipeline.transcribe.PARTIAL_EVERY_S", 0.0)
    job_id = _upload(client, sample_video).json()["job_id"]
    try:
        assert first_done.wait(20), "transcription never started"
        mid = client.get(f"/api/jobs/{job_id}/analysis")
        assert mid.status_code == 200
        body = mid.json()
        assert body["partial"] is True and body["visual"] is None and body["plan"] is None
        assert [s["text"] for s in body["transcript"]["segments"]] == ["One."]
        assert body["transcript"]["language"] == "en" and body["transcript"]["duration"] == 3.0
        assert body["transcript"]["complete"] is False
        assert str(get_settings().storage_dir) not in json.dumps(body)
    finally:
        release.set()

    assert _wait_done(client, job_id)["status"] == "completed"
    final = client.get(f"/api/jobs/{job_id}/analysis").json()
    assert final["partial"] is False and [s["text"] for s in final["transcript"]["segments"]] == ["One.", "Two.", "Three."]


def test_no_partial_transcript_before_transcription_starts(client: TestClient, sample_video: Path):
    from app import db
    job_id = _upload(client, sample_video).json()["job_id"]
    _wait_done(client, job_id)
    db.update_job(job_id, status="running", stage="preparing", transcript_path=None)
    (get_settings().temp_dir / job_id / "transcript.partial.json").unlink(missing_ok=True)
    assert client.get(f"/api/jobs/{job_id}/analysis").status_code == 409
