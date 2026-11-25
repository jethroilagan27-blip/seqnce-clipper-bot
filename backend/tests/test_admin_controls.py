"""What an admin can change per account (plan, daily limits, beta access) and the usage graphs."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone
from datetime import time as daytime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import admin, auth, db, features
from app.ai import get_provider
from app.config import get_settings

PASSWORD = "correct horse battery"


@pytest.fixture
def ac(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    auth.reset_throttle()
    return request.getfixturevalue("client")


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _join(c: TestClient, email: str) -> tuple[str, int]:
    r = c.post("/api/auth/signup", json={"invite_code": auth.new_invite(), "email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()["token"], db.get_user_by_email(email)["id"]  # type: ignore[index]


def _boss(c: TestClient) -> dict[str, str]:
    token, uid = _join(c, "boss@example.com")
    db.update_user(uid, is_admin=1)
    return _h(token)


def _me(c: TestClient, token: str) -> dict:
    return c.get("/api/auth/me", headers=_h(token)).json()["user"]


def _change(c: TestClient, uid: int, headers: dict[str, str], **change):
    return c.patch(f"/api/admin/users/{uid}", json=change, headers=headers)


# ---------- plans, limits, beta ----------

def test_only_an_admin_can_change_accounts(ac: TestClient):
    boss = _boss(ac)
    token, uid = _join(ac, "a@example.com")
    assert _change(ac, uid, {}, plan="pro").status_code == 401
    assert _change(ac, uid, _h(token), plan="pro").status_code == 404  # not even your own
    assert ac.get("/api/admin/stats", headers=_h(token)).status_code == 404
    assert _me(ac, token)["plan"] == "standard"
    assert _change(ac, uid, boss, plan="pro").status_code == 200
    assert _me(ac, token)["plan"] == "pro"


def test_pro_has_higher_limits_and_a_limit_for_one_account_comes_first(ac: TestClient):
    boss = _boss(ac)
    token, uid = _join(ac, "a@example.com")
    cfg = get_settings()
    assert _me(ac, token)["quota"]["videos"]["limit"] == cfg.daily_video_limit
    pro = _change(ac, uid, boss, plan="pro").json()
    assert pro["limits"] == {"videos": 15, "chats": 100} and pro["studio"] is True and pro["video_limit"] is None
    assert _me(ac, token)["quota"]["chats"]["limit"] == 100 > cfg.daily_chat_limit
    own = _change(ac, uid, boss, video_limit=1).json()
    assert own["limits"] == {"videos": 1, "chats": 100} and own["plan"] == "pro"  # nothing else touched
    user = auth._to_user(db.get_user(uid))  # type: ignore[arg-type]
    auth.spend_quota(user, "video")
    with pytest.raises(Exception) as err:
        auth.spend_quota(user, "video")
    assert getattr(err.value, "status_code", None) == 429
    assert _change(ac, uid, boss, video_limit=None).json()["limits"]["videos"] == 15  # back to the plan
    assert _change(ac, uid, boss, chat_limit=0).json()["limits"]["chats"] == 0  # zero is a real limit


def test_beta_access_is_switched_per_account(ac: TestClient):
    boss = _boss(ac)
    token, uid = _join(ac, "a@example.com")
    assert ac.get("/api/studio/projects", headers=_h(token)).status_code == 403
    got = _change(ac, uid, boss, studio=True, studio_ai_chat=False).json()
    assert got["studio"] is True and got["studio_ai_chat"] is False and got["plan"] == "standard"
    assert ac.get("/api/studio/projects", headers=_h(token)).status_code == 200
    assert db.get_user(uid)["features_json"] == '{"studio": true}'  # type: ignore[index]  # only what differs from the plan
    _change(ac, uid, boss, plan="pro", studio=False, studio_ai_chat=True)
    assert ac.get("/api/studio/projects", headers=_h(token)).status_code == 403  # beta can be hidden from a pro account
    _change(ac, uid, boss, studio=None)
    assert db.get_user(uid)["features_json"] is None  # type: ignore[index]
    assert _me(ac, token)["features"]["studio"] is True


def test_other_hand_set_features_survive_a_change(ac: TestClient):
    boss = _boss(ac)
    _, uid = _join(ac, "a@example.com")
    admin.main(["set-feature", "a@example.com", "studio_max_scenes", "12"])
    _change(ac, uid, boss, studio=True)
    assert auth._to_user(db.get_user(uid)).overrides == {"studio_max_scenes": 12, "studio": True}  # type: ignore[arg-type]


def test_bad_changes_are_refused(ac: TestClient):
    boss = _boss(ac)
    _, uid = _join(ac, "a@example.com")
    for bad in ({"plan": "gold"}, {"video_limit": -1}, {"video_limit": "5"}, {"chat_limit": 10_001}, {"is_admin": True}, {"disabled": True}):
        assert _change(ac, uid, boss, **bad).status_code == 422, bad
    assert _change(ac, 999, boss, plan="pro").status_code == 404
    admin_id = db.get_user_by_email("boss@example.com")["id"]  # type: ignore[index]
    assert _change(ac, admin_id, boss, video_limit=1).status_code == 400
    row = db.get_user(uid)
    assert (row["plan"], row["video_limit"], row["is_admin"]) == ("standard", None, 0)  # type: ignore[index]


def test_the_list_says_what_each_plan_and_account_allows(ac: TestClient):
    boss = _boss(ac)
    _join(ac, "a@example.com")
    body = ac.get("/api/admin/users", headers=boss).json()
    assert body["plans"]["pro"] == {"videos": 15, "chats": 100, "studio": True, "studio_ai_chat": True}
    assert body["plans"]["standard"]["videos"] == get_settings().daily_video_limit
    standard, mine = body["users"][0], body["users"][1]
    assert standard["limits"] == {"videos": get_settings().daily_video_limit, "chats": get_settings().daily_chat_limit}
    assert mine["is_admin"] and mine["limits"] == {"videos": None, "chats": None}


def test_plans_only_allow_more_as_you_go_up():
    for kind in ("video", "chat"):
        assert auth.plan_limit("standard", kind) <= features.PLAN_LIMITS["pro"][kind] <= features.PLAN_LIMITS["max"][kind]  # type: ignore[operator]


def test_the_website_may_send_a_change(ac: TestClient):
    origin = get_settings().cors_origin_list[0]
    r = ac.options("/api/admin/users/1", headers={"Origin": origin, "Access-Control-Request-Method": "PATCH"})
    assert r.status_code == 200 and "PATCH" in r.headers["access-control-allow-methods"]


# ---------- the graphs ----------

def _wait(c: TestClient, job_id: str, headers: dict[str, str], version: int) -> None:
    for _ in range(300):
        job = c.get(f"/api/jobs/{job_id}", headers=headers).json()
        if job["status"] in ("completed", "failed") and not job["revising"] and (job["current_version"] == version or job["error"]):
            return
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_videos_changes_and_ai_requests_are_counted_per_day_and_account(ac: TestClient, sample_video: Path, monkeypatch: pytest.MonkeyPatch):
    boss = _boss(ac)
    token, uid = _join(ac, "a@example.com")
    _, other = _join(ac, "b@example.com")
    with sample_video.open("rb") as f:
        job_id = ac.post("/api/videos/upload", files={"file": ("a.mp4", f, "video/mp4")}, headers=_h(token)).json()["job_id"]
    _wait(ac, job_id, _h(token), 1)
    url = f"/api/jobs/{job_id}/revisions"
    assert ac.post(url, json={"edit": {"captions_enabled": False}}, headers=_h(token)).status_code == 202
    _wait(ac, job_id, _h(token), 2)
    assert ac.post(url, json={"restore_version": 1}, headers=_h(token)).status_code == 202  # going back is not an edit
    _wait(ac, job_id, _h(token), 3)

    monkeypatch.setenv("GEMINI_API_KEY", "server-key-" + "s" * 24)
    monkeypatch.setenv("SHARE_SERVER_AI_KEY", "true")
    get_settings.cache_clear()
    provider = get_provider(other)
    provider._on_request()  # type: ignore[union-attr]
    provider._on_request()  # type: ignore[union-attr]

    r = ac.get("/api/admin/stats?days=7", headers=boss)
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert len(body["days"]) == 7 and body["days"][-1]["date"] == datetime.now(timezone.utc).date().isoformat()
    assert body["totals"] == {"videos": 1, "changes": 1, "ai": 2, "ai_own": 0}
    assert {u["user_id"]: (u["videos"], u["changes"], u["ai"]) for u in body["per_user"]} == {uid: (1, 1, 0), other: (0, 0, 2)}
    one = ac.get(f"/api/admin/stats?days=7&user_id={other}", headers=boss).json()
    assert one["totals"] == {"videos": 0, "changes": 0, "ai": 2, "ai_own": 0} and len(one["per_user"]) == 2


def test_days_start_at_the_viewers_midnight(ac: TestClient):
    boss = _boss(ac)
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    late = datetime.combine(yesterday, daytime(20), timezone.utc).isoformat(timespec="seconds")  # 04:00 the next day in Manila
    with db.connect() as conn:
        conn.execute("INSERT INTO activity (user_id, kind, created_at) VALUES (2, 'ai', ?)", (late,))

    def per_day(tz: int) -> dict[str, int]:
        return {d["date"]: d["ai"] for d in ac.get(f"/api/admin/stats?days=4&tz={tz}", headers=boss).json()["days"]}

    assert per_day(0)[yesterday.isoformat()] == 1
    assert per_day(480)[today.isoformat()] == 1
    for bad in ("days=0", "days=366", "tz=900", "user_id=0"):
        assert ac.get(f"/api/admin/stats?{bad}", headers=boss).status_code == 422, bad


def test_every_request_sent_to_the_ai_is_counted_even_retries(monkeypatch: pytest.MonkeyPatch):
    from google.genai import errors as genai_errors

    from app.ai.base import AIError
    from app.ai.gemini import GeminiProvider
    from app.ai.schemas import PlanProposal

    sent: list[int] = []
    provider = GeminiProvider("x" * 30, "m", max_retries=3, on_request=lambda: sent.append(1))

    def busy(**_):
        raise genai_errors.APIError(503, {"error": {"message": "busy"}})

    monkeypatch.setattr(provider._client.models, "generate_content", busy)
    monkeypatch.setattr("app.ai.gemini.time.sleep", lambda _s: None)
    with pytest.raises(AIError):
        provider.generate_structured("hi", PlanProposal)
    assert len(sent) == 3


def test_the_graphs_start_with_what_an_older_database_still_has(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    storage = tmp_path / "old"
    storage.mkdir()
    monkeypatch.setenv("STORAGE_DIR", str(storage))
    get_settings.cache_clear()
    try:
        db.init_db()
        db.create_job("a" * 32, "a.mp4", "x", {}, None, user_id=7)
        db.add_version("a" * 32, 1, plan={}, source="initial")
        db.add_version("a" * 32, 2, plan={}, source="chat")
        db.add_version("a" * 32, 3, plan={}, source="restore")
        with sqlite3.connect(storage / "svb.sqlite3") as conn:
            conn.execute("DROP TABLE activity")  # as it was before the graphs existed
        db.init_db()
        db.init_db()  # only once
        assert sorted((u, k) for u, k, _ in db.activity_since("2000-01-01")) == [(7, "edit"), (7, "video")]
    finally:
        get_settings.cache_clear()
