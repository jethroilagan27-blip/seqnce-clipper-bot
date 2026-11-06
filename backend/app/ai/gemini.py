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


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, max_retries: int = 3) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._max_retries = max(1, max_retries)

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
        )

        last_error = "unknown error"
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._client.models.generate_content(
                    model=self._model, contents=contents, config=config
                )
            except genai_errors.APIError as exc:
                code = getattr(exc, "code", None)
                last_error = f"HTTP {code}: {str(exc)[:200]}"
                if code in _RETRYABLE and attempt < self._max_retries:
                    delay = 4 * 2 ** (attempt - 1)  # 4s, 8s, ...
                    log.warning("gemini %s, retry %d in %ds", last_error, attempt, delay)
                    time.sleep(delay)
                    continue
                if code == 429:
                    raise AIError(
                        "The AI service is rate-limited right now (free-tier quota). Try again in a minute."
                    ) from exc
                if code in (400, 401, 403):
                    raise AIError(
                        "The AI service rejected the request. Check GEMINI_API_KEY and GEMINI_MODEL."
                    ) from exc
                raise AIError("The AI service is temporarily unavailable.") from exc
            except Exception as exc:  # network errors etc.
                last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                if attempt < self._max_retries:
                    time.sleep(2 * attempt)
                    continue
                raise AIError("Could not reach the AI service.") from exc

            usage = resp.usage_metadata
            if usage:
                log.info(
                    "gemini usage: model=%s images=%d prompt_tokens=%s output_tokens=%s",
                    self._model,
                    len(images or []),
                    usage.prompt_token_count,
                    usage.candidates_token_count,
                )

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


def make_gemini_provider() -> GeminiProvider | None:
    cfg = get_settings()
    if not cfg.gemini_api_key:
        return None
    return GeminiProvider(cfg.gemini_api_key, cfg.gemini_model, cfg.ai_max_retries)
