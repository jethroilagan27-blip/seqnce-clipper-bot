"""Caption pages (few words at a time, big and centred) written as an ASS file.

Word times come from Whisper in *source* time; we remap them onto the output
timeline through the cut list so captions stay in sync after cutting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from .cuts import Cut

SENTENCE_END = re.compile(r"[.!?…]$")
MAX_GAP_S = 0.6  # a pause longer than this starts a new caption page
MIN_PAGE_S = 0.4
HOLD_S = 0.15  # keep a page up briefly after its last word


@dataclass
class Page:
    start: float  # output time (s)
    end: float
    text: str


def remap_words(words: Sequence[dict[str, Any]], cuts: Sequence[Cut]) -> list[dict[str, Any]]:
    """Source-time words -> output-time words (words outside every cut are dropped)."""
    out: list[dict[str, Any]] = []
    for w in words:
        mid = (w["start"] + w["end"]) / 2
        for c in cuts:
            if c.start <= mid <= c.end:
                s = c.out_start + max(w["start"], c.start) - c.start
                e = c.out_start + min(w["end"], c.end) - c.start
                out.append({"start": s, "end": max(e, s + 0.05), "word": w["word"]})
                break
    return out


def build_pages(words: Sequence[dict[str, Any]], max_words: int) -> list[Page]:
    groups: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    for w in words:
        if cur and (
            len(cur) >= max_words
            or w["start"] - cur[-1]["end"] > MAX_GAP_S
            or SENTENCE_END.search(cur[-1]["word"])
        ):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)

    pages: list[Page] = []
    for i, g in enumerate(groups):
        start = g[0]["start"]
        end = max(g[-1]["end"] + HOLD_S, start + MIN_PAGE_S)
        if i + 1 < len(groups):
            nxt = groups[i + 1][0]["start"]
            end = min(end, nxt) if nxt - g[-1]["end"] > HOLD_S else nxt  # no flicker, no overlap
        pages.append(Page(round(start, 2), round(end, 2), " ".join(w["word"] for w in g)))
    return pages


def _ts(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _escape(text: str) -> str:
    # ASS treats { } as override blocks and \ as escapes; keep the text literal.
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Arial,{size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,2,2,{mx},{mx},{mv},1
Style: Hook,Arial Black,{hsize},{hcolor},&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,{houtline},{hshadow},8,{mx},{mx},{hmv},1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""

# ASS colours are &HAABBGGRR (alpha, blue, green, red).
HOOK_ASS_COLORS = {
    "yellow": "&H0000E6FF",
    "white": "&H00FFFFFF",
    "red": "&H004B4BFF",
    "cyan": "&H00FFE600",
    "green": "&H0050E650",
    "pink": "&H00C864FF",
    "orange": "&H000096FF",
}

HOOK_FADE_IN_MS = 180
HOOK_FADE_OUT_MS = 300


@dataclass
class HookTitle:
    text: str
    color: str = "yellow"
    duration_s: float = 4.0


def render_ass(
    pages: Sequence[Page],
    width: int = 1080,
    height: int = 1920,
    hook: HookTitle | None = None,
    total: float | None = None,
) -> str:
    """Safe area: 8 % side margins; captions sit above the TikTok/Reels bottom UI and the
    hook sits below the top bar, in the upper part of the frame."""
    header = ASS_HEADER.format(
        w=width, h=height, size=round(width * 0.07), mx=round(width * 0.08), mv=round(height * 0.22),
        hsize=round(width * 0.105), hcolor=HOOK_ASS_COLORS.get(hook.color if hook else "yellow", HOOK_ASS_COLORS["yellow"]),
        houtline=round(width * 0.011), hshadow=round(width * 0.004), hmv=round(height * 0.115),
    )
    lines = [
        f"Dialogue: 0,{_ts(p.start)},{_ts(p.end)},Default,,0,0,0,,{_escape(p.text)}"
        for p in pages
    ]
    if hook and hook.text.strip():
        end = hook.duration_s if total is None else min(hook.duration_s, total)
        lines.append(
            f"Dialogue: 1,{_ts(0)},{_ts(end)},Hook,,0,0,0,,"
            f"{{\\fad({HOOK_FADE_IN_MS},{HOOK_FADE_OUT_MS})}}{_escape(hook.text.upper())}"
        )
    return header + "\n".join(lines) + "\n"
