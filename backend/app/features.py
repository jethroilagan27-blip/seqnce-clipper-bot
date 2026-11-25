"""Per-account features: a plan (standard / pro / max) plus overrides for one account.

Every account has a plan. A plan is just a set of values for the features below. An account can also carry
overrides (set with `python -m app.admin set-feature`), so one customer can get "pro, but with 1080p and
10 renders a day" without a new plan. Admins, and everyone when accounts are off (local use), get the
"max" plan with no daily render limit.

THE NUMBERS BELOW ARE STARTING VALUES. Pricing and what each plan includes are still to be decided:
change them here, in one place, and nothing else needs to change.

The server checks these on every request (see auth.require_feature and the studio API); the website only
uses them to hide or lock things.
"""

from __future__ import annotations

from typing import Any

# key -> (type, what it means). The order is the order the admin command prints them.
FEATURES: dict[str, tuple[type, str]] = {
    "studio": (bool, "Studio mode (multi-scene projects with voice-overs, titles and transitions)"),
    "studio_max_projects": (int, "Studio projects kept at once"),
    "studio_max_scenes": (int, "Scenes in one Studio project"),
    "studio_max_minutes": (int, "Longest finished Studio video, in minutes"),
    "studio_max_height": (int, "Highest Studio video quality in pixels of height (720 or 1080)"),
    "studio_max_assets": (int, "Clips, audio files and pictures in one Studio project"),
    "studio_max_storage_mb": (int, "Total size of the files in one Studio project, in MB"),
    "studio_max_file_mb": (int, "Biggest single file in a Studio project, in MB"),
    "studio_renders_per_day": (int, "Finished Studio videos per rolling 24 hours (previews are free)"),
    "studio_crossfade": (bool, "Cross-fade between scenes (fade through black is always there)"),
    "studio_text_effects": (bool, "Title zoom animation and font choice"),
    "studio_overlays": (bool, "Pictures and clips popping up over a scene, highlights, pins, the narrow-frame opening"),
    "studio_grid": (bool, "Several clips on screen at once (for example the 3x2 grid of members)"),
    "studio_credits": (bool, "Rolling credits"),
    "studio_ducking": (bool, "Music that lowers by itself while someone speaks"),
    "studio_auto_montage": (bool, "Spread clips or pictures evenly under a voice-over"),
    "studio_custom_fonts": (bool, "Upload your own font files for titles"),
    "studio_ai_chat": (bool, "The AI assistant that builds and changes scenes from a script (uses the daily chat limit)"),
}

PLAN_NAMES = ("standard", "pro", "max")

PLANS: dict[str, dict[str, Any]] = {
    "standard": {
        "studio": False,
        "studio_max_projects": 1,
        "studio_max_scenes": 8,
        "studio_max_minutes": 2,
        "studio_max_height": 720,
        "studio_max_assets": 30,
        "studio_max_storage_mb": 500,
        "studio_max_file_mb": 300,
        "studio_renders_per_day": 2,
        "studio_crossfade": False,
        "studio_text_effects": False,
        "studio_overlays": False,
        "studio_grid": False,
        "studio_credits": False,
        "studio_ducking": False,
        "studio_auto_montage": False,
        "studio_custom_fonts": False,
        "studio_ai_chat": False,
    },
    "pro": {
        "studio": True,
        "studio_max_projects": 5,
        "studio_max_scenes": 30,
        "studio_max_minutes": 6,
        "studio_max_height": 1080,
        "studio_max_assets": 120,
        "studio_max_storage_mb": 4000,
        "studio_max_file_mb": 800,
        "studio_renders_per_day": 5,
        "studio_crossfade": True,
        "studio_text_effects": True,
        "studio_overlays": True,
        "studio_grid": True,
        "studio_credits": True,
        "studio_ducking": True,
        "studio_auto_montage": True,
        "studio_custom_fonts": True,
        "studio_ai_chat": True,
    },
    "max": {
        "studio": True,
        "studio_max_projects": 20,
        "studio_max_scenes": 100,
        "studio_max_minutes": 20,
        "studio_max_height": 1080,
        "studio_max_assets": 400,
        "studio_max_storage_mb": 20000,
        "studio_max_file_mb": 1500,
        "studio_renders_per_day": 20,
        "studio_crossfade": True,
        "studio_text_effects": True,
        "studio_overlays": True,
        "studio_grid": True,
        "studio_credits": True,
        "studio_ducking": True,
        "studio_auto_montage": True,
        "studio_custom_fonts": True,
        "studio_ai_chat": True,
    },
}
DEFAULT_PLAN = "standard"

# Videos and AI chat messages per rolling 24 hours. None = the server's own default (DAILY_VIDEO_LIMIT and
# DAILY_CHAT_LIMIT). A limit set for one account (admin page, or `set-limits`) comes before these.
PLAN_LIMITS: dict[str, dict[str, int | None]] = {
    "standard": {"video": None, "chat": None},
    "pro": {"video": 15, "chat": 100},
    "max": {"video": 50, "chat": 300},
}

_TRUE = {"true", "on", "yes", "1"}
_FALSE = {"false", "off", "no", "0"}


def parse_value(key: str, raw: Any) -> Any:
    """A feature value from text (admin command) or JSON. Raises ValueError with a message fit to show."""
    if key not in FEATURES:
        raise ValueError(f"Unknown feature {key!r}. Features: {', '.join(FEATURES)}.")
    kind = FEATURES[key][0]
    if kind is bool:
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ValueError(f"{key} is on or off.")
    if isinstance(raw, bool):
        raise ValueError(f"{key} is a number.")
    try:
        number = int(str(raw).strip())
    except ValueError:
        raise ValueError(f"{key} is a whole number.") from None
    if number < 0 or number > 1_000_000:
        raise ValueError(f"{key} must be between 0 and 1000000.")
    return number


def clean_overrides(raw: Any) -> dict[str, Any]:
    """Overrides read back from the database: drop anything unknown or broken instead of failing."""
    out: dict[str, Any] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                out[key] = parse_value(key, value)
            except ValueError:
                continue
    return out


def resolve(plan: str | None, overrides: Any = None, *, admin: bool = False) -> dict[str, Any]:
    """The features this account actually has."""
    if admin:
        values = dict(PLANS["max"])
        values["studio_renders_per_day"] = None  # no daily limit
        return values
    values = dict(PLANS.get(plan or DEFAULT_PLAN, PLANS[DEFAULT_PLAN]))
    values.update(clean_overrides(overrides))
    return values
