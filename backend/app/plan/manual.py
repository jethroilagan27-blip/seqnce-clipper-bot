"""Hand edits to a plan (no AI): clips, hook text/colour/duration/on-off, captions on/off.

Everything is re-validated here, so a request can only ever produce a plan the editor can render.
"""

from __future__ import annotations

import copy
from typing import Any

from ..schemas import ManualEdit
from .schema import EditingPlan
from .text import clean_hook_text
from .validate import PlanValidationError, validate_manual_clips


class ManualEditError(ValueError):
    """User-safe message (shown in the UI)."""


def _same_clips(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> bool:
    return len(a) == len(b) and all(
        abs(x["start"] - y["start"]) < 0.005 and abs(x["end"] - y["end"]) < 0.005 for x, y in zip(a, b)
    )


def apply_manual_edit(
    plan: dict[str, Any], edit: ManualEdit, video_duration: float | None = None
) -> tuple[dict[str, Any], str]:
    """Return (new plan dict, short human description of what changed)."""
    new = copy.deepcopy(plan)
    parts: list[str] = []

    if edit.clips is not None:
        if video_duration is None:
            raise ManualEditError("The video length is unknown, so clips can't be edited.")
        try:
            clips = validate_manual_clips(edit.clips, video_duration)
        except PlanValidationError as exc:
            raise ManualEditError("Can't use that cut: " + "; ".join(exc.errors) + ".") from exc
        as_dicts = [c.model_dump() for c in clips]
        if not _same_clips(as_dicts, new["clips"]):
            n_old, n_new = len(new["clips"]), len(as_dicts)
            parts.append("edited the clips" + (f" ({n_old} → {n_new})" if n_old != n_new else ""))
        new["clips"] = as_dicts

    if edit.remove_clips:
        ids = set(edit.remove_clips)
        known = {c["id"] for c in new["clips"]}
        unknown = ids - known
        if unknown:
            raise ManualEditError("One of the clips you tried to remove doesn't exist any more.")
        kept = [c for c in new["clips"] if c["id"] not in ids]
        if not kept:
            raise ManualEditError("At least one clip has to stay in the video.")
        for i, c in enumerate(kept, 1):
            c["id"] = f"c{i}"
        new["clips"] = kept
        parts.append(f"removed {len(ids)} clip{'s' if len(ids) != 1 else ''}")

    hook = new["hook"]
    if edit.hook_text is not None:
        text = clean_hook_text(edit.hook_text)
        if not text:
            raise ManualEditError("The hook title can't be empty (use the hook switch to turn it off).")
        if text != hook["text"]:
            parts.append("changed the hook text")
        hook["text"] = text
        if edit.hook_enabled is None:
            hook["enabled"] = True
    if edit.hook_color is not None and edit.hook_color != hook["color"]:
        hook["color"] = edit.hook_color
        parts.append("changed the hook colour")
    if edit.hook_duration_s is not None and abs(edit.hook_duration_s - hook["duration_s"]) > 0.01:
        hook["duration_s"] = round(edit.hook_duration_s, 1)
        parts.append("changed how long the hook shows")
    if edit.hook_enabled is not None and edit.hook_enabled != hook["enabled"]:
        if edit.hook_enabled and not hook["text"]:
            raise ManualEditError("Type a hook title first.")
        hook["enabled"] = edit.hook_enabled
        parts.append("turned the hook " + ("on" if edit.hook_enabled else "off"))
    if edit.captions_enabled is not None and edit.captions_enabled != new["captions"]["enabled"]:
        new["captions"]["enabled"] = edit.captions_enabled
        parts.append("turned captions " + ("on" if edit.captions_enabled else "off"))

    # Dragged positions: a block moves only when both coordinates arrive; "reset" puts it back.
    for name, box, x, y in (
        ("caption", new["captions"], edit.caption_x, edit.caption_y),
        ("hook", hook, edit.hook_x, edit.hook_y),
    ):
        if (x is None) != (y is None):
            raise ManualEditError(f"Send both the horizontal and vertical position of the {name}.")
        if name in edit.reset_positions and (box.get("x") is not None or box.get("y") is not None):
            box["x"] = box["y"] = None
            parts.append(f"moved the {name} back to its usual spot")
        elif x is not None and y is not None and (box.get("x"), box.get("y")) != (round(x, 4), round(y, 4)):
            box["x"], box["y"] = round(x, 4), round(y, 4)
            parts.append(f"moved the {name}")

    if edit.texts is not None:
        old = new.get("texts", [])
        new["texts"] = [t.model_dump() for t in edit.texts]
        if new["texts"] != old:
            parts.append(f"edited the text ({len(old)} → {len(new['texts'])})" if len(old) != len(new["texts"]) else "edited the text")

    new["warnings"] = []  # warnings described the previous build; the editor adds fresh ones
    EditingPlan.model_validate(new)  # last line of defence
    return new, ("Edited by hand: " + ", ".join(parts)) if parts else "No changes"
