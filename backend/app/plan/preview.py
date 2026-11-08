"""Everything the browser needs to preview an edit without rendering it.

The numbers come from the *same* functions the renderer uses (build_cuts, remap_words,
build_pages), so the live preview and the final video cut at the same places and show the
same caption pages. Pure function: no files, no FFmpeg.
"""

from __future__ import annotations

from typing import Any

from ..editing import captions as cap
from ..editing import cuts as cuts_mod
from .schema import EditingPlan


def _pos(x: float | None, y: float | None) -> dict[str, float] | None:
    return {"x": x, "y": y} if x is not None and y is not None else None


def build_spec(plan: EditingPlan, transcript: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    duration = float(meta["duration"])
    words = cuts_mod.flatten_words(transcript)
    cuts = cuts_mod.build_cuts(plan, words, duration)
    total = cuts_mod.total_duration(cuts)

    pages: list[dict[str, Any]] = []
    if plan.captions.enabled and cuts:
        pages = [
            {"start": p.start, "end": p.end, "text": p.text}
            for p in cap.build_pages(cap.remap_words(words, cuts), plan.captions.max_words_per_line)
        ]

    hook = plan.hook
    return {
        "total": round(total, 3),
        "cuts": [{"start": c.start, "end": c.end, "out_start": c.out_start} for c in cuts],
        "pages": pages,
        "captions_enabled": plan.captions.enabled,
        "captions_pos": _pos(plan.captions.x, plan.captions.y),
        "hook": {
            "enabled": hook.enabled and bool(hook.text.strip()),
            "text": hook.text,
            "color": hook.color,
            "duration_s": min(hook.duration_s, total) if total else hook.duration_s,
            "pos": _pos(hook.x, hook.y),
        },
        "texts": [t.model_dump() for t in plan.texts],
        "reframe": {"strategy": plan.reframe.strategy, "focus_x": plan.reframe.focus_x},
        "source": {"width": int(meta["width"]), "height": int(meta["height"]), "duration": duration},
        "clips": [c.model_dump() for c in plan.clips],
    }
