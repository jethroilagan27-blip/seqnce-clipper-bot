"""Shortening file names for labels without breaking them."""

from __future__ import annotations


def keep_extension(name: str, limit: int = 120) -> str:
    """Shorten a long file name to at most `limit` characters but keep its extension.

    Downloaded clips often have names of 150+ characters ("... (1080p, 60fps).mp4"). Cutting such a name at a fixed
    length throws away the ".mp4" at the end, and the file is then refused as "not a video"."""
    if len(name) <= limit:
        return name
    dot = name.rfind(".")
    ext = name[dot:] if dot > 0 and len(name) - dot <= 12 else ""
    return name[: max(limit - len(ext), 1)] + ext
