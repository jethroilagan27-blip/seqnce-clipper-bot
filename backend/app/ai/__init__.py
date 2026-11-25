"""AI providers. Use `get_provider(user_id)`; it returns None when there is no key to use.

Whose key? With accounts off (your own computer) the key in .env. With accounts on and SHARE_SERVER_AI_KEY=true,
every account uses the server's key. With sharing off, each person uses the key they saved in Settings (admins fall
back to the server's); everyone else without a key gets no AI (basic cuts, and a note that says where to add one),
so nobody's usage is paid by someone else's key.
"""

from __future__ import annotations

from ..config import get_settings
from .base import AIError, AIProvider, LabeledImage


def get_provider(user_id: int | None = None) -> AIProvider | None:
    from .gemini import GeminiProvider  # lazy: keeps SDK import off hot paths

    cfg = get_settings()
    if cfg.auth_enabled and not cfg.share_server_ai_key:
        from .. import aikeys, db

        own = aikeys.load(user_id) if user_id else None
        if own:
            return GeminiProvider(own, cfg.gemini_model, cfg.ai_max_retries, own_key=True)
        user = db.get_user(user_id) if user_id else None
        if not (user and user["is_admin"] and cfg.gemini_api_key):
            return None
    if not cfg.gemini_api_key:
        return None
    return GeminiProvider(cfg.gemini_api_key, cfg.gemini_model, cfg.ai_max_retries)


def no_key_reason() -> str:
    """Why there is no AI, in words fit for the page."""
    if get_settings().auth_enabled and not get_settings().share_server_ai_key:
        return "no Gemini key on your account yet (add one in Settings)"
    return "no API key configured (set GEMINI_API_KEY in the .env file)"


__all__ = ["AIError", "AIProvider", "LabeledImage", "get_provider", "no_key_reason"]
