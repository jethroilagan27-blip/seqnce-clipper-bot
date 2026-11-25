"""Each account brings its own Gemini key: kept encrypted, never shown again, used only for its owner's AI calls."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import admin, aikeys, auth, db
from app.ai import AIError, get_provider, no_key_reason
from app.ai.gemini import GeminiProvider
from app.config import get_settings

PASSWORD = "correct horse battery"
KEY_A = "AIzaSyA-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1111"
KEY_B = "AIzaSyB-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb2222"


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ac(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    auth.reset_throttle()
    aikeys.reset_throttle()
    checked: list[str] = []
    monkeypatch.setattr("app.api.account.check_key", lambda key: checked.append(key))  # no call to Google in tests
    c = request.getfixturevalue("client")
    c.checked = checked  # type: ignore[attr-defined]
    return c


def _join(c: TestClient, email: str) -> tuple[str, int]:
    r = c.post("/api/auth/signup", json={"invite_code": auth.new_invite(), "email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    return token, db.get_session_user(auth._sha(token))["id"]  # type: ignore[index]


def test_saving_a_key_hides_it_afterwards(ac: TestClient):
    token, uid = _join(ac, "a@example.com")
    assert ac.get("/api/account/ai-key", headers=_h(token)).json() == {"mode": "own", "has_key": False, "hint": None, "system": False}
    r = ac.put("/api/account/ai-key", json={"key": f"  {KEY_A}  "}, headers=_h(token))
    assert r.status_code == 200 and r.json() == {"mode": "own", "has_key": True, "hint": "…1111", "system": False}
    assert ac.checked == [KEY_A]  # it was checked with Google, trimmed
    assert r.headers["cache-control"] == "no-store"
    # nothing the server says afterwards contains the key
    for url in ("/api/account/ai-key", "/api/auth/me"):
        body = ac.get(url, headers=_h(token))
        assert KEY_A not in body.text and "AIza" not in body.text
    assert ac.get("/api/auth/me", headers=_h(token)).json()["user"]["ai"]["has_key"] is True
    # stored encrypted, not as text
    row = db.get_ai_key(uid)
    assert row is not None and KEY_A not in row["ciphertext"] and KEY_A[:12] not in row["ciphertext"]
    assert aikeys.load(uid) == KEY_A


def test_a_wrong_key_is_not_saved(ac: TestClient, monkeypatch: pytest.MonkeyPatch):
    token, uid = _join(ac, "a@example.com")

    def refuse(_key: str) -> None:
        raise AIError("Google says that key isn't valid. Copy it again from Google AI Studio.")

    monkeypatch.setattr("app.api.account.check_key", refuse)
    r = ac.put("/api/account/ai-key", json={"key": KEY_A}, headers=_h(token))
    assert r.status_code == 400 and "isn't valid" in r.json()["detail"] and KEY_A not in r.text
    assert db.get_ai_key(uid) is None
    for junk in ("", "short", "has spaces in it which is not a key at all", "x" * 250, "ключ" * 10):
        assert ac.put("/api/account/ai-key", json={"key": junk}, headers=_h(token)).status_code in (422,), junk


def test_the_newer_key_format_with_a_dot_is_accepted(ac: TestClient):
    token, uid = _join(ac, "a@example.com")
    newer = "AQ.Fake0000000000000000000000000000000000000000000000_x"
    assert ac.put("/api/account/ai-key", json={"key": newer}, headers=_h(token)).status_code == 200
    assert aikeys.load(uid) == newer


def test_the_backup_key_is_only_for_the_servers_key(ac: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_API_KEY", "server-key-" + "s" * 20)
    monkeypatch.setenv("GEMINI_API_KEY_BACKUP", "backup-key-" + "b" * 20)
    monkeypatch.setenv("SHARE_SERVER_AI_KEY", "true")
    get_settings.cache_clear()
    ta, ua = _join(ac, "a@example.com")
    _, ub = _join(ac, "b@example.com")
    shared = get_provider(ub)
    assert shared is not None and shared._backup is not None and shared._backup._api_key.startswith("backup-key-")  # type: ignore[attr-defined]
    ac.put("/api/account/ai-key", json={"key": KEY_A}, headers=_h(ta))
    assert get_provider(ua)._backup is None  # someone's own key never spills over onto yours  # type: ignore[union-attr]
    for url in ("/api/auth/me", "/api/account/ai-key"):
        assert "backup-key-" not in ac.get(url, headers=_h(ta)).text


def test_checking_keys_is_limited(ac: TestClient):
    token, _ = _join(ac, "a@example.com")
    codes = [ac.put("/api/account/ai-key", json={"key": KEY_A}, headers=_h(token)).status_code for _ in range(aikeys.TRIES_PER_WINDOW + 2)]
    assert codes[: aikeys.TRIES_PER_WINDOW] == [200] * aikeys.TRIES_PER_WINDOW and codes[-1] == 429


def test_replacing_and_removing_a_key(ac: TestClient):
    token, uid = _join(ac, "a@example.com")
    ac.put("/api/account/ai-key", json={"key": KEY_A}, headers=_h(token))
    assert ac.put("/api/account/ai-key", json={"key": KEY_B}, headers=_h(token)).json()["hint"] == "…2222"
    assert aikeys.load(uid) == KEY_B
    r = ac.delete("/api/account/ai-key", headers=_h(token))
    assert r.json()["has_key"] is False and db.get_ai_key(uid) is None


def test_the_ai_uses_only_its_owners_key(ac: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_API_KEY", "server-key-" + "s" * 20)
    get_settings.cache_clear()
    ta, ua = _join(ac, "a@example.com")
    tb, ub = _join(ac, "b@example.com")
    ac.put("/api/account/ai-key", json={"key": KEY_A}, headers=_h(ta))
    pa = get_provider(ua)
    assert isinstance(pa, GeminiProvider) and pa._api_key == KEY_A and pa._own_key
    assert get_provider(ub) is None  # B has no key: A's key and the server's key are not used for B
    assert get_provider(None) is None
    admin_id = admin.create_user("boss@example.com", PASSWORD, is_admin=True)
    boss = get_provider(admin_id)
    assert isinstance(boss, GeminiProvider) and boss._api_key.startswith("server-key-")  # admins fall back to the server's key
    assert "Me page" in no_key_reason()
    ac.put("/api/account/ai-key", json={"key": KEY_B}, headers=_h(tb))
    assert get_provider(ub)._api_key == KEY_B  # type: ignore[union-attr]
    assert get_provider(ua)._api_key == KEY_A  # type: ignore[union-attr]


def test_a_copied_row_is_useless_for_another_account(ac: TestClient):
    ta, ua = _join(ac, "a@example.com")
    _, ub = _join(ac, "b@example.com")
    ac.put("/api/account/ai-key", json={"key": KEY_A}, headers=_h(ta))
    row = db.get_ai_key(ua)
    db.set_ai_key(ub, row["ciphertext"], row["hint"])  # type: ignore[index]
    assert aikeys.load(ub) is None and aikeys.load(ua) == KEY_A


def test_a_damaged_row_means_no_key_not_a_crash(ac: TestClient):
    _, uid = _join(ac, "a@example.com")
    db.set_ai_key(uid, "not-a-real-token", "…zzzz")
    assert aikeys.load(uid) is None and get_provider(uid) is None


def test_a_job_without_a_key_falls_back_and_says_where_to_add_one(ac: TestClient, sample_video):
    token, _ = _join(ac, "a@example.com")
    with sample_video.open("rb") as f:
        r = ac.post("/api/videos/upload", files={"file": ("a.mp4", f, "video/mp4")}, headers=_h(token))
    assert r.status_code == 201, r.text
    import time

    job_id = r.json()["job_id"]
    for _ in range(150):
        job = ac.get(f"/api/jobs/{job_id}", headers=_h(token)).json()
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "completed"
    plan = ac.get(f"/api/jobs/{job_id}/analysis", headers=_h(token)).json().get("plan") or {}
    assert plan.get("source") == "fallback" and "Me page" in (plan.get("fallback_reason") or "")


def test_the_key_never_reaches_a_log_line():
    p = GeminiProvider(KEY_A, "m", 1, own_key=True)
    assert KEY_A not in p._scrub(f"HTTP 400: bad request for key={KEY_A}") and "[key]" in p._scrub(f"x {KEY_A} y")


def test_without_accounts_it_is_the_servers_own_setting(client: TestClient):
    assert client.get("/api/account/ai-key").json() == {"mode": "server", "has_key": False, "hint": None, "system": False}
    assert client.put("/api/account/ai-key", json={"key": KEY_A}).status_code == 404  # your own computer uses .env
    assert client.get("/api/auth/me").json()["user"]["ai"]["mode"] == "server"


# ---------- the check with Google (the real client is replaced by a fake) ----------

class _Models:
    def __init__(self, outcome):
        self.outcome = outcome

    def get(self, model):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return object()


def _fake_client(monkeypatch: pytest.MonkeyPatch, outcome):
    holder = {}

    class Client:
        def __init__(self, api_key):
            holder["key"] = api_key
            self.models = _Models(outcome)

        def __del__(self):  # the real client closes itself when it is garbage collected: the check must keep it alive
            holder["closed"] = True

    monkeypatch.setattr("app.ai.gemini.genai.Client", Client)
    return holder


def test_check_key_accepts_a_working_key_and_rejects_the_rest(monkeypatch: pytest.MonkeyPatch):
    from google.genai import errors

    from app.ai.gemini import check_key

    _fake_client(monkeypatch, None)
    check_key(KEY_A)  # works
    _fake_client(monkeypatch, errors.ClientError(429, {"error": {"message": "quota"}}))
    check_key(KEY_A)  # a real key that is just busy right now
    for code in (400, 401, 403):
        _fake_client(monkeypatch, errors.ClientError(code, {"error": {"message": "API key not valid"}}))
        with pytest.raises(AIError, match="isn't valid"):
            check_key(KEY_A)
    _fake_client(monkeypatch, errors.ServerError(500, {"error": {"message": "boom"}}))
    with pytest.raises(AIError, match="problem checking"):
        check_key(KEY_A)
    _fake_client(monkeypatch, ConnectionError("no network"))
    with pytest.raises(AIError, match="reach Google"):
        check_key(KEY_A)


def test_the_key_check_never_leaks_the_key_in_its_errors(monkeypatch: pytest.MonkeyPatch):
    from app.ai.gemini import check_key

    _fake_client(monkeypatch, ConnectionError(f"failed for key {KEY_A}"))
    with pytest.raises(AIError) as info:
        check_key(KEY_A)
    assert KEY_A not in str(info.value) and info.value.__cause__ is None and info.value.__suppress_context__
