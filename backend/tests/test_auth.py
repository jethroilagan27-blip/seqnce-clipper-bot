"""Accounts, ownership, media tokens and quotas (AUTH_ENABLED=true)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import admin, auth, db
from app.api import auth as auth_api  # noqa: F401  (imported to make sure the router module loads)

PASSWORD = "correct horse battery"
OPEN_ROUTES = {"/api/health", "/api/auth/signup", "/api/auth/login"}


@pytest.fixture
def ac(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> TestClient:
    """A client for a server with accounts on and small limits."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("DAILY_VIDEO_LIMIT", "2")
    monkeypatch.setenv("DAILY_CHAT_LIMIT", "2")
    monkeypatch.setenv("MAX_ACTIVE_JOBS_PER_USER", "1")
    auth.reset_throttle()
    return request.getfixturevalue("client")


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _join(c: TestClient, email: str = "a@example.com", password: str = PASSWORD, code: str | None = None) -> dict:
    r = c.post("/api/auth/signup", json={"invite_code": code or auth.new_invite(), "email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def _up(c: TestClient, path: Path, token: str, **form):
    with path.open("rb") as f:
        return c.post("/api/videos/upload", files={"file": (path.name, f, "video/mp4")}, data=form, headers=_h(token))


def _wait(c: TestClient, job_id: str, token: str, timeout: float = 30) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        job = c.get(f"/api/jobs/{job_id}", headers=_h(token)).json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


# ---------- passwords and tokens (pure) ----------

def test_password_hashing():
    h = auth.hash_password(PASSWORD)
    assert h.startswith("scrypt$") and PASSWORD not in h
    assert auth.verify_password(PASSWORD, h) and not auth.verify_password(PASSWORD + "x", h)
    assert auth.hash_password(PASSWORD) != h  # random salt
    for bad in ("", "scrypt$1$2", "md5$a$b$c$d$e", "scrypt$x$8$1$AAAA$AAAA"):
        assert auth.verify_password(PASSWORD, bad) is False


def test_password_and_email_rules():
    assert auth.password_problem("short", "a@b.co") and auth.password_problem("x" * 300, "a@b.co")
    assert auth.password_problem("a@b.co", "a@b.co") and auth.password_problem(PASSWORD, "a@b.co") is None
    assert auth.normalize_email("  Jo@Example.COM ") == "jo@example.com"
    assert auth.normalize_email("nope") is None and auth.normalize_email("a b@c.de") is None


# ---------- the whole API is closed without a login ----------

def _all_routes(app) -> list:
    """Every route, including those inside include_router() wrappers."""
    out = []
    for route in app.routes:
        inner = getattr(route, "original_router", None)
        out.extend(inner.routes if inner is not None else [route])
    return out


def test_every_api_route_needs_a_login(ac: TestClient):
    checked = 0
    for route in _all_routes(ac.app):  # type: ignore[attr-defined]
        path = getattr(route, "path", "")
        if not path.startswith("/api/") or path in OPEN_ROUTES:
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            url = path.replace("{job_id}", "0" * 32)
            r = ac.request(method, url, json={} if method == "POST" else None)
            assert r.status_code == 401, f"{method} {path} answered {r.status_code} without a login"
            checked += 1
    assert checked >= 12  # all the job, video, music and auth routes


def test_health_is_open_and_docs_are_hidden(ac: TestClient):
    assert ac.get("/api/health").json()["auth_required"] is True
    assert ac.get("/docs").status_code == 404 and ac.get("/openapi.json").status_code == 404


# ---------- sign-up / sign-in ----------

def test_signup_login_me_logout(ac: TestClient):
    joined = _join(ac)
    assert joined["user"]["email"] == "a@example.com" and joined["user"]["is_admin"] is False
    me = ac.get("/api/auth/me", headers=_h(joined["token"])).json()
    assert me["auth_required"] is True and me["media_token"]
    assert me["user"]["quota"]["videos"] == {"used": 0, "limit": 2, "resets_at": None}
    assert me["user"]["quota"]["chats"]["limit"] == 2

    login = ac.post("/api/auth/login", json={"email": " A@Example.com ", "password": PASSWORD})
    assert login.status_code == 200 and login.json()["token"] != joined["token"]
    assert ac.post("/api/auth/logout", headers=_h(joined["token"])).status_code == 204
    assert ac.get("/api/auth/me", headers=_h(joined["token"])).status_code == 401  # that session is gone
    assert ac.get("/api/auth/me", headers=_h(login.json()["token"])).status_code == 200  # the other one lives


def test_tokens_and_codes_are_stored_hashed(ac: TestClient):
    code = auth.new_invite()
    token = _join(ac, code=code)["token"]
    with db.connect() as conn:
        stored = [r[0] for r in conn.execute("SELECT token_hash FROM sessions")] + [r[0] for r in conn.execute("SELECT code_hash FROM invites")]
        pw = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    assert token not in stored and code not in stored and PASSWORD not in pw


def test_signup_rules(ac: TestClient):
    url = "/api/auth/signup"
    ok = auth.new_invite()
    assert ac.post(url, json={"invite_code": "SQ-NOPE-NOPE-NOPE", "email": "a@example.com", "password": PASSWORD}).status_code == 400
    assert ac.post(url, json={"invite_code": ok, "email": "not-an-email", "password": PASSWORD}).status_code == 422
    assert ac.post(url, json={"invite_code": ok, "email": "a@example.com", "password": "short"}).status_code == 422
    _join(ac, "a@example.com", code=ok)
    assert ac.post(url, json={"invite_code": ok, "email": "b@example.com", "password": PASSWORD}).status_code == 400  # single use
    assert ac.post(url, json={"invite_code": auth.new_invite(), "email": "A@example.com", "password": PASSWORD}).status_code == 409
    locked = auth.new_invite("only@example.com")
    assert ac.post(url, json={"invite_code": locked, "email": "other@example.com", "password": PASSWORD}).status_code == 400
    assert ac.post(url, json={"invite_code": locked.lower().replace("-", " "), "email": "only@example.com", "password": PASSWORD}).status_code == 201

    expired = auth.new_invite()
    with db.connect() as conn:
        conn.execute("UPDATE invites SET expires_at = '2000-01-01T00:00:00+00:00' WHERE used_at IS NULL")
    assert ac.post(url, json={"invite_code": expired, "email": "c@example.com", "password": PASSWORD}).status_code == 400


def test_one_invite_cannot_be_spent_twice_in_a_race(ac: TestClient):
    code_hash = auth._sha(auth.normalize_code(auth.new_invite()))
    results: list[str] = []

    def attempt(i: int) -> None:
        results.append(db.create_user_with_invite(code_hash, f"u{i}@example.com", "x")[0])

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1 and results.count("invalid") == 7
    assert len(db.list_users()) == 1


def test_login_failures_are_generic_and_throttled(ac: TestClient):
    _join(ac)
    bad = ac.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong-password"})
    unknown = ac.post("/api/auth/login", json={"email": "ghost@example.com", "password": "wrong-password"})
    assert bad.status_code == unknown.status_code == 401 and bad.json() == unknown.json()  # can't probe which emails exist
    for _ in range(auth.LOGIN_MAX_PER_EMAIL):
        ac.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong-password"})
    blocked = ac.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD})
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers  # even the right password waits
    auth.reset_throttle()
    assert ac.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}).status_code == 200


def test_disabled_and_expired_sessions_stop_working(ac: TestClient):
    token = _join(ac)["token"]
    uid = db.get_user_by_email("a@example.com")["id"]
    db.update_user(uid, disabled=1)
    assert ac.get("/api/auth/me", headers=_h(token)).status_code == 401
    assert ac.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}).status_code == 401
    db.update_user(uid, disabled=0)
    assert ac.get("/api/auth/me", headers=_h(token)).status_code == 200
    with db.connect() as conn:
        conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
    assert ac.get("/api/auth/me", headers=_h(token)).status_code == 401


# ---------- ownership ----------

def test_users_only_see_their_own_jobs(ac: TestClient, sample_video: Path):
    a, b = _join(ac, "a@example.com")["token"], _join(ac, "b@example.com")["token"]
    job_id = _up(ac, sample_video, a).json()["job_id"]
    assert _wait(ac, job_id, a)["status"] == "completed"

    own = {
        "GET": [f"/api/jobs/{job_id}", f"/api/jobs/{job_id}/analysis", f"/api/jobs/{job_id}/result", f"/api/jobs/{job_id}/versions"],
        "POST": [f"/api/jobs/{job_id}/timeline", f"/api/jobs/{job_id}/revisions"],
    }
    for url in own["GET"]:
        assert ac.get(url, headers=_h(a)).status_code == 200, url
        assert ac.get(url, headers=_h(b)).status_code == 404, url  # looks exactly like a job that doesn't exist
    assert ac.post(own["POST"][0], json={}, headers=_h(a)).status_code == 200
    assert ac.post(own["POST"][0], json={}, headers=_h(b)).status_code == 404
    assert ac.post(own["POST"][1], json={"message": "cut it"}, headers=_h(b)).status_code == 404
    assert ac.get(f"/api/jobs/{'0' * 32}", headers=_h(b)).json() == ac.get(f"/api/jobs/{job_id}", headers=_h(b)).json()  # same body

    admin_token = ac.post("/api/auth/login", json={"email": _make_admin(ac), "password": PASSWORD}).json()["token"]
    assert ac.get(f"/api/jobs/{job_id}", headers=_h(admin_token)).status_code == 200  # admins can look

    # a job from before accounts existed (no owner) is for admins only
    db.update_job(job_id, user_id=None)
    assert ac.get(f"/api/jobs/{job_id}", headers=_h(a)).status_code == 404
    assert ac.get(f"/api/jobs/{job_id}", headers=_h(admin_token)).status_code == 200


def _make_admin(c: TestClient, email: str = "boss@example.com") -> str:
    admin.create_user(email, PASSWORD, is_admin=True)
    return email


# ---------- media tokens ----------

def test_media_tokens(ac: TestClient, sample_video: Path, monkeypatch: pytest.MonkeyPatch):
    a = _join(ac, "a@example.com")
    b = _join(ac, "b@example.com")
    job_id = _up(ac, sample_video, a["token"]).json()["job_id"]
    assert _wait(ac, job_id, a["token"])["status"] == "completed"

    urls = [f"/api/videos/{job_id}/original", f"/api/videos/{job_id}/preview", f"/api/videos/{job_id}/download",
            f"/api/videos/{job_id}/thumb?t=1&h=48"]
    for url in urls:
        sep = "&" if "?" in url else "?"
        assert ac.get(url).status_code == 401, url  # no credentials at all
        assert ac.get(f"{url}{sep}st={a['media_token']}").status_code == 200, url  # what <video>/<img> send
        assert ac.get(f"{url}{sep}st={b['media_token']}").status_code == 404, url  # someone else's token: not their job
        assert ac.get(f"{url}{sep}st={a['media_token'][:-3]}xyz").status_code == 401, url  # tampered
        assert ac.get(url, headers=_h(a["token"])).status_code == 200, url  # the normal header works too

    # a media token opens media only: it is not a login
    assert ac.get(f"/api/jobs/{job_id}?st={a['media_token']}").status_code == 401
    assert ac.get(f"/api/auth/me?st={a['media_token']}").status_code == 401

    # expired
    monkeypatch.setattr(auth, "MEDIA_TOKEN_TTL_S", -5)
    old = auth.make_media_token(db.get_user_by_email("a@example.com")["id"])
    assert ac.get(f"/api/videos/{job_id}/original?st={old}").status_code == 401

    # a disabled user's media token stops working too
    monkeypatch.undo()
    db.update_user(db.get_user_by_email("a@example.com")["id"], disabled=1)
    assert ac.get(f"/api/videos/{job_id}/original?st={a['media_token']}").status_code == 401


# ---------- quotas ----------

def test_video_quota_active_job_limit_and_me(ac: TestClient, sample_video: Path):
    t = _join(ac)["token"]
    uid = db.get_user_by_email("a@example.com")["id"]
    first = _up(ac, sample_video, t).json()["job_id"]

    db.update_job(first, status="running")  # pretend it's still processing
    busy = _up(ac, sample_video, t)
    assert busy.status_code == 409 and "already have a video" in busy.json()["detail"]
    assert db.usage_in_window(uid, "video", auth.QUOTA_WINDOW)[0] == 1  # a refused upload costs nothing
    db.update_job(first, status="completed")

    assert _up(ac, sample_video, t).status_code == 201  # 2 of 2
    _wait(ac, first, t)
    over = None
    for _ in range(40):  # wait until the second job is done, so only the quota can say no
        if db.count_active_jobs(uid) == 0:
            over = _up(ac, sample_video, t)
            break
        time.sleep(0.25)
    assert over is not None and over.status_code == 429
    assert "2 videos" in over.json()["detail"] and "in about" in over.json()["detail"]
    me = ac.get("/api/auth/me", headers=_h(t)).json()["user"]["quota"]["videos"]
    assert me["used"] == 2 and me["limit"] == 2 and me["resets_at"]
    assert len(list((__import__("app.config", fromlist=["x"]).get_settings().uploads_dir).iterdir())) == 2  # the refused file was not kept


def test_per_user_override_and_admin_unlimited(ac: TestClient, sample_video: Path):
    t = _join(ac)["token"]
    uid = db.get_user_by_email("a@example.com")["id"]
    db.update_user(uid, video_limit=0)
    assert _up(ac, sample_video, t).status_code == 429
    db.update_user(uid, video_limit=None, is_admin=1)  # admins: no quota
    assert auth.limit_for(auth._to_user(db.get_user(uid)), "video") is None
    assert ac.get("/api/auth/me", headers=_h(t)).json()["user"]["quota"]["videos"]["limit"] is None


def test_chat_quota_counts_only_chat_messages(ac: TestClient, sample_video: Path):
    t = _join(ac)["token"]
    job_id = _up(ac, sample_video, t).json()["job_id"]
    assert _wait(ac, job_id, t)["status"] == "completed"
    url = f"/api/jobs/{job_id}/revisions"

    for i in range(2):  # no AI key here, so each chat fails politely, but it still used a message
        assert ac.post(url, json={"message": f"try {i}"}, headers=_h(t)).status_code == 202
        assert _wait(ac, job_id, t)["status"] == "completed"
    third = ac.post(url, json={"message": "one more"}, headers=_h(t))
    assert third.status_code == 429 and "chat messages" in third.json()["detail"]

    # hand edits and restoring use no AI, so they are never limited
    assert ac.post(url, json={"edit": {"hook_enabled": False, "captions_enabled": False}}, headers=_h(t)).status_code in (202, 422)
    assert ac.get("/api/auth/me", headers=_h(t)).json()["user"]["quota"]["chats"]["used"] == 2


def test_quota_check_is_atomic_under_parallel_requests(ac: TestClient):
    uid = db.create_user("p@example.com", "x") or 0
    results: list[bool] = []

    def spend() -> None:
        results.append(db.try_record_usage(uid, "video", 3, auth.QUOTA_WINDOW))

    threads = [threading.Thread(target=spend) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count(True) == 3 and results.count(False) == 9


# ---------- the upload gate runs before the body is read ----------

def test_upload_gate_rejects_before_reading_the_body(ac: TestClient):
    # no login: refused on the headers alone, even when the declared body is huge
    r = ac.post("/api/videos/upload", content=b"x", headers={"content-length": "400000000", "content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 401
    t = _join(ac)["token"]
    r = ac.post("/api/videos/upload", content=b"x", headers={**_h(t), "content-length": "9999999999", "content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 413 and "MB" in r.json()["detail"]
    assert "access-control-allow-origin" in {k.lower() for k in ac.options("/api/videos/upload", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"}).headers}


# ---------- admin tool ----------

def test_admin_cli(ac: TestClient, monkeypatch: pytest.MonkeyPatch, capsys):
    monkeypatch.setenv("SEQNCE_ADMIN_PASSWORD", PASSWORD)
    assert admin.main(["create-user", "Boss@Example.com", "--admin"]) == 0
    assert db.get_user_by_email("boss@example.com")["is_admin"] == 1
    with pytest.raises(SystemExit):
        admin.main(["create-user", "boss@example.com"])  # duplicate
    monkeypatch.setenv("SEQNCE_ADMIN_PASSWORD", "short")
    with pytest.raises(SystemExit):
        admin.main(["create-user", "weak@example.com"])  # weak password refused
    monkeypatch.setenv("SEQNCE_ADMIN_PASSWORD", PASSWORD)

    capsys.readouterr()
    admin.main(["invite", "--email", "friend@example.com", "--days", "3"])
    code = [w for w in capsys.readouterr().out.split() if w.startswith("SQ-")][0]
    assert ac.post("/api/auth/signup", json={"invite_code": code, "email": "friend@example.com", "password": PASSWORD}).status_code == 201

    admin.main(["set-limits", "friend@example.com", "--videos", "7", "--chats", "default"])
    friend = db.get_user_by_email("friend@example.com")
    assert friend["video_limit"] == 7 and friend["chat_limit"] is None
    token = ac.post("/api/auth/login", json={"email": "friend@example.com", "password": PASSWORD}).json()["token"]
    admin.main(["disable", "friend@example.com"])
    assert ac.get("/api/auth/me", headers=_h(token)).status_code == 401  # signed out immediately
    admin.main(["enable", "friend@example.com"])
    monkeypatch.setenv("SEQNCE_ADMIN_PASSWORD", "a brand new password")
    admin.main(["reset-password", "friend@example.com"])
    assert ac.post("/api/auth/login", json={"email": "friend@example.com", "password": PASSWORD}).status_code == 401
    assert ac.post("/api/auth/login", json={"email": "friend@example.com", "password": "a brand new password"}).status_code == 200
    capsys.readouterr()
    admin.main(["users"])
    assert "boss@example.com" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        admin.main(["disable", "nobody@example.com"])


# ---------- accounts off: nothing changes ----------

def test_accounts_off_means_no_login_and_no_limits(client: TestClient, sample_video: Path):
    assert client.post("/api/auth/login", json={"email": "a@b.co", "password": "x" * 12}).status_code == 404
    assert client.post("/api/auth/signup", json={"invite_code": "x", "email": "a@b.co", "password": "x" * 12}).status_code == 404
    me = client.get("/api/auth/me").json()
    assert me["auth_required"] is False and me["media_token"] is None and me["user"]["quota"]["videos"]["limit"] is None
    for _ in range(4):  # more than the default daily limit of 3, no token
        r = client.post("/api/videos/upload", files={"file": ("v.mp4", sample_video.open("rb"), "video/mp4")})
        assert r.status_code == 201
        _wait_local = client.get(f"/api/jobs/{r.json()['job_id']}")
        assert _wait_local.status_code == 200
        time.sleep(0.1)
    assert client.get("/docs").status_code == 200
