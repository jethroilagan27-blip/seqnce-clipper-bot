"""The Gemini provider with a stand-in for the network: an answer that was cut off must never be used."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import errors
from pydantic import BaseModel

from app.ai import AIError, AIQuotaError, VideoInput, gemini
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


# ---------- the backup key ----------

def _client(outcomes: list, seen: list, name: str):
    """A stand-in client: each outcome is an HTTP error code or a reply."""

    def generate_content(model, contents, config):
        seen.append(name)
        result = outcomes.pop(0)
        if isinstance(result, int):
            raise errors.ClientError(result, {"error": {"message": "nope"}})
        return result

    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


def _pair(monkeypatch: pytest.MonkeyPatch, first: list, second: list, retries: int = 3) -> tuple[GeminiProvider, list]:
    provider = GeminiProvider("first-key", "m", max_retries=retries, backup_key="second-key")
    seen: list = []
    provider._client = _client(first, seen, "first")
    provider._backup._client = _client(second, seen, "backup")
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    return provider, seen


def _ok(text: str):
    return _response("STOP", Reply(text=text))


def test_the_backup_is_not_touched_while_the_first_key_works(monkeypatch: pytest.MonkeyPatch):
    provider, seen = _pair(monkeypatch, [_ok("a")], [])
    assert provider.generate_structured("p", Reply).text == "a" and seen == ["first"]


def test_at_the_limit_the_backup_answers_at_once_and_the_first_is_tried_again_next_time(monkeypatch: pytest.MonkeyPatch):
    provider, seen = _pair(monkeypatch, [429, _ok("first again")], [_ok("from backup")])
    assert provider.generate_structured("p", Reply).text == "from backup"
    assert seen == ["first", "backup"]  # no waiting and retrying on the full key
    assert provider.generate_structured("p", Reply).text == "first again"
    assert seen[-1] == "first"


@pytest.mark.parametrize("code", [400, 401, 403, 500, 503])
def test_other_problems_do_not_use_the_backup(monkeypatch: pytest.MonkeyPatch, code: int):
    provider, seen = _pair(monkeypatch, [code, code, code], [_ok("should not be used")])
    with pytest.raises(AIError):
        provider.generate_structured("p", Reply)
    assert "backup" not in seen


def test_when_both_are_at_the_limit_the_user_is_told(monkeypatch: pytest.MonkeyPatch):
    provider, seen = _pair(monkeypatch, [429], [429, 429, 429])
    with pytest.raises(AIQuotaError, match="rate-limited"):
        provider.generate_structured("p", Reply)
    assert seen == ["first", "backup", "backup", "backup"]


def test_a_rejected_backup_key_is_named(monkeypatch: pytest.MonkeyPatch):
    provider, _ = _pair(monkeypatch, [429], [401])
    with pytest.raises(AIError, match="GEMINI_API_KEY_BACKUP") as info:
        provider.generate_structured("p", Reply)
    assert "second-key" not in str(info.value)


def test_without_a_backup_the_limit_is_retried_then_reported(monkeypatch: pytest.MonkeyPatch):
    provider = GeminiProvider("first-key", "m", max_retries=2)
    seen: list = []
    provider._client = _client([429, 429], seen, "first")
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    with pytest.raises(AIQuotaError):
        provider.generate_structured("p", Reply)
    assert seen == ["first", "first"]
    assert GeminiProvider("same", "m", backup_key="same")._backup is None  # the same key twice is no backup


def test_a_video_is_sent_again_with_the_backup_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(gemini, "INLINE_VIDEO_BYTES", 100)  # through the file store, which belongs to one key
    first, first_seen = _video_provider(monkeypatch)
    second, second_seen = _video_provider(monkeypatch)

    def full(model, contents, config):
        raise errors.ClientError(429, {"error": {"message": "quota"}})

    first._client.models = SimpleNamespace(generate_content=full)
    first._backup = second
    assert first.generate_from_video("p", Reply, VideoInput(_video_file(tmp_path), fps=1)).text == "watched"
    assert len(first_seen["uploaded"]) == 1 and first_seen["deleted"] == ["files/abc"]  # tidied up
    assert len(second_seen["uploaded"]) == 1 and len(second_seen["calls"]) == 1  # uploaded afresh with the backup


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
