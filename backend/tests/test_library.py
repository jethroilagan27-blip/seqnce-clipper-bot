"""The library lists one account's own videos from every mode."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import admin, auth, db
from app.slideshow import store as photo_store
from app.studio import store as studio_store

from .test_studio import _new, png

PASSWORD = "correct horse battery"


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ac(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    auth.reset_throttle()
    return request.getfixturevalue("client")


def _join(c: TestClient, email: str) -> str:
    r = c.post("/api/auth/signup", json={"invite_code": auth.new_invite(), "email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def _upload(c: TestClient, path: Path, headers: dict | None = None) -> str:
    with path.open("rb") as f:
        r = c.post("/api/videos/upload", files={"file": (path.name, f, "video/mp4")}, headers=headers or {})
    assert r.status_code == 201, r.text
    return r.json()["job_id"]


def _wait(c: TestClient, job_id: str, headers: dict | None = None) -> None:
    for _ in range(200):
        if c.get(f"/api/jobs/{job_id}", headers=headers or {}).json()["status"] in ("completed", "failed"):
            return
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_an_empty_library(client: TestClient):
    body = client.get("/api/library").json()
    assert body["items"] == [] and body["keep_days"] == {"video": 7, "photos": 7, "studio": 30}


def test_a_finished_video_can_be_watched_and_downloaded_from_the_library(client: TestClient, sample_video: Path):
    job_id = _upload(client, sample_video)
    _wait(client, job_id)
    [item] = client.get("/api/library").json()["items"]
    assert (item["kind"], item["id"], item["title"], item["status"]) == ("video", job_id, sample_video.name, "ready")
    assert item["duration"] > 0
    for key in ("thumb", "video", "download"):
        assert client.get(item[key]).status_code == 200, key


def test_unmade_projects_are_not_listed_and_made_ones_are(client: TestClient, tmp_path: Path):
    pid = _new(client, title="My trailer")
    slides = client.post("/api/slideshows").json()["id"]
    client.post(f"/api/slideshows/{slides}/photos", files=[("files", ("a.png", png(), "image/png"))])
    assert client.get("/api/library").json()["items"] == []  # nothing has been rendered yet
    out = tmp_path / "out.mp4"
    out.write_bytes(b"video")
    studio_store.update(pid, output_path=str(out), output_meta_json={"duration": 12.5}, status="ready")
    photo_store.update(slides, status="queued")
    items = {i["kind"]: i for i in client.get("/api/library").json()["items"]}
    assert items["studio"]["title"] == "My trailer" and items["studio"]["duration"] == 12.5 and items["studio"]["status"] == "ready"
    assert items["photos"]["status"] == "working" and items["photos"]["video"] is None and "1 photo)" in items["photos"]["title"]
    assert client.get(items["photos"]["thumb"]).status_code == 200


def test_everyone_sees_only_their_own_videos_even_admins(ac: TestClient, sample_video: Path):
    a, b = _join(ac, "a@example.com"), _join(ac, "b@example.com")
    job_id = _upload(ac, sample_video, _h(a))
    _wait(ac, job_id, _h(a))
    assert [i["id"] for i in ac.get("/api/library", headers=_h(a)).json()["items"]] == [job_id]
    assert ac.get("/api/library", headers=_h(b)).json()["items"] == []
    admin.create_user("boss@example.com", PASSWORD, is_admin=True)
    boss = ac.post("/api/auth/login", json={"email": "boss@example.com", "password": PASSWORD}).json()["token"]
    assert ac.get("/api/library", headers=_h(boss)).json()["items"] == []  # an admin's library is their own work
    assert ac.get("/api/library").status_code == 401
    assert db.get_job(job_id) is not None
