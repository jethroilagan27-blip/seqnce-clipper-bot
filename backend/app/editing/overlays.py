"""Free text laid over a video: typed by the user, placed by dragging.

Shared by video mode (extra texts on a short) and photo mode (slideshows), so it lives with the
other editing code and depends on nothing mode-specific. Positions are fractions of the frame
(0..1, the *centre* of the text) and sizes are a percentage of the frame width, so the same numbers
describe the browser preview and the rendered file at any resolution.
"""

from __future__ import annotations

import re
import textwrap
from typing import Literal, Sequence

from pydantic import BaseModel, Field, field_validator

MAX_TEXTS = 30
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_CONTROL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")  # everything except newline

# Average glyph width of a bold sans font relative to its size; the browser preview and the renderer
# wrap with the same estimate so a text breaks at about the same place in both.
CHAR_WIDTH = 0.56
MAX_LINE_FRACTION = 0.9  # a line may use at most 90 % of the frame width


class TextOverlay(BaseModel):
    id: str = Field(max_length=40)
    text: str = Field(min_length=1, max_length=200)
    x: float = Field(default=0.5, ge=0, le=1)
    y: float = Field(default=0.2, ge=0, le=1)
    size: float = Field(default=7, ge=2, le=25)  # % of the frame width
    color: str = "#ffffff"
    style: Literal["outline", "box", "plain"] = "outline"
    bold: bool = True
    start: float = Field(default=0, ge=0)  # seconds in the finished video
    end: float | None = Field(default=None, gt=0)  # None = until the end
    fade: bool = True

    @field_validator("color")
    @classmethod
    def _color(cls, v: str) -> str:
        if not _HEX.match(v):
            raise ValueError("color must look like #RRGGBB")
        return v.lower()

    @field_validator("text")
    @classmethod
    def _text(cls, v: str) -> str:
        cleaned = _CONTROL.sub(" ", v).strip()
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        if not cleaned:
            raise ValueError("text can't be empty")
        return cleaned


def chars_per_line(size_pct: float) -> int:
    return max(4, int(MAX_LINE_FRACTION * 100 / (size_pct * CHAR_WIDTH)))


def wrap_text(text: str, size_pct: float) -> str:
    """Break lines the way the preview does (explicit newlines are kept)."""
    width = chars_per_line(size_pct)
    lines: list[str] = []
    for paragraph in text.split("\n"):
        lines.extend(textwrap.wrap(paragraph, width=width, break_long_words=True) or [""])
    return "\n".join(lines)


def hex_to_ass(color: str, alpha: int = 0) -> str:
    """#RRGGBB -> ASS &HAABBGGRR."""
    r, g, b = color[1:3], color[3:5], color[5:7]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ts(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _escape(text: str) -> str:
    # ASS treats { } as override blocks and \ as escapes; keep the text literal.
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def ass_text_lines(texts: Sequence[TextOverlay], width: int, height: int, total: float) -> list[str]:
    """ASS "Dialogue:" lines for the overlays (layer 2, above captions and the hook)."""
    lines: list[str] = []
    for t in texts:
        start = min(t.start, total)
        end = min(t.end if t.end is not None else total, total)
        if end - start < 0.05:
            continue  # starts after the video ends
        size_px = max(8, round(t.size / 100 * width))
        tags = [
            "\\an5",
            f"\\pos({t.x * width:.0f},{t.y * height:.0f})",
            f"\\fs{size_px}",
            f"\\c{hex_to_ass(t.color)}",
            f"\\b{1 if t.bold else 0}",
        ]
        if t.style == "plain":
            tags += ["\\bord0", "\\shad0"]
        elif t.style == "box":
            tags += [f"\\bord{max(4, round(size_px * 0.28))}", "\\shad0"]
        else:
            tags += [f"\\bord{max(2, round(size_px * 0.09))}", f"\\shad{max(1, round(size_px * 0.03))}"]
        if t.fade:
            tags.append("\\fad(150,150)")
        style = "TextBox" if t.style == "box" else "TextOutline"
        body = _escape(wrap_text(t.text, t.size))
        lines.append(f"Dialogue: 2,{_ts(start)},{_ts(end)},{style},,0,0,0,,{{{''.join(tags)}}}{body}")
    return lines
