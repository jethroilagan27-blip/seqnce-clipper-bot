"""Sanity-check the Gemini setup without running the whole app.

    cd backend
    ..\\tools\\uv\\uv.exe run python check_gemini.py

Reads GEMINI_API_KEY / GEMINI_MODEL from the root .env. Never prints the key.
Makes 1 list call + 1 tiny text call (negligible free-tier usage).
"""

from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore")

from pydantic import BaseModel

from app.ai import AIError
from app.ai.gemini import make_gemini_provider
from app.config import get_settings


class Ping(BaseModel):
    answer: str


def main() -> int:
    cfg = get_settings()
    if not cfg.gemini_api_key:
        print("GEMINI_API_KEY is not set. Put it in the root .env file (not in chat, not in git).")
        return 1

    from google import genai

    client = genai.Client(api_key=cfg.gemini_api_key)
    try:
        names = sorted(
            m.name.removeprefix("models/")
            for m in client.models.list()
            if "generateContent" in (m.supported_actions or [])
        )
    except Exception as exc:
        print(f"Could not list models ({type(exc).__name__}). Is the key valid?")
        return 1
    flash = [n for n in names if "flash" in n]
    print(f"Key accepted. {len(names)} models support generateContent. Flash models:")
    for n in flash:
        print("  ", n)
    if cfg.gemini_model not in names:
        print(f"\nWARNING: GEMINI_MODEL={cfg.gemini_model!r} is not in that list. Pick one above.")
        return 1

    provider = make_gemini_provider()
    try:
        out = provider.generate_structured("Reply with the single word: pong", Ping)
    except AIError as exc:
        print(f"\nCall failed: {exc}")
        return 1
    print(f"\nOK - {cfg.gemini_model} answered: {out.answer!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
