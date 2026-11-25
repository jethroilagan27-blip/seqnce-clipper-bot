"""A broken SSLKEYLOGFILE (set by antivirus software) must not stop the AI from being reached."""

from __future__ import annotations

import os
import ssl
from pathlib import Path

import pytest

from app.ai.gemini import GeminiProvider
from app.services.tls import drop_unusable_key_log


def test_a_key_log_that_cannot_be_opened_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SSLKEYLOGFILE", str(tmp_path / "gone" / "keys.log"))
    with pytest.raises(OSError):
        ssl.create_default_context()  # the failure the live site hit
    GeminiProvider("x" * 30, "gemini-test")
    assert "SSLKEYLOGFILE" not in os.environ
    ssl.create_default_context()


def test_a_working_key_log_is_left_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = str(tmp_path / "keys.log")
    monkeypatch.setenv("SSLKEYLOGFILE", path)
    drop_unusable_key_log()
    assert os.environ["SSLKEYLOGFILE"] == path


def test_no_setting_is_fine(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SSLKEYLOGFILE", raising=False)
    drop_unusable_key_log()
    assert "SSLKEYLOGFILE" not in os.environ
