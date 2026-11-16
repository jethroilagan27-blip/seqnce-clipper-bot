"""Uploads in pieces: only for the public setup (PROXY_REQUEST_LIMIT_MB), never needed on your own computer."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth, chunked, db
from app.config import Settings, get_settings

from .test_studio import _new, make_clip, make_tone, png

PASSWORD = "correct horse battery"
PIECE = 20_000  # bytes: small, so a tiny test file still needs several pieces


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def pub(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> TestClient:
    """A server behind a proxy that refuses requests over 100 MB (what Cloudflare's free plan does), no accounts."""
    monkeypatch.setenv("PROXY_REQUEST_LIMIT_MB", "100")
    monkeypatch.setattr(Settings, "chunk_bytes", property(lambda self: PIECE))
    return request.getfixturevalue("client")


@pytest.fixture
def pubauth(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> TestClient:
    monkeypatch.setenv("PROXY_REQUEST_LIMIT_MB", "100")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("DAILY_VIDEO_LIMIT", "2")
    monkeypatch.setattr(Settings, "chunk_bytes", property(lambda self: PIECE))
    auth.reset_throttle()
    return request.getfixturevalue("client")


def _join(c: TestClient, email: str) -> str:
    r = c.post("/api/auth/signup", json={"invite_code": auth.new_invite(), "email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def _announce(c: TestClient, purpose: str, name: str, size: int, params: dict | None = None, headers: dict | None = None):
    return c.post("/api/uploads", json={"purpose": purpose, "name": name, "size": size, "params": params or {}}, headers=headers or {})


def _send(c: TestClient, upload_id: str, data: bytes, chunk: int, headers: dict | None = None, skip: set[int] = frozenset()) -> None:  # type: ignore[assignment]
    for i in range(-(-len(data) // chunk)):
        if i in skip:
            continue
        r = c.put(f"/api/uploads/{upload_id}/{i}", content=data[i * chunk:(i + 1) * chunk], headers=headers or {})
        assert r.status_code == 204, r.text


# ---------- the difference between your own computer and the public setup ----------

def test_health_tells_the_page_whether_to_use_pieces(pub: TestClient):
    up = pub.get("/api/health").json()["upload"]
    assert up == {"max_mb": 5, "chunk_mb": 50}  # public: the page sends big files in pieces of this size


def test_the_piece_size_follows_the_proxy_limit():
    assert Settings(proxy_request_limit_mb=0).chunk_mb is None  # your own computer: never in pieces
    assert Settings(proxy_request_limit_mb=100).chunk_mb == 50
    assert Settings(proxy_request_limit_mb=95).chunk_mb == 50
    assert Settings(proxy_request_limit_mb=40).chunk_mb == 30  # always safely under the limit
    assert Settings(proxy_request_limit_mb=5).chunk_mb == 1


def test_your_own_computer_has_no_proxy_limit(client: TestClient):
    assert get_settings().proxy_request_limit_mb == 0
    assert client.get("/api/health").json()["upload"]["chunk_mb"] is None


# ---------- video mode ----------

def test_a_video_sent_in_pieces_becomes_a_job(pub: TestClient, sample_video: Path):
    data = sample_video.read_bytes()
    assert len(data) > PIECE * 2
    r = _announce(pub, "video", sample_video.name, len(data))
    assert r.status_code == 201, r.text
    uid, pieces = r.json()["upload_id"], r.json()["pieces"]
    assert pieces == -(-len(data) // PIECE) and r.json()["chunk_bytes"] == PIECE
    _send(pub, uid, data, PIECE)
    assert pub.get(f"/api/uploads/{uid}").json()["received"] == list(range(pieces))
    r = pub.post("/api/videos/upload", data={"upload_id": uid, "target_duration": "30"})
    assert r.status_code == 201, r.text
    job = pub.get(f"/api/jobs/{r.json()['job_id']}").json()
    assert job["original_filename"] == sample_video.name
    assert pub.get(f"/api/videos/{job['id']}/original").content == data  # put back together byte for byte
    assert not (chunked.root() / uid).exists()  # the pieces are gone
    assert pub.get(f"/api/uploads/{uid}").status_code == 404


def test_a_missing_or_wrong_piece_is_caught(pub: TestClient, sample_video: Path):
    data = sample_video.read_bytes()
    uid = _announce(pub, "video", "clip.mp4", len(data)).json()["upload_id"]
    _send(pub, uid, data, PIECE, skip={1})
    assert pub.get(f"/api/uploads/{uid}").json()["received"][:2] == [0, 2]  # the page can see what to resend
    r = pub.post("/api/videos/upload", data={"upload_id": uid})
    assert r.status_code == 409 and "missing" in r.json()["detail"]
    assert pub.put(f"/api/uploads/{uid}/1", content=b"x" * (PIECE - 1)).status_code == 422  # too short
    assert pub.put(f"/api/uploads/{uid}/1", content=b"x" * (PIECE + 1)).status_code == 413  # too long
    assert pub.put(f"/api/uploads/{uid}/999", content=b"x").status_code == 422  # there is no such piece
    assert pub.put(f"/api/uploads/{uid}/-1", content=b"x").status_code == 422
    assert pub.get(f"/api/uploads/{uid}").json()["received"][:2] == [0, 2]  # a refused piece leaves nothing behind
    pub.put(f"/api/uploads/{uid}/1", content=data[PIECE:2 * PIECE])
    assert pub.post("/api/videos/upload", data={"upload_id": uid}).status_code == 201  # sending it again finishes the upload


def test_garbage_in_pieces_is_still_refused_as_not_a_video(pub: TestClient):
    data = b"this is a text file, not a video. " * 2000
    uid = _announce(pub, "video", "fake.mp4", len(data)).json()["upload_id"]
    _send(pub, uid, data, PIECE)
    r = pub.post("/api/videos/upload", data={"upload_id": uid})
    assert r.status_code == 415, r.text
    assert not (chunked.root() / uid).exists()  # nothing left on the disk


def test_things_that_can_never_work_are_refused_before_anything_is_sent(pub: TestClient):
    assert _announce(pub, "video", "notes.txt", 1000).status_code == 415
    assert _announce(pub, "video", "big.mp4", 6 * 1024 * 1024).status_code == 413  # over MAX_UPLOAD_MB (5 here)
    assert _announce(pub, "video", "empty.mp4", 0).status_code == 422
    assert _announce(pub, "nonsense", "a.mp4", 10).status_code == 422
    assert _announce(pub, "studio", "a.mp4", 10, {"project_id": "../../etc"}).status_code == 422
    assert _announce(pub, "studio", "a.mp4", 10, {"project_id": "0" * 32}).status_code == 404  # no such project


def test_an_upload_made_for_one_thing_cannot_be_used_for_another(pub: TestClient, sample_video: Path):
    data = sample_video.read_bytes()
    pid = _new(pub)
    uid = _announce(pub, "studio", "clip.mp4", len(data), {"project_id": pid}).json()["upload_id"]
    _send(pub, uid, data, PIECE)
    assert pub.post("/api/videos/upload", data={"upload_id": uid}).status_code == 422


def test_session_ids_are_not_paths(pub: TestClient):
    for bad in ("..", "..%2F..%2Fstorage", "x" * 32, "0" * 31):
        assert pub.get(f"/api/uploads/{bad}").status_code == 404
        assert pub.put(f"/api/uploads/{bad}/0", content=b"x").status_code in (404, 422)
    assert pub.post("/api/videos/upload", data={"upload_id": "../x"}).status_code == 404


def test_old_unfinished_uploads_are_deleted(pub: TestClient):
    import os
    import time

    uid = _announce(pub, "video", "a.mp4", 1000).json()["upload_id"]
    d = chunked.root() / uid
    old = time.time() - chunked.STALE_SECONDS - 60
    os.utime(d, (old, old))
    assert chunked.purge_stale() == 1 and not d.exists()


def test_a_person_can_only_have_a_few_unfinished_uploads(pub: TestClient):
    for _ in range(chunked.MAX_SESSIONS_PER_USER):
        assert _announce(pub, "video", "a.mp4", 1000).status_code == 201
    assert _announce(pub, "video", "a.mp4", 1000).status_code == 429


# ---------- accounts ----------

def test_someone_elses_upload_looks_like_it_does_not_exist(pubauth: TestClient, sample_video: Path):
    data = sample_video.read_bytes()
    a, b = _join(pubauth, "a@example.com"), _join(pubauth, "b@example.com")
    uid = _announce(pubauth, "video", "clip.mp4", len(data), headers=_h(a)).json()["upload_id"]
    _send(pubauth, uid, data, PIECE, headers=_h(a))
    assert pubauth.get(f"/api/uploads/{uid}", headers=_h(b)).status_code == 404
    assert pubauth.put(f"/api/uploads/{uid}/0", content=b"x" * PIECE, headers=_h(b)).status_code == 404
    assert pubauth.delete(f"/api/uploads/{uid}", headers=_h(b)).status_code == 404
    assert pubauth.post("/api/videos/upload", data={"upload_id": uid}, headers=_h(b)).status_code == 404
    assert pubauth.post("/api/videos/upload", data={"upload_id": uid}, headers=_h(a)).status_code == 201  # still A's


def test_nothing_works_without_a_login(pubauth: TestClient):
    assert _announce(pubauth, "video", "a.mp4", 1000).status_code == 401
    assert pubauth.put(f"/api/uploads/{'0' * 32}/0", content=b"x").status_code == 401
    assert pubauth.get(f"/api/uploads/{'0' * 32}").status_code == 401


def test_the_daily_limit_is_checked_before_the_file_is_sent(pubauth: TestClient, sample_video: Path):
    data = sample_video.read_bytes()
    a = _join(pubauth, "a@example.com")
    uid = db.get_session_user(auth._sha(a))["id"]  # type: ignore[index]
    for _ in range(2):  # the test server allows 2 videos a day
        assert db.try_record_usage(uid, "video", None, auth.QUOTA_WINDOW)
    r = _announce(pubauth, "video", "clip.mp4", len(data), headers=_h(a))
    assert r.status_code == 429


# ---------- Studio ----------

def test_a_studio_file_sent_in_pieces_is_added_like_any_other(pub: TestClient, tmp_path: Path):
    pid = _new(pub)
    data = make_clip(tmp_path / "c.mp4", "red", 2, audio=True).read_bytes()
    assert len(data) > PIECE
    uid = _announce(pub, "studio", "Members/clip.mp4", len(data), {"project_id": pid}).json()["upload_id"]
    _send(pub, uid, data, PIECE)
    r = pub.post(f"/api/studio/projects/{pid}/assets/from-upload", json={"upload_id": uid, "folder": "Members/Vidal"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rejected"] == [] and len(body["added"]) == 1
    assert body["added"][0]["kind"] == "video" and body["added"][0]["folder"] == "Members/Vidal"
    assert body["added"][0]["name"] == "clip.mp4"
    assert len(body["project"]["assets"]) == 1 and body["project"]["assets"][0]["size_bytes"] == len(data)
    assert not (chunked.root() / uid).exists()


def test_a_studio_upload_cannot_be_given_to_another_project(pub: TestClient, tmp_path: Path):
    p1, p2 = _new(pub), _new(pub)
    data = make_tone(tmp_path / "t.wav", 2).read_bytes()
    uid = _announce(pub, "studio", "t.wav", len(data), {"project_id": p1}).json()["upload_id"]
    _send(pub, uid, data, PIECE)
    r = pub.post(f"/api/studio/projects/{p2}/assets/from-upload", json={"upload_id": uid})
    assert r.status_code == 422
    assert pub.get(f"/api/studio/projects/{p2}").json()["assets"] == []


def test_studio_refuses_what_it_could_not_keep_before_anything_is_sent(pub: TestClient):
    pid = _new(pub)
    assert _announce(pub, "studio", "notes.txt", 1000, {"project_id": pid}).status_code == 415
    assert _announce(pub, "studio", "a.mp4", 6 * 1024 * 1024, {"project_id": pid}).status_code == 413  # more than the file limit
    ok = _announce(pub, "studio", "pic.png", len(png()), {"project_id": pid})
    assert ok.status_code == 201
    _send(pub, ok.json()["upload_id"], png(), PIECE)
    r = pub.post(f"/api/studio/projects/{pid}/assets/from-upload", json={"upload_id": ok.json()["upload_id"]})
    assert r.status_code == 200 and r.json()["added"][0]["kind"] == "image"
