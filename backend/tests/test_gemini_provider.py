"""The Gemini provider with a stand-in for the network: an answer that was cut off must never be used."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.ai import AIError
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
