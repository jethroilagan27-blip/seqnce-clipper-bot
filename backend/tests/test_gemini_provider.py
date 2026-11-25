"""The Gemini provider with a stand-in for the network: an answer that was cut off must never be used."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.ai import AIError, VideoInput, gemini
from app.ai.gemini import MAX_OUTPUT_TOKENS, GeminiProvider


class Reply(BaseModel):
    text: str = ""
    items: list[str] = []


def _response(finish: str, parsed: Reply | None, text: str = ""):
    return SimpleNamespace(
        usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=20),
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=finish))],
        parsed=parsed,
        text=text,
    )


def _provider(responses: list, monkeypatch: pytest.MonkeyPatch) -> tuple[GeminiProvider, list]:
    provider = GeminiProvider("test-key", "test-model", max_retries=2)
    calls: list = []

    def generate_content(model, contents, config):
        calls.append(config)
        return responses.pop(0)

    provider._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    monkeypatch.setattr("app.ai.gemini.time.sleep", lambda s: None)
    return provider, calls


def test_a_complete_answer_is_used_and_the_output_limit_is_asked_for(monkeypatch: pytest.MonkeyPatch):
    provider, calls = _provider([_response("STOP", Reply(text="hi"))], monkeypatch)
    assert provider.generate_structured("p", Reply).text == "hi"
    assert calls[0].max_output_tokens == MAX_OUTPUT_TOKENS >= 16384  # long scripts need long answers


def test_an_answer_cut_off_at_the_limit_is_not_used_even_if_half_of_it_parses(monkeypatch: pytest.MonkeyPatch):
    cut = _response("MAX_TOKENS", Reply(text="only the beginning"))
    provider, calls = _provider([cut, _response("STOP", Reply(text="the whole answer"))], monkeypatch)
    assert provider.generate_structured("p", Reply).text == "the whole answer"  # it asked again
    assert len(calls) == 2


def test_if_every_try_is_cut_off_the_user_is_told_to_send_less(monkeypatch: pytest.MonkeyPatch):
    provider, _ = _provider([_response("MAX_TOKENS", Reply(text="a")), _response("MAX_TOKENS", Reply(text="b"))], monkeypatch)
    with pytest.raises(AIError, match="too long"):
        provider.generate_structured("p", Reply)


# ---------- watching a video ----------

def _video_provider(monkeypatch: pytest.MonkeyPatch, states: list[str] | None = None, fail_upload: bool = False):
    provider = GeminiProvider("test-key", "test-model", max_retries=1)
    seen: dict = {"calls": [], "uploaded": [], "deleted": []}
    queue = list(states or ["ACTIVE"])

    def file_():
        state = queue.pop(0) if len(queue) > 1 else queue[0]
        return SimpleNamespace(name="files/abc", uri="https://files/abc", state=SimpleNamespace(name=state))

    def upload(file):
        if fail_upload:
            raise ConnectionError("no network for test-key")
        seen["uploaded"].append(file)
        return file_()

    def generate_content(model, contents, config):
        seen["calls"].append((contents, config))
        return _response("STOP", Reply(text="watched"))

    provider._client = SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content),
        files=SimpleNamespace(upload=upload, get=lambda name: file_(), delete=lambda name: seen["deleted"].append(name)),
    )
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    return provider, seen


def _video_file(tmp_path: Path) -> Path:
    video = tmp_path / "w.mp4"
    video.write_bytes(b"\x00" * 1000)
    return video


def test_a_small_video_travels_inside_the_request(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    provider, seen = _video_provider(monkeypatch)
    assert provider.generate_from_video("find it", Reply, VideoInput(_video_file(tmp_path), fps=4)).text == "watched"
    [(contents, config)] = seen["calls"]
    assert contents[0].inline_data.mime_type == "video/mp4" and contents[0].video_metadata.fps == 4 and contents[1] == "find it"
    assert config.media_resolution is None and seen["uploaded"] == []


def test_a_big_video_is_uploaded_waited_for_and_deleted_afterwards(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(gemini, "INLINE_VIDEO_BYTES", 100)
    video = _video_file(tmp_path)
    provider, seen = _video_provider(monkeypatch, states=["PROCESSING", "PROCESSING", "ACTIVE"])
    provider.generate_from_video("p", Reply, VideoInput(video, fps=1, low_resolution=True))
    [(contents, config)] = seen["calls"]
    assert contents[0].file_data.file_uri == "https://files/abc" and contents[0].video_metadata.fps == 1
    assert config.media_resolution.name == "MEDIA_RESOLUTION_LOW"
    assert seen["uploaded"] == [str(video)] and seen["deleted"] == ["files/abc"]


def test_a_video_google_cannot_read_or_receive_is_a_clear_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(gemini, "INLINE_VIDEO_BYTES", 100)
    video = _video_file(tmp_path)
    provider, seen = _video_provider(monkeypatch, states=["FAILED"])
    with pytest.raises(AIError, match="couldn't read"):
        provider.generate_from_video("p", Reply, VideoInput(video, fps=1))
    assert seen["calls"] == []
    provider, _ = _video_provider(monkeypatch, fail_upload=True)
    with pytest.raises(AIError, match="couldn't be sent") as info:
        provider.generate_from_video("p", Reply, VideoInput(video, fps=1))
    assert "test-key" not in str(info.value)
