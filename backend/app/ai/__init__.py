"""AI providers. Use `get_provider()`; it returns None when no key is configured."""

from __future__ import annotations

from .base import AIError, AIProvider, LabeledImage


def get_provider() -> AIProvider | None:
    from .gemini import make_gemini_provider  # lazy: keeps SDK import off hot paths

    return make_gemini_provider()


__all__ = ["AIError", "AIProvider", "LabeledImage", "get_provider"]
