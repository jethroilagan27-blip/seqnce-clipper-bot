"""What changed between two editing plans (shown to the user after every revision).

Pure functions over plan dicts, so the result can be stored with the version and
unit-tested without any video.
"""

from __future__ import annotations

from typing import Any

SAME_EDGE_S = 0.25  # edges within this are "the same cut"
MATCH_OVERLAP = 0.5  # a new clip matches an old one if they overlap by this share of the shorter one


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> float:
    return max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))


def _clip_view(c: dict[str, Any]) -> dict[str, Any]:
    return {"id": c["id"], "start": c["start"], "end": c["end"], "purpose": c["purpose"], "reason": c.get("reason", "")}


def diff_clips(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chronological list of clips with a status: kept | trimmed | added | removed.

    `trimmed` entries carry `before` = the old start/end. `removed` entries are old clips
    that no longer overlap anything in the new plan.
    """
    matched_old: set[int] = set()
    rows: list[dict[str, Any]] = []
    for n in new:
        best, best_ov = None, 0.0
        for i, o in enumerate(old):
            ov = _overlap(n, o)
            if ov > best_ov:
                best, best_ov = i, ov
        view = _clip_view(n)
        if best is not None and best_ov >= MATCH_OVERLAP * min(n["end"] - n["start"], old[best]["end"] - old[best]["start"]):
            matched_old.add(best)
            o = old[best]
            if abs(o["start"] - n["start"]) <= SAME_EDGE_S and abs(o["end"] - n["end"]) <= SAME_EDGE_S:
                view["status"] = "kept"
            else:
                view["status"] = "trimmed"
                view["before"] = {"start": o["start"], "end": o["end"]}
        else:
            view["status"] = "added"
        rows.append(view)
    for i, o in enumerate(old):
        if i not in matched_old:
            view = _clip_view(o)
            view["status"] = "removed"
            rows.append(view)
    rows.sort(key=lambda r: (r["start"], r["end"]))
    return rows


def _settings_changes(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, str]]:
    def hook(p: dict[str, Any]) -> tuple[bool, str, str]:
        h = p.get("hook") or {}
        return bool(h.get("enabled")), h.get("text", ""), h.get("color", "")

    out: list[dict[str, str]] = []
    (oe, ot, oc), (ne, nt, nc) = hook(old), hook(new)
    if oe != ne:
        out.append({"field": "Hook title", "before": "on" if oe else "off", "after": "on" if ne else "off"})
    if ne and ot != nt:
        out.append({"field": "Hook text", "before": ot or "—", "after": nt})
    if ne and oc != nc:
        out.append({"field": "Hook colour", "before": oc, "after": nc})
    ocap = bool((old.get("captions") or {}).get("enabled"))
    ncap = bool((new.get("captions") or {}).get("enabled"))
    if ocap != ncap:
        out.append({"field": "Captions", "before": "on" if ocap else "off", "after": "on" if ncap else "off"})
    if old.get("target_duration") != new.get("target_duration"):
        out.append({
            "field": "Target length",
            "before": f"{old.get('target_duration')}s",
            "after": f"{new.get('target_duration')}s",
        })
    return out


def diff_plans(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    clips = diff_clips(old.get("clips", []), new.get("clips", []))
    settings = _settings_changes(old, new)
    counts = {k: sum(1 for c in clips if c["status"] == k) for k in ("kept", "trimmed", "added", "removed")}
    return {
        "clips": clips,
        "settings": settings,
        "counts": counts,
        "unchanged": not settings and counts["trimmed"] == counts["added"] == counts["removed"] == 0,
        "old_total": round(sum(c["end"] - c["start"] for c in old.get("clips", [])), 1),
        "new_total": round(sum(c["end"] - c["start"] for c in new.get("clips", [])), 1),
    }
