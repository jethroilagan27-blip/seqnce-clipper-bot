"""Opt-in end-to-end check with the REAL Whisper model and REAL Gemini (uses free-tier quota).
Run: uv run pytest -m live_ai -s"""
from __future__ import annotations

import json
import time

import pytest

from app.config import ROOT_DIR
from tests.test_upload_flow import _upload, _wait_done

SAMPLE = ROOT_DIR / "samples" / "speech_sample.mp4"

pytestmark = [
    pytest.mark.live_ai,
    pytest.mark.real_whisper,
    pytest.mark.skipif(not SAMPLE.exists(), reason="run scripts/make_sample_video.ps1 first"),
]


def test_live_plan(client):
    t0 = time.time()
    job_id = _upload(client, SAMPLE, target_duration="30").json()["job_id"]
    job = _wait_done(client, job_id, timeout=600)
    assert job["status"] == "completed", job
    data = client.get(f"/api/jobs/{job_id}/analysis").json()
    print(f"\ntotal {time.time()-t0:.1f}s")
    print("VISUAL:", json.dumps(data["visual"], indent=1))
    plan = data["plan"]
    print("PLAN:", json.dumps(plan, indent=1))

    assert data["visual"]["analysis_source"] == "ai", data["visual"].get("fallback_reason")
    assert plan["source"] == "ai", plan.get("fallback_reason")
    total = sum(c["end"] - c["start"] for c in plan["clips"])
    assert 30 * 0.6 <= total <= 30 * 1.25
    assert plan["summary"]["main_message"]
    for c in plan["clips"]:
        assert 0 <= c["start"] < c["end"] <= 60.0

    # the finished video: keep a copy for eyeballing (samples/ is gitignored)
    assert job["has_output"], job
    res = client.get(f"/api/videos/{job_id}/download")
    assert res.status_code == 200
    (ROOT_DIR / "samples" / "live_output.mp4").write_bytes(res.content)
    from app.config import get_settings
    import shutil
    shutil.copy(get_settings().temp_dir / job_id / "captions.ass", ROOT_DIR / "samples" / "live_captions.ass")
    rendered = client.get(f"/api/jobs/{job_id}/result").json()["rendered"]
    print("RENDERED:", rendered)
