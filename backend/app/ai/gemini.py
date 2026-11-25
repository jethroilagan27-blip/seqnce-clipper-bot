"""Google Gemini implementation of AIProvider (google-genai SDK)."""

from __future__ import annotations

import logging
import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import ValidationError

from ..config import get_settings
from .base import AIError, LabeledImage, T

log = logging.getLogger(__name__)

_RETRYABLE = {429, 500, 502, 503, 504}
MAX_OUTPUT_TOKENS = 32768


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, max_retries: int = 3, own_key: bool = False) -> None:
        self._client = genai.Client(api_key=api_key)
        self._api_key = api_key
        self._model = model
        self._max_retries = max(1, max_retries)
        self._own_key = own_key  # the key belongs to the person asking: error texts point them to the Me page

    def _scrub(self, text: str) -> str:
        """Never let the key reach a log line or an error message."""
        return text.replace(self._api_key, "[key]") if self._api_key else text

    def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        images: list[LabeledImage] | None = None,
    ) -> T:
        contents: list[types.Part | str] = []
        for img in images or []:
            contents.append(img.label)
            contents.append(types.Part.from_bytes(data=img.jpeg, mime_type="image/jpeg"))
        contents.append(prompt)

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=response_model,
            temperature=0.2,
            max_output_tokens=MAX_OUTPUT_TOKENS,  # long scripts need a long answer (and "thinking" models spend tokens before it)
        )

        last_error = "unknown error"
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._client.models.generate_content(
                    model=self._model, contents=contents, config=config
                )
            except genai_errors.APIError as exc:
                code = getattr(exc, "code", None)
                last_error = self._scrub(f"HTTP {code}: {str(exc)[:200]}")
                if code in _RETRYABLE and attempt < self._max_retries:
                    delay = 4 * 2 ** (attempt - 1)  # 4s, 8s, ...
                    log.warning("gemini %s, retry %d in %ds", last_error, attempt, delay)
                    time.sleep(delay)
                    continue
                if code == 429:
                    raise AIError(
                        "Your Gemini key has used up its quota for now (the free tier has limits). Try again in a minute."
                        if self._own_key
                        else "The AI service is rate-limited right now (free-tier quota). Try again in a few minutes, or tomorrow if today's limit is used up."
                    ) from exc
                if code in (400, 401, 403):
                    raise AIError(
                        "Google rejected your Gemini key. Check it on the Me page."
                        if self._own_key
                        else "The AI service rejected the request. Check GEMINI_API_KEY and GEMINI_MODEL."
                    ) from exc
                raise AIError("The AI service is temporarily unavailable.") from exc
            except Exception as exc:  # network errors etc.
                last_error = self._scrub(f"{type(exc).__name__}: {str(exc)[:200]}")
                if attempt < self._max_retries:
                    time.sleep(2 * attempt)
                    continue
                raise AIError("Could not reach the AI service.") from exc

            finish = getattr(resp.candidates[0], "finish_reason", None) if resp.candidates else None
            finish_name = str(getattr(finish, "name", finish) or "")
            usage = resp.usage_metadata
            if usage:
                log.info(
                    "gemini usage: model=%s images=%d prompt_tokens=%s output_tokens=%s finish=%s",
                    self._model,
                    len(images or []),
                    usage.prompt_token_count,
                    usage.candidates_token_count,
                    finish_name,
                )

            if finish_name == "MAX_TOKENS":
                # The answer was cut off: whatever was parsed from it is only the beginning. Never use half an answer.
                last_error = "the answer was cut off (too long)"
                log.warning("gemini answer cut off at the output limit (attempt %d)", attempt)
                if attempt < self._max_retries:
                    continue
                raise AIError("The AI's answer was too long and got cut off. Try a shorter request, or send it in parts.")

            parsed = resp.parsed
            if isinstance(parsed, response_model):
                return parsed
            # Fallback: parse the raw text ourselves.
            try:
                return response_model.model_validate_json(resp.text or "")
            except (ValidationError, ValueError) as exc:
                last_error = f"unparseable output: {str(exc)[:200]}"
                log.warning("gemini returned invalid JSON (attempt %d): %s", attempt, last_error)
                if attempt < self._max_retries:
                    continue
                raise AIError("The AI returned an unreadable answer.") from exc

        raise AIError(f"The AI request failed ({last_error}).")


def check_key(api_key: str) -> None:
    """Ask Google whether this key works (a free call that lists nothing of ours). Raises AIError with a message fit to show."""
    client = genai.Client(api_key=api_key)  # kept in a variable: a temporary one is closed before the call is made
    try:
        client.models.get(model=get_settings().gemini_model)
    except genai_errors.APIError as exc:
        code = getattr(exc, "code", None)
        if code in (400, 401, 403):
            raise AIError("Google says that key isn't valid. Copy it again from Google AI Studio.") from None
        if code == 429:
            return  # a real key that is simply busy right now
        raise AIError("Google's service had a problem checking the key. Try again in a moment.") from None
    except Exception:
        raise AIError("Couldn't reach Google to check the key. Try again in a moment.") from None
