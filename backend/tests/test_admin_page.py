"""The admin page (every account, read-only) and sharing the server's Gemini key with everyone."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import admin, aikeys, auth, db
from app.ai import get_provider
from app.config import get_settings

PASSWORD = "correct horse battery"
SERVER_KEY = "server-key-" + "s" * 24


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


def _login(c: TestClient, email: str) -> str:
    r = c.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_only_an_admin_sees_the_accounts(ac: TestClient):
    boss = _join(ac, "boss@example.com")
    other = _join(ac, "user@example.com")
    assert ac.get("/api/admin/users").status_code == 401
    assert ac.get("/api/admin/users", headers=_h(boss)).status_code == 404  # signing up never makes anyone an admin
    assert ac.get("/api/admin/users", headers=_h(other)).status_code == 404
    admin.main(["make-admin", "boss@example.com"])
    assert ac.get("/api/admin/users", headers=_h(boss)).status_code == 200
    assert ac.get("/api/admin/users", headers=_h(other)).status_code == 404


def test_the_list_shows_every_account_newest_first_without_secrets(ac: TestClient):
    admin.create_user("boss@example.com", PASSWORD, is_admin=True)
    _join(ac, "first@example.com")
    _join(ac, "second@example.com")
    uid = db.get_user_by_email("first@example.com")["id"]  # type: ignore[index]
    assert db.try_record_usage(uid, "chat", None, auth.QUOTA_WINDOW)
    assert db.try_record_usage(uid, "chat", None, auth.QUOTA_WINDOW)
    assert db.try_record_usage(uid, "video", None, auth.QUOTA_WINDOW)

    r = ac.get("/api/admin/users", headers=_h(_login(ac, "boss@example.com")))
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["totals"] == {"accounts": 3, "new_24h": 3, "new_7d": 3}
    assert [u["email"] for u in body["users"]] == ["second@example.com", "first@example.com", "boss@example.com"]
    first = body["users"][1]
    assert (first["chats_24h"], first["videos_24h"], first["videos_stored"], first["is_admin"], first["plan"]) == (2, 1, 0, False, "standard")
    assert body["users"][2]["is_admin"] is True
    assert "password" not in r.text and "scrypt" not in r.text and "ciphertext" not in r.text


def test_there_is_no_admin_page_on_your_own_computer(client: TestClient):
    assert client.get("/api/admin/users").status_code == 404


# ---------- sharing the server's key ----------

@pytest.fixture
def shared(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> TestClient:
    monkeypatch.setenv("SHARE_SERVER_AI_KEY", "true")
    c = request.getfixturevalue("ac")
    monkeypatch.setenv("GEMINI_API_KEY", SERVER_KEY)
    get_settings.cache_clear()
    return c


def test_with_sharing_on_every_account_uses_the_servers_key(shared: TestClient):
    token = _join(shared, "user@example.com")
    uid = db.get_user_by_email("user@example.com")["id"]  # type: ignore[index]
    provider = get_provider(uid)
    assert provider is not None and provider._api_key == SERVER_KEY and not provider._own_key  # type: ignore[attr-defined]
    me = shared.get("/api/auth/me", headers=_h(token))
    assert me.json()["user"]["ai"] == {"mode": "server", "has_key": True, "hint": None}
    assert SERVER_KEY not in me.text
    aikeys.save(uid, "AIzaSyA-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1111")  # a key saved earlier is kept, but not used while sharing is on
    assert get_provider(uid)._api_key == SERVER_KEY  # type: ignore[union-attr]


def test_with_sharing_on_but_no_server_key_nobody_has_ai(monkeypatch: pytest.MonkeyPatch, shared: TestClient):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    token = _join(shared, "user@example.com")
    assert get_provider(db.get_user_by_email("user@example.com")["id"]) is None  # type: ignore[index]
    assert shared.get("/api/auth/me", headers=_h(token)).json()["user"]["ai"]["has_key"] is False
