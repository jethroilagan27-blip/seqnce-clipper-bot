"""Plans and per-account features (app/features.py), the admin commands, and what /api/auth/me reports."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import admin, auth, db, features
from app.config import get_settings

PASSWORD = "correct horse battery"


@pytest.fixture
def ac(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    auth.reset_throttle()
    return request.getfixturevalue("client")


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _join(c: TestClient, email: str = "a@example.com") -> dict:
    r = c.post("/api/auth/signup", json={"invite_code": auth.new_invite(), "email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()


def _me(c: TestClient, token: str) -> dict:
    return c.get("/api/auth/me", headers=_h(token)).json()["user"]


# ---------- the plan table ----------

def test_every_plan_defines_every_feature_with_the_right_type():
    for name in features.PLAN_NAMES:
        plan = features.PLANS[name]
        assert set(plan) == set(features.FEATURES), name
        for key, (kind, _) in features.FEATURES.items():
            assert isinstance(plan[key], kind) and not (kind is int and isinstance(plan[key], bool)), (name, key)


def test_standard_has_no_studio_and_pro_and_max_do():
    assert features.resolve("standard")["studio"] is False
    assert features.resolve("pro")["studio"] is True and features.resolve("max")["studio"] is True
    # plans only get bigger as you go up
    for key, (kind, _) in features.FEATURES.items():
        if kind is int:
            assert features.PLANS["standard"][key] <= features.PLANS["pro"][key] <= features.PLANS["max"][key], key


def test_unknown_plan_falls_back_to_standard_and_admins_get_everything():
    assert features.resolve("gold") == features.resolve("standard") == features.resolve(None)
    admin_values = features.resolve("standard", {"studio": False}, admin=True)  # overrides can't lock an admin out
    assert admin_values["studio"] is True and admin_values["studio_renders_per_day"] is None


def test_overrides_change_one_value_and_junk_is_ignored():
    got = features.resolve("standard", {"studio": True, "studio_max_height": 1080, "nonsense": 5, "studio_max_scenes": "x"})
    assert got["studio"] is True and got["studio_max_height"] == 1080
    assert got["studio_max_scenes"] == features.PLANS["standard"]["studio_max_scenes"]  # broken value dropped
    assert "nonsense" not in got
    assert features.clean_overrides("not a dict") == {} and features.clean_overrides(None) == {}


def test_parse_value_accepts_words_and_numbers_and_refuses_the_rest():
    assert features.parse_value("studio", "on") is True and features.parse_value("studio", "No") is False
    assert features.parse_value("studio_max_scenes", "12") == 12
    for key, raw in (("studio", "maybe"), ("studio_max_scenes", "ten"), ("studio_max_scenes", "-1"), ("studio_max_scenes", True), ("nope", "1")):
        with pytest.raises(ValueError):
            features.parse_value(key, raw)


# ---------- what the API reports ----------

def test_new_accounts_are_standard_without_studio(ac: TestClient):
    me = _me(ac, _join(ac)["token"])
    assert me["plan"] == "standard" and me["features"]["studio"] is False
    assert me["quota"]["studio"]["limit"] == features.PLANS["standard"]["studio_renders_per_day"]


def test_changing_the_plan_or_one_feature_shows_up_at_once(ac: TestClient, capsys: pytest.CaptureFixture[str]):
    token = _join(ac)["token"]
    assert admin.main(["set-plan", "a@example.com", "pro"]) == 0
    me = _me(ac, token)
    assert me["plan"] == "pro" and me["features"]["studio"] is True and me["features"]["studio_max_height"] == 1080
    assert admin.main(["set-feature", "a@example.com", "studio_max_height", "720"]) == 0
    assert _me(ac, token)["features"]["studio_max_height"] == 720  # one value changed, the rest still pro
    assert _me(ac, token)["features"]["studio_max_scenes"] == features.PLANS["pro"]["studio_max_scenes"]
    out = capsys.readouterr().out
    assert "studio_max_height" in out and "*" in out  # the changed value is marked
    assert admin.main(["set-feature", "a@example.com", "studio_max_height", "default"]) == 0
    assert _me(ac, token)["features"]["studio_max_height"] == 1080  # back to what the plan says
    assert db.get_user_by_email("a@example.com")["features_json"] is None  # nothing left over


def test_admins_see_everything_in_me_and_have_no_studio_limit(ac: TestClient):
    token = _join(ac)["token"]
    db.update_user(db.get_user_by_email("a@example.com")["id"], is_admin=1)
    me = _me(ac, token)
    assert me["plan"] == "max" and me["features"]["studio"] is True and me["quota"]["studio"]["limit"] is None


def test_admin_commands_refuse_bad_input(ac: TestClient):
    _join(ac)
    with pytest.raises(SystemExit):
        admin.main(["set-feature", "a@example.com", "studio", "maybe"])
    with pytest.raises(SystemExit):
        admin.main(["set-plan", "nobody@example.com", "pro"])
    with pytest.raises(SystemExit):
        admin.main(["set-plan", "a@example.com", "gold"])


def test_features_command_lists_every_feature(ac: TestClient, capsys: pytest.CaptureFixture[str]):
    _join(ac)
    capsys.readouterr()
    assert admin.main(["features", "a@example.com"]) == 0
    out = capsys.readouterr().out
    assert all(key in out for key in features.FEATURES)


def test_require_feature_says_403_when_it_is_off(ac: TestClient):
    _join(ac)
    user = auth._to_user(db.get_user_by_email("a@example.com"))
    with pytest.raises(Exception) as err:
        auth.require_feature(user, "studio")
    assert getattr(err.value, "status_code", None) == 403
    db.update_user(user.id, plan="pro")
    assert auth.require_feature(auth._to_user(db.get_user(user.id)), "studio")["studio"] is True  # type: ignore[arg-type]


def test_the_biggest_file_follows_the_servers_upload_limit_not_a_fixed_number(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """On your own computer there is no reason for Studio to refuse a 300 MB phone video the server itself accepts."""
    limit = get_settings().max_upload_mb  # the test server's MAX_UPLOAD_MB
    me = client.get("/api/auth/me").json()["user"]  # accounts off: local use
    assert me["features"]["studio_max_file_mb"] == limit != features.PLANS["pro"]["studio_max_file_mb"]
    assert client.get("/api/studio/info").json()["limits"]["max_file_mb"] == limit

    monkeypatch.setenv("MAX_UPLOAD_MB", "500")  # the normal local setting
    get_settings.cache_clear()
    admin_user = auth.User(id=1, email="a@x.co", is_admin=True)
    pro = auth.User(id=2, email="p@x.co", is_admin=False, plan="pro")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()
    assert auth.features_of(admin_user)["studio_max_file_mb"] == 500  # admins: all of it
    assert auth.features_of(pro)["studio_max_file_mb"] == min(features.PLANS["pro"]["studio_max_file_mb"], 500)  # a plan can only lower it
    monkeypatch.setenv("MAX_UPLOAD_MB", "5000")  # the public setup: the plan is what limits a normal account
    get_settings.cache_clear()
    assert auth.features_of(pro)["studio_max_file_mb"] == features.PLANS["pro"]["studio_max_file_mb"]
    assert auth.features_of(admin_user)["studio_max_file_mb"] == 5000
    monkeypatch.setenv("MAX_UPLOAD_MB", "50")  # a server that accepts less than the plan says
    get_settings.cache_clear()
    assert auth.features_of(pro)["studio_max_file_mb"] == 50 and auth.features_of(admin_user)["studio_max_file_mb"] == 50
    get_settings.cache_clear()


def test_with_accounts_off_everyone_has_everything(client: TestClient):
    me = client.get("/api/auth/me").json()["user"]
    assert me["features"]["studio"] is True and me["quota"]["studio"]["limit"] is None


# ---------- upgrading an existing database ----------

def test_an_old_database_gets_the_new_columns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    storage = tmp_path / "old"
    storage.mkdir()
    monkeypatch.setenv("STORAGE_DIR", str(storage))
    get_settings.cache_clear()
    conn = sqlite3.connect(storage / "svb.sqlite3")
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, "
        "is_admin INTEGER NOT NULL DEFAULT 0, disabled INTEGER NOT NULL DEFAULT 0, video_limit INTEGER, chat_limit INTEGER, created_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO users (email, password_hash, created_at) VALUES ('old@example.com', 'x', '2026-01-01')")
    conn.commit()
    conn.close()
    try:
        db.init_db()
        row = db.get_user_by_email("old@example.com")
        assert row["plan"] == "standard" and row["features_json"] is None
        db.update_user(row["id"], features_json=json.dumps({"studio": True}))
        assert features.resolve("standard", auth._to_user(db.get_user(row["id"])).overrides)["studio"] is True  # type: ignore[arg-type]
    finally:
        get_settings.cache_clear()
