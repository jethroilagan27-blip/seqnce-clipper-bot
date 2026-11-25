"""AI providers. Use `get_provider(user_id)`; it returns None when there is no key to use.

Whose key? With accounts off (your own computer) the key in .env. With accounts on, a key the person saved themselves
(their "custom API") always comes first. Without one: the server's key if SHARE_SERVER_AI_KEY=true or the person is an
admin; otherwise no AI (basic cuts, and a note that says where to add a key), so nobody's usage is paid by someone
else's key.
"""

from __future__ import annotations

from ..config import get_settings
from .base import AIError, AIProvider, AIQuotaError, LabeledImage, VideoInput


def get_provider(user_id: int | None = None) -> AIProvider | None:
    from .gemini import GeminiProvider  # lazy: keeps SDK import off hot paths

    cfg = get_settings()
    if cfg.auth_enabled:
        from .. import aikeys, db

        own = aikeys.load(user_id) if user_id else None
        if own:
            return GeminiProvider(own, cfg.gemini_model, cfg.ai_max_retries, own_key=True)
        if not cfg.share_server_ai_key:
            user = db.get_user(user_id) if user_id else None
            if not (user and user["is_admin"]):
                return None
    if not cfg.gemini_api_key:
        return None
    return GeminiProvider(cfg.gemini_api_key, cfg.gemini_model, cfg.ai_max_retries, backup_key=cfg.gemini_api_key_backup.strip())


def no_key_reason() -> str:
    """Why there is no AI, in words fit for the page."""
    if get_settings().auth_enabled and not get_settings().share_server_ai_key:
        return "no Gemini key on your account yet (add one on the Me page)"
    return "no API key configured (set GEMINI_API_KEY in the .env file)"


__all__ = ["AIError", "AIProvider", "AIQuotaError", "LabeledImage", "VideoInput", "get_provider", "no_key_reason"]
