"""The Studio file panel sends three files at once: the server must cope, and the plan's limits must still hold."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth, features
from app.config import get_settings
from app.studio import engine

from .test_studio import _new, png


def _send(client: TestClient, pid: str, n: int) -> dict:
    r = client.post(f"/api/studio/projects/{pid}/assets", files=[("files", (f"p{n}.png", png(size=(40 + n, 40 + n)), "image/png"))], data={"folders": f"Folder {n % 2}"})
    assert r.status_code == 200, r.text
    return r.json()


def test_many_files_sent_at_the_same_time_are_all_kept_with_their_folders(client: TestClient):
    pid = _new(client)
    with ThreadPoolExecutor(max_workers=3) as pool:
        replies = list(pool.map(lambda n: _send(client, pid, n), range(9)))
    assert sum(len(r["added"]) for r in replies) == 9 and all(not r["rejected"] for r in replies)
    assets = client.get(f"/api/studio/projects/{pid}").json()["assets"]
    assert len(assets) == 9 and len({a["id"] for a in assets}) == 9
    assert sorted(a["name"] for a in assets) == sorted(f"p{n}.png" for n in range(9))
    assert {a["folder"] for a in assets} == {"Folder 0", "Folder 1"}
    files = list((Path(get_settings().storage_dir) / "studio" / pid / "assets").iterdir())
    assert len(files) == 9  # nothing lost, nothing left over


def test_the_file_limit_holds_even_when_uploads_arrive_together(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    tiny = dict(features.resolve("max", admin=True), studio_max_assets=3)
    monkeypatch.setattr(engine, "owner_features", lambda project: tiny)
    monkeypatch.setattr(auth, "features_of", lambda user: tiny)
    pid = _new(client)
    with ThreadPoolExecutor(max_workers=6) as pool:
        replies = list(pool.map(lambda n: _send(client, pid, n), range(8)))
    added = sum(len(r["added"]) for r in replies)
    rejected = [x for r in replies for x in r["rejected"]]
    assert added == 3 and len(rejected) == 5 and all("at most 3" in x["reason"] for x in rejected)
    assert len(client.get(f"/api/studio/projects/{pid}").json()["assets"]) == 3
    left = list((Path(get_settings().storage_dir) / "studio" / pid / "assets").iterdir())
    assert len(left) == 3  # the refused ones were not kept on disk
