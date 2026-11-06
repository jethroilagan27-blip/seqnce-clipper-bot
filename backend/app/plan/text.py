"""Cleaning of free text that comes from the user or the AI before it is stored or rendered."""

from __future__ import annotations

import re

MAX_INSTRUCTIONS = 500
MAX_HOOK_WORDS = 8
MAX_HOOK_CHARS = 60

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_SPACES = re.compile(r"\s+")
# Letters/digits in any language plus plain punctuation. Emoji and symbols are dropped because the
# burned-in font cannot draw them (they would show up as empty boxes).
_HOOK_ALLOWED = re.compile(r"[^\w\s'\"!?.,:;%$&+\-–—…#@()/]")


def clean_instructions(raw: str | None) -> str:
    """User request for the AI editor: plain single-spaced text, length-capped."""
    text = _SPACES.sub(" ", _CONTROL.sub(" ", raw or "")).strip()
    return text[:MAX_INSTRUCTIONS]


def clean_hook_text(raw: str | None) -> str:
    """Hook title: no symbols the font can't draw, at most 8 words / 60 chars. May return ''."""
    text = _HOOK_ALLOWED.sub("", _CONTROL.sub(" ", raw or ""))
    text = _SPACES.sub(" ", text).strip()
    words = text.split(" ")[:MAX_HOOK_WORDS] if text else []
    text = " ".join(words)
    if len(text) > MAX_HOOK_CHARS:
        text = text[:MAX_HOOK_CHARS].rsplit(" ", 1)[0]
    return text.strip(" -–—,;:")
