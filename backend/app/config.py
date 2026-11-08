"""Application settings, loaded from environment variables / the root .env file."""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> repo root is two levels above "app"
ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- storage -----------------------------------------------------------
    storage_dir: Path = ROOT_DIR / "storage"

    # --- tools (empty = auto-detect: ./tools/ffmpeg first, then PATH) --------
    ffmpeg_path: str = ""
    ffprobe_path: str = ""

    # --- upload limits -----------------------------------------------------
    max_upload_mb: int = 500
    max_video_duration_s: int = 30 * 60
    retention_days: int = 7  # finished jobs older than this are deleted at startup (0 = keep forever)

    # --- web ---------------------------------------------------------------
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- accounts (off by default: local use needs no login) ----------------
    auth_enabled: bool = False  # True = invite-only accounts, per-user ownership and quotas
    auth_secret: str = ""  # signs media tokens; empty = a random one is created once in storage/.auth_secret
    session_days: int = 14
    daily_video_limit: int = 3  # uploads per rolling 24 h for a normal user (admins: unlimited)
    daily_chat_limit: int = 20  # AI chat messages per rolling 24 h for a normal user
    max_active_jobs_per_user: int = 1  # videos a user may have queued/processing at once
    open_signup: bool = False  # True = anyone can create an account (no invite code); False = invite only
    signup_daily_cap: int = 50  # open sign-up only: most new accounts per rolling 24 h on the whole server
    signup_per_ip_per_hour: int = 5  # open sign-up only: most new accounts one visitor can make per hour

    # --- AI (used from Day 3 onwards) --------------------------------------
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    whisper_model: str = "small"
    whisper_device: str = "cpu"  # "cpu" or "cuda"
    whisper_compute_type: str = "int8"  # int8 on CPU; float16 on cuda
    whisper_language: str = ""  # "" = auto-detect; e.g. "en", "tl"
    frame_interval_s: float = 3.0
    frame_width: int = 512  # px, frames are downscaled before storage/AI
    max_ai_frames: int = 12  # cap on images sent to the AI per call
    scene_threshold: float = 0.35  # ffmpeg scene-change score (0-1)
    ai_max_retries: int = 3

    # --- helpers -----------------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def db_path(self) -> Path:
        return self.storage_dir / "svb.sqlite3"

    @property
    def uploads_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def temp_dir(self) -> Path:
        return self.storage_dir / "temp"

    @property
    def subtitles_dir(self) -> Path:
        return self.storage_dir / "subtitles"

    @property
    def outputs_dir(self) -> Path:
        return self.storage_dir / "outputs"

    @property
    def music_dir(self) -> Path:
        return self.storage_dir / "music"

    def ensure_dirs(self) -> None:
        for d in (
            self.storage_dir,
            self.uploads_dir,
            self.temp_dir,
            self.subtitles_dir,
            self.outputs_dir,
            self.music_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def _resolve_tool(self, configured: str, name: str) -> str:
        if configured:
            return configured
        local = ROOT_DIR / "tools" / "ffmpeg" / f"{name}.exe"
        if local.exists():
            return str(local)
        found = shutil.which(name)
        return found or name

    @property
    def ffmpeg(self) -> str:
        return self._resolve_tool(self.ffmpeg_path, "ffmpeg")

    @property
    def ffprobe(self) -> str:
        return self._resolve_tool(self.ffprobe_path, "ffprobe")


@lru_cache
def get_settings() -> Settings:
    return Settings()
