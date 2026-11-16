"""Studio's assistant chat and folder names. A stand-in AI is used, so these tests are exact and free."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import admin
from app.ai import AIError
from app.studio import chat
from app.studio.chat import AiClip, AiHighlight, AiOverlay, AiScene, AiStudioReply, AiText

from .test_studio import (  # noqa: F401  (ac is a fixture)
    _asset,
    _frame,
    _h,
    _join,
    _new,
    _out_path,
    _put,
    _render,
    _wait,
    ac,
    make_clip,
    make_tone,
    png,
)


class FakeAI:
    """Stands in for Gemini: hands back the replies it was given, in order, and remembers every prompt."""

    name = "fake"

    def __init__(self, *replies: AiStudioReply | Exception):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def generate_structured(self, prompt, response_model, images=None):
        self.prompts.append(prompt)
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def ai(monkeypatch: pytest.MonkeyPatch):
    def install(*replies):
        fake = FakeAI(*replies)
        monkeypatch.setattr(chat, "get_provider", lambda *a, **k: fake)
        return fake

    return install


def _upload_in(c: TestClient, pid: str, path_or_bytes, name: str, folder: str, headers: dict | None = None) -> str:
    data = path_or_bytes.read_bytes() if isinstance(path_or_bytes, Path) else path_or_bytes
    r = c.post(f"/api/studio/projects/{pid}/assets", files=[("files", (name, data, "application/octet-stream"))], data={"folders": folder}, headers=headers or {})
    assert r.status_code == 200 and r.json()["added"], r.text
    return r.json()["added"][0]["id"]


def _say(c: TestClient, pid: str, text: str, headers: dict | None = None):
    return c.post(f"/api/studio/projects/{pid}/chat", json={"message": text}, headers=headers or {})


def _project(c: TestClient, pid: str, headers: dict | None = None) -> dict:
    return c.get(f"/api/studio/projects/{pid}", headers=headers or {}).json()


@pytest.fixture
def members(client: TestClient, tmp_path: Path):
    """A project shaped like the Greatest Showman folders: one folder per member, numbered voice-overs, a poster."""
    pid = _new(client)
    ids = {
        "vidal": _upload_in(client, pid, make_clip(tmp_path / "a.mp4", "red", 2, size="320x180"), "Wide shot.mp4", "Members/Vidal"),
        "deo": _upload_in(client, pid, make_clip(tmp_path / "b.mp4", "blue", 2, size="320x180"), "Side view.mp4", "Members/Deogracias"),
        "vo1": _upload_in(client, pid, make_tone(tmp_path / "vo1.wav", 2.0, 440), "VO 1.wav", "Voice overs"),
        "vo2": _upload_in(client, pid, make_tone(tmp_path / "vo2.wav", 3.0, 523), "VO 2.wav", "Voice overs"),
        "poster": _upload_in(client, pid, png(), "poster.png", ""),
    }
    return pid, ids


# ---------- folders ----------

def test_a_files_folder_is_kept_as_a_clean_label(client: TestClient, tmp_path: Path):
    pid = _new(client)
    clip = make_clip(tmp_path / "a.mp4", "red", 1, audio=False)
    ok = _upload_in(client, pid, clip, "clip.mp4", "Members\\Vidal")
    odd = _upload_in(client, pid, clip, "clip2.mp4", "../../etc/./passwd\x00/..")
    none = _asset(client, pid, clip, "plain.mp4")
    got = {a["id"]: a for a in _project(client, pid)["assets"]}
    assert got[ok]["folder"] == "Members/Vidal" and got[ok]["name"] == "clip.mp4"
    assert got[odd]["folder"] == "etc/passwd"  # no dots, no ".." and no control characters
    assert got[none]["folder"] == ""
    long = _upload_in(client, pid, clip, "c3.mp4", "/".join(["x" * 90] * 12))
    assert len({a["id"]: a for a in _project(client, pid)["assets"]}[long]["folder"]) <= 200


def test_folders_are_matched_to_files_in_order_when_several_come_together(client: TestClient, tmp_path: Path):
    pid = _new(client)
    a = make_clip(tmp_path / "a.mp4", "red", 1, audio=False).read_bytes()
    r = client.post(f"/api/studio/projects/{pid}/assets", files=[("files", ("one.mp4", a, "video/mp4")), ("files", ("two.mp4", a, "video/mp4"))],
                    data={"folders": ["First", "Second"]})
    assert [x["folder"] for x in r.json()["added"]] == ["First", "Second"]


# ---------- what the AI is told ----------

def test_the_ai_is_shown_every_file_with_its_folder_and_the_current_scenes_and_the_script(client: TestClient, members, ai):
    pid, ids = members
    fake = ai(AiStudioReply(message="Just checking.", change="none"))
    assert _say(client, pid, "VIDEO (10 seconds): Vidal talks about the film").status_code == 200
    prompt = fake.prompts[0]
    assert f"{ids['vidal']} | video | Members/Vidal/Wide shot.mp4" in prompt
    assert f"{ids['vo2']} | audio | Voice overs/VO 2.wav | 3.0 s" in prompt
    assert f"{ids['poster']} | image | poster.png" in prompt
    assert "VIDEO (10 seconds): Vidal talks about the film" in prompt
    assert "(no scenes yet)" in prompt and "Use ONLY ids from the list" in prompt


# ---------- turning the AI's answer into scenes ----------

def _script_reply(ids: dict[str, str]) -> AiStudioReply:
    return AiStudioReply(message="I built three scenes from your script.", change="replace_all", scenes=[
        AiScene(name="Question", kind="text_card", min_seconds=3, fade_in_s=0.5, fade_out_s=0.5,
                texts=[AiText(text="Where did this story begin?", x=0.5, y=0.5, size=8, color="white", font="Comic Nonexistent")]),
        AiScene(name="Origin", voiceover_asset_id=ids["vo2"], music_asset_id="0" * 16, crossfade_from_previous=True,
                clips=[AiClip(asset_id=ids["vidal"], use_s=1.5, muted=True), AiClip(asset_id="f" * 16), AiClip(asset_id=ids["vo1"])],
                overlays=[AiOverlay(asset_id=ids["poster"], x=7, y=-2, width=0.3, start_s=0.5, end_s=2.0, effect="pop"), AiOverlay(asset_id="e" * 16)],
                highlights=[AiHighlight(kind="pin", x=0.4, y=0.6, w=0.05, color="red")]),
        AiScene(name="Members", kind="grid", voiceover_asset_id=ids["vo1"], grid_columns=3, grid_rows=2, grid_wait_s=1.0,
                clips=[AiClip(asset_id=ids["vidal"]), AiClip(asset_id=ids["deo"])]),
    ])


def test_a_script_becomes_scenes_and_every_bad_thing_in_the_answer_is_fixed_or_left_out_with_a_note(client: TestClient, members, ai):
    pid, ids = members
    ai(_script_reply(ids))
    r = _say(client, pid, "PART 1 ... the whole script ...")
    assert r.status_code == 200, r.text
    body = r.json()
    doc = body["project"]["doc"]
    assert [s["name"] for s in doc["scenes"]] == ["Question", "Origin", "Members"]
    q, origin, grid = doc["scenes"]
    assert q["min_duration"] == 3 and q["texts"][0]["font"] == "" and q["texts"][0]["text"] == "Where did this story begin?"
    # the origin scene: the one real clip kept (muted, 1.5 s), the unknown id and the audio file dropped, the music id refused
    assert [v["asset_id"] for v in origin["visuals"]] == [ids["vidal"]] and origin["visuals"][0]["volume"] == 0 and origin["visuals"][0]["length"] == 1.5
    assert origin["voiceover"]["asset_id"] == ids["vo2"] and origin["music"] is None and origin["transition_in"] == "crossfade"
    assert [o["asset_id"] for o in origin["overlays"]] == [ids["poster"]] and (origin["overlays"][0]["x"], origin["overlays"][0]["y"]) == (1.0, 0.0)  # clamped
    assert origin["overlays"][0]["anim"] == "pop" and origin["shapes"][0]["color"] == "#ff3b30" and origin["shapes"][0]["anim"] == "drop"  # named colours become real ones
    # the grid: both cells muted because a voice-over plays, cut to fill, a dark start
    assert grid["grid"]["delay"] == 1.0 and [c["volume"] for c in grid["grid"]["cells"]] == [0, 0] and grid["grid"]["cells"][0]["fit"] == "crop"
    reply = body["messages"][-1]["text"]
    assert "I built three scenes" in reply and "Comic Nonexistent" in reply and "couldn't use" in reply  # the user is told what was dropped
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"] and body["can_undo"] is True
    assert all(s["duration"] and not s["problem"] for s in body["project"]["scenes"]), body["project"]["scenes"]


def test_a_scene_with_nothing_in_it_is_left_out_and_the_user_is_told(client: TestClient, members, ai):
    pid, ids = members
    ai(AiStudioReply(message="Built it.", change="replace_all", scenes=[
        AiScene(name="PART 1 - INTRODUCTION"),  # a heading turned into a scene
        AiScene(name="Origin", clips=[AiClip(asset_id=ids["vidal"])]),
        AiScene(name="Lost", clips=[AiClip(asset_id="d" * 16)]),  # every file it named was refused
        AiScene(name="Question", kind="text_card"),  # a text card gets its own length, so it is not empty
    ]))
    body = _say(client, pid, "build").json()
    assert [s["name"] for s in body["project"]["doc"]["scenes"]] == ["Origin", "Question"]
    text = body["messages"][-1]["text"]
    assert "“PART 1 - INTRODUCTION” had nothing in it" in text and "“Lost” had nothing in it" in text


def test_an_answer_that_is_mostly_empty_scenes_gets_one_more_try_with_the_problems_spelled_out(client: TestClient, members, ai):
    pid, ids = members
    bad = AiStudioReply(message="I built a grid.", change="replace_all", scenes=[AiScene(name="Watching", kind="grid"), AiScene(name="Watching", kind="grid")])
    good = AiStudioReply(message="Now with the clips.", change="replace_all", scenes=[
        AiScene(name="Watching", kind="grid", clips=[AiClip(asset_id=ids["vidal"]), AiClip(asset_id=ids["deo"])])])
    fake = ai(bad, good)
    body = _say(client, pid, "show the members together").json()
    assert len(fake.prompts) == 2 and "PREVIOUS ANSWER WAS NOT USABLE" in fake.prompts[1] and "had nothing in it" in fake.prompts[1]
    assert [s["name"] for s in body["project"]["doc"]["scenes"]] == ["Watching"] and len(body["project"]["doc"]["scenes"][0]["grid"]["cells"]) == 2
    assert "Now with the clips" in body["messages"][-1]["text"]


def test_a_second_bad_answer_does_not_make_things_worse_and_a_mostly_fine_answer_is_not_asked_again(client: TestClient, members, ai):
    pid, ids = members
    ai(AiStudioReply(message="first", change="replace_all", scenes=[AiScene(name="Mine", clips=[AiClip(asset_id=ids["vidal"])])]))
    _say(client, pid, "start")
    mine = _project(client, pid)["doc"]["scenes"]
    assert [s["name"] for s in mine] == ["Mine"]
    empty = AiScene(name="Heading")
    fake = ai(AiStudioReply(message="a", change="replace_all", scenes=[empty, empty]), AiStudioReply(message="b", change="replace_all", scenes=[empty]))
    body = _say(client, pid, "x").json()
    assert len(fake.prompts) == 2
    assert body["project"]["doc"]["scenes"] == mine  # still nothing usable: the user's scenes are left exactly as they were
    assert "changed nothing" in body["messages"][-1]["text"]
    fine = AiStudioReply(message="c", change="replace_all", scenes=[AiScene(name="One", clips=[AiClip(asset_id=ids["vidal"])]), AiScene(name="Two", clips=[AiClip(asset_id=ids["deo"])]), empty])
    fake2 = ai(fine)
    _say(client, pid, "y")
    assert len(fake2.prompts) == 1  # one of three dropped: no retry


def test_the_ai_is_never_asked_to_write_free_text_colours():
    """A model that has to write "#000000" can get stuck writing zeros until it runs out of room (seen for real)."""
    schema = AiStudioReply.model_json_schema()
    props = {name: p for d in schema["$defs"].values() for name, p in d.get("properties", {}).items()}
    assert "background_color" not in props
    for name, p in props.items():
        if "color" in name:
            assert "enum" in p or "$ref" in p, f"{name} must be a fixed choice, not free text"
    assert set(chat.COLORS) == {"white", "black", "yellow", "red", "blue", "green", "orange", "pink"}


def test_the_schema_sent_to_the_ai_requires_every_field_but_our_code_still_accepts_defaults():
    """Optional fields get skipped by a lazy model (seen for real: one scene, no clips). Required ones can't be."""
    schema = AiStudioReply.model_json_schema()
    for name, d in [("AiStudioReply", schema), *schema["$defs"].items()]:
        assert set(d["required"]) == set(d["properties"]), name
    assert AiScene().clips == [] and AiClip(asset_id="x").use_s == 0  # leaving fields out in our own code still works
    assert all(len(hex_) == 7 and hex_.startswith("#") for hex_ in chat.COLORS.values())


def test_the_prompt_explains_grids_headings_and_voiceover_numbers(client: TestClient, members, ai):
    pid, _ = members
    fake = ai(AiStudioReply(message="ok", change="none"))
    _say(client, pid, "x")
    for phrase in ("AT THE SAME TIME", "Do not make a scene out of a heading", "Voice over N", "wrong file"):
        assert phrase in fake.prompts[0], phrase


def test_scenes_the_ai_says_are_unchanged_stay_exactly_as_they_are_and_changed_ones_keep_their_id(client: TestClient, members, ai):
    pid, ids = members
    ai(_script_reply(ids))
    first = _say(client, pid, "build it").json()["project"]["doc"]["scenes"]
    keep, change = first[0], first[1]
    ai(AiStudioReply(message="Kept the first, made the second longer.", change="replace_all", scenes=[
        AiScene(existing_scene_id=keep["id"], unchanged=True),
        AiScene(existing_scene_id=change["id"], name="Origin (longer)", min_seconds=8, voiceover_asset_id=ids["vo2"]),
    ]))
    scenes = _say(client, pid, "make the second one 8 seconds").json()["project"]["doc"]["scenes"]
    assert scenes[0] == keep  # untouched, even its text ids
    assert scenes[1]["id"] == change["id"] and scenes[1]["name"] == "Origin (longer)" and scenes[1]["min_duration"] == 8
    assert len(scenes) == 2


def test_a_question_changes_nothing_and_the_old_chat_is_remembered(client: TestClient, members, ai):
    pid, _ = members
    fake = ai(AiStudioReply(message="You have 5 files.", change="none"), AiStudioReply(message="Still 5.", change="none"))
    body = _say(client, pid, "how many files do I have?").json()
    assert body["messages"][-1]["text"] == "You have 5 files." and body["can_undo"] is False and body["project"]["doc"]["scenes"] == []
    _say(client, pid, "and now?")
    assert "User: how many files do I have?" in fake.prompts[1] and "You: You have 5 files." in fake.prompts[1]


def test_undo_puts_the_scenes_back_and_only_once(client: TestClient, members, ai):
    pid, ids = members
    assert client.post(f"/api/studio/projects/{pid}/chat/undo").status_code == 409  # nothing yet
    ai(_script_reply(ids))
    _say(client, pid, "build it")
    assert len(_project(client, pid)["doc"]["scenes"]) == 3
    body = client.post(f"/api/studio/projects/{pid}/chat/undo").json()
    assert body["project"]["doc"]["scenes"] == [] and body["can_undo"] is False
    assert client.post(f"/api/studio/projects/{pid}/chat/undo").status_code == 409
    assert "Undone" in body["messages"][-1]["text"]


def test_undo_forgets_files_that_were_deleted_in_the_meantime(client: TestClient, members, ai):
    pid, ids = members
    ai(_script_reply(ids))
    _say(client, pid, "build it")
    assert _put(client, pid, [], title="x").status_code == 200  # the user clears the scenes by hand...
    # ...but first make the assistant's old version point at a file that is then deleted
    client.delete(f"/api/studio/projects/{pid}/assets/{ids['vidal']}")
    restored = client.post(f"/api/studio/projects/{pid}/chat/undo").json()["project"]["doc"]["scenes"]
    assert all(v["asset_id"] != ids["vidal"] for s in restored for v in s["visuals"])


def test_a_built_project_really_renders(client: TestClient, members, ai, tmp_path: Path):
    pid, ids = members
    ai(AiStudioReply(message="ok", change="replace_all", scenes=[
        AiScene(name="Origin", voiceover_asset_id=ids["vo1"], clips=[AiClip(asset_id=ids["vidal"], muted=True)],
                overlays=[AiOverlay(asset_id=ids["poster"], x=0.5, y=0.5, width=0.3)])]))
    _say(client, pid, "build it")
    assert _render(client, pid, kind="preview", scene_id=_project(client, pid)["doc"]["scenes"][0]["id"]).status_code == 202
    done = _wait(client, pid)
    assert done["status"] == "completed", done["error"]


# ---------- who may use it, and what it costs ----------

def test_the_assistant_needs_the_feature_and_uses_the_daily_chat_limit(ac: TestClient, tmp_path: Path, ai):
    token = _join(ac, "chat@example.com")
    h = _h(token)
    admin.main(["set-feature", "chat@example.com", "studio", "on"])  # studio, but on the standard plan: no assistant
    pid = _new(ac, h)
    assert _say(ac, pid, "hi", h).status_code == 403 and ac.get(f"/api/studio/projects/{pid}/chat", headers=h).status_code == 403
    assert ac.post(f"/api/studio/projects/{pid}/chat/undo", headers=h).status_code == 403

    admin.main(["set-feature", "chat@example.com", "studio_ai_chat", "on"])
    admin.main(["set-limits", "chat@example.com", "--chats", "2"])
    used = lambda: ac.get("/api/auth/me", headers=h).json()["user"]["quota"]["chats"]["used"]  # noqa: E731
    fake = ai(AiStudioReply(message="a", change="none"), AIError("The AI service is rate-limited right now."), AiStudioReply(message="b", change="none"),
              AiStudioReply(message="c", change="none"))
    assert _say(ac, pid, "one", h).status_code == 200 and used() == 1
    r = _say(ac, pid, "two", h)
    assert r.status_code == 502 and "rate-limited" in r.json()["detail"] and used() == 1  # a failed answer costs nothing
    assert _say(ac, pid, "three", h).status_code == 200 and used() == 2
    r = _say(ac, pid, "four", h)
    assert r.status_code == 429 and len(fake.prompts) == 3  # refused before the AI was even asked


def test_without_an_ai_key_it_says_so_and_costs_nothing(client: TestClient, members, monkeypatch: pytest.MonkeyPatch):
    pid, _ = members
    monkeypatch.setattr(chat, "get_provider", lambda *a, **k: None)
    r = _say(client, pid, "hello")
    assert r.status_code == 503 and "GEMINI_API_KEY" in r.json()["detail"]
    assert client.get(f"/api/studio/projects/{pid}/chat").json()["messages"] == []


def test_tools_the_plan_lacks_are_not_offered_and_are_removed_from_the_answer(ac: TestClient, tmp_path: Path, ai):
    token = _join(ac, "lim@example.com")
    h = _h(token)
    for key, value in (("studio", "on"), ("studio_ai_chat", "on")):
        admin.main(["set-feature", "lim@example.com", key, value])  # standard plan + studio + chat: no overlays / grid / credits / cross-fade
    pid = _new(ac, h)
    clip = _asset(ac, pid, make_clip(tmp_path / "a.mp4", "red", 1, audio=False), None, h)
    pic = _asset(ac, pid, png(), "p.png", h)
    fake = ai(AiStudioReply(message="Built.", change="replace_all", scenes=[
        AiScene(name="One", clips=[AiClip(asset_id=clip)], overlays=[AiOverlay(asset_id=pic)], narrow_frame_opening=True),
        AiScene(name="Two", kind="grid", clips=[AiClip(asset_id=clip)], crossfade_from_previous=True),
        AiScene(name="Three", kind="credits", credits_lines=["a"]),
    ]))
    body = _say(ac, pid, "make it fancy", h).json()
    assert "does NOT include" in fake.prompts[0] and "grid scenes" in fake.prompts[0]
    scenes = body["project"]["doc"]["scenes"]
    assert scenes[0]["overlays"] == [] and scenes[0]["open_effect"] == "none"
    assert scenes[1]["grid"] is None and [v["asset_id"] for v in scenes[1]["visuals"]] == [clip] and scenes[1]["transition_in"] == "cut"
    assert len(scenes) == 2 and "“Three” had nothing in it" in body["messages"][-1]["text"]  # a credits scene without the credits is empty: left out
    assert "doesn't include" in body["messages"][-1]["text"]
    assert _put(ac, pid, scenes, h).status_code == 200  # what was built is something this plan may keep


def test_the_number_of_scenes_follows_the_plan(client: TestClient, members, ai, monkeypatch: pytest.MonkeyPatch):
    from app import auth, features

    small = dict(features.resolve("max", admin=True), studio_max_scenes=2)
    monkeypatch.setattr(auth, "features_of", lambda user: small)
    pid, _ = members
    ai(AiStudioReply(message="ok", change="replace_all", scenes=[AiScene(name=f"S{i}", min_seconds=2) for i in range(5)]))
    body = _say(client, pid, "five scenes").json()
    assert [s["name"] for s in body["project"]["doc"]["scenes"]] == ["S0", "S1"] and "allows 2 scenes" in body["messages"][-1]["text"]


def test_other_users_cannot_read_or_use_someone_elses_chat(ac: TestClient, tmp_path: Path, ai):
    a, b = _h(_join(ac, "a@example.com")), _h(_join(ac, "b@example.com"))
    for who in ("a@example.com", "b@example.com"):
        admin.main(["set-plan", who, "pro"])
    pid = _new(ac, a)
    ai(AiStudioReply(message="hi", change="none"))
    _say(ac, pid, "hello", a)
    assert ac.get(f"/api/studio/projects/{pid}/chat", headers=b).status_code == 404
    assert _say(ac, pid, "hello", b).status_code == 404
    assert ac.post(f"/api/studio/projects/{pid}/chat/undo", headers=b).status_code == 404


def test_the_message_size_is_limited(client: TestClient, members):
    pid, _ = members
    assert _say(client, pid, "x" * (chat.MAX_MESSAGE_CHARS + 1)).status_code == 422
    assert _say(client, pid, "").status_code == 422
