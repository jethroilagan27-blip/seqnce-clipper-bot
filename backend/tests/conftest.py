from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ai.schemas import PlanProposal, ProposedClip, RevisionProposal, VisualAnalysis
from app.config import get_settings


class FakeWhisper:
    """Stands in for faster-whisper so tests are fast and need no model download."""

    def transcribe(self, audio, **kwargs):
        words = [SimpleNamespace(start=0.0, end=1.5, word=" Hello"),
                 SimpleNamespace(start=1.5, end=3.0, word=" world")]
        seg = SimpleNamespace(start=0.0, end=3.0, text=" Hello world", words=words)
        info = SimpleNamespace(language="en", language_probability=0.99, duration=3.0)
        return iter([seg]), info


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.calls: list[dict] = []
        self.plan_responses: list[PlanProposal] = []  # consumed in order by plan requests
        self.revision_responses: list[RevisionProposal] = []  # consumed in order by revision requests
        self.revision_error: Exception | None = None  # raised by revision requests when set

    def generate_structured(self, prompt, response_model, images=None):
        self.calls.append({"prompt": prompt, "n_images": len(images or []), "model": response_model.__name__})
        if response_model is RevisionProposal:
            if self.revision_error:
                raise self.revision_error
            return self.revision_responses.pop(0)
        if response_model is PlanProposal:
            if self.plan_responses:
                return self.plan_responses.pop(0)
            return PlanProposal(
                main_subject="business automation", main_message="Automate small, keep humans in charge.",
                clips=[ProposedClip(start=0.0, end=3.0, purpose="hook", reason="x")],
            )
        return VisualAnalysis(
            main_subject="a person speaking",
            speaker_visible=True,
            framing="medium",
            speaker_focus_x=1.7,  # out of range on purpose: must be clamped
            suitable_for_vertical=True,
            notable_moments=[],
        )


@pytest.fixture
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    prov = FakeProvider()
    monkeypatch.setattr("app.pipeline.visual.get_provider", lambda: prov)
    monkeypatch.setattr("app.pipeline.planner.get_provider", lambda: prov)
    monkeypatch.setattr("app.pipeline.revise.get_provider", lambda: prov)
    return prov


@pytest.fixture
def client(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """App wired to a throwaway storage dir; worker runs for real.

    Whisper is faked; the AI provider defaults to 'none configured' (override
    with the `fake_provider` fixture).
    """
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("MAX_UPLOAD_MB", "50" if request.node.get_closest_marker("real_whisper") else "5")
    live = bool(request.node.get_closest_marker("live_ai"))
    if not live:
        monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()

    if not request.node.get_closest_marker("real_whisper"):
        monkeypatch.setattr("app.pipeline.transcribe._get_model", lambda: FakeWhisper())
    if not live:
        monkeypatch.setattr("app.pipeline.visual.get_provider", lambda: None)
        monkeypatch.setattr("app.pipeline.planner.get_provider", lambda: None)

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


def _make_video(path: Path, *, audio: bool, seconds: int = 3) -> Path:
    cfg = get_settings()
    cmd = [cfg.ffmpeg, "-y", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25"]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100"]
    cmd += ["-t", str(seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    return _make_video(tmp_path / "sample.mp4", audio=True)


@pytest.fixture
def silent_video(tmp_path: Path) -> Path:
    return _make_video(tmp_path / "silent.mp4", audio=False)
