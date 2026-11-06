"""Opt-in: run with `uv run pytest -m real_whisper -s`. Uses ../samples/speech_sample.mp4
(generate with scripts/make_sample_video.ps1) and the real Whisper model."""
from __future__ import annotations

import time

import pytest

from app.config import ROOT_DIR
from tests.test_upload_flow import _upload, _wait_done

SAMPLE = ROOT_DIR / "samples" / "speech_sample.mp4"

pytestmark = [
    pytest.mark.real_whisper,
    pytest.mark.skipif(not SAMPLE.exists(), reason="run scripts/make_sample_video.ps1 first"),
]


def test_real_transcription(client):
    t0 = time.time()
    job_id = _upload(client, SAMPLE).json()["job_id"]
    job = _wait_done(client, job_id, timeout=600)
    elapsed = time.time() - t0
    assert job["status"] == "completed", job

    tr = client.get(f"/api/jobs/{job_id}/analysis").json()["transcript"]
    text = " ".join(s["text"] for s in tr["segments"]).lower()
    print(f"\n{elapsed:.1f}s total, {len(tr['segments'])} segments, lang={tr['language']}")
    for s in tr["segments"]:
        print(f"  [{s['start']:6.2f}-{s['end']:6.2f}] {s['text']}")

    assert tr["language"] == "en"
    for phrase in ("business automation", "start small", "human in the loop"):
        assert phrase in text
    segs = tr["segments"]
    assert all(a["end"] <= b["start"] + 0.01 for a, b in zip(segs, segs[1:]))  # ordered, no overlap
    assert segs[-1]["end"] <= tr["duration"] + 0.5
    assert all(s["words"] for s in segs)
