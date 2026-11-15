"""Studio (scenes + voice-over + music + text -> video). Uses the real FFmpeg and real image decoding."""

from __future__ import annotations

import io
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from app import admin, auth, db, features
from app.config import get_settings
from app.studio import engine
from app.studio.schemas import Scene, StudioDoc, StudioText, Visual, frame_size

PASSWORD = "correct horse battery"


# ---------- helpers ----------

def _ffmpeg(*args: str) -> None:
    subprocess.run([get_settings().ffmpeg, "-y", "-loglevel", "error", *args], check=True)


def make_clip(path: Path, color: str = "blue", seconds: float = 2.0, audio: bool = True, size: str = "640x360") -> Path:
    cmd = ["-f", "lavfi", "-i", f"color=c={color}:s={size}:r=30:d={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"] + (["-c:a", "aac"] if audio else []) + ["-t", str(seconds), str(path)]
    _ffmpeg(*cmd)
    return path


def make_tone(path: Path, seconds: float = 2.0, hz: int = 330) -> Path:
    _ffmpeg("-f", "lavfi", "-i", f"sine=frequency={hz}:sample_rate=44100:duration={seconds}", str(path))
    return path


def png(color=(220, 20, 20), size=(800, 450)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _new(c: TestClient, headers: dict | None = None, title: str = "Test") -> str:
    r = c.post("/api/studio/projects", json={"title": title}, headers=headers or {})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _upload(c: TestClient, pid: str, path_or_bytes, name: str | None = None, headers: dict | None = None):
    if isinstance(path_or_bytes, Path):
        data, name = path_or_bytes.read_bytes(), name or path_or_bytes.name
    else:
        data = path_or_bytes
    return c.post(f"/api/studio/projects/{pid}/assets", files=[("files", (name, data, "application/octet-stream"))], headers=headers or {})


def _asset(c: TestClient, pid: str, path_or_bytes, name: str | None = None, headers: dict | None = None) -> str:
    r = _upload(c, pid, path_or_bytes, name, headers)
    assert r.status_code == 200 and r.json()["added"], r.text
    return r.json()["added"][0]["id"]


def vis(i: str, asset: str, **kw) -> dict:
    return {"id": i, "asset_id": asset, **kw}


def scene(i: str, **kw) -> dict:
    return {"id": i, "name": kw.pop("name", f"Scene {i}"), **kw}


def _put(c: TestClient, pid: str, scenes: list[dict], headers: dict | None = None, **doc):
    return c.put(f"/api/studio/projects/{pid}/doc", json={"title": "Test", "scenes": scenes, **doc}, headers=headers or {})


def _render(c: TestClient, pid: str, headers: dict | None = None, **body):
    return c.post(f"/api/studio/projects/{pid}/render", json=body or {"kind": "final"}, headers=headers or {})


def _wait(c: TestClient, pid: str, headers: dict | None = None, timeout: float = 120) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        p = c.get(f"/api/studio/projects/{pid}", headers=headers or {}).json()
        if p["status"] in ("completed", "failed"):
            return p
        time.sleep(0.3)
    raise AssertionError("render did not finish")


def _frame(video: Path, t: float, tmp: Path) -> Image.Image:
    out = tmp / f"f{t}.png"
    _ffmpeg("-ss", str(t), "-i", str(video), "-frames:v", "1", str(out))
    return Image.open(out).convert("RGB")


def _near(pixel, color, tol=45) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(pixel, color))


def _streams(path: Path) -> set[str]:
    proc = subprocess.run([get_settings().ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True, check=True)
    return set(proc.stdout.split())


def _out_path(c: TestClient, pid: str, which: str = "video", tmp: Path | None = None, params: str = "") -> Path:
    r = c.get(f"/api/studio/projects/{pid}/{which}{params}")
    assert r.status_code == 200, r.text
    dest = (tmp or Path(".")) / f"{which}-{pid[:6]}.mp4"
    dest.write_bytes(r.content)
    return dest


def ref(kind: str, duration: float = 0.0, audio: bool = True, name: str = "x", id: str = "a" * 16) -> engine.AssetRef:
    return engine.AssetRef(id, kind, Path("x"), duration, audio, name)


# ---------- the document ----------

def test_frame_sizes():
    assert frame_size("landscape", 1080) == (1920, 1080) and frame_size("landscape", 720) == (1280, 720)
    assert frame_size("vertical", 1080) == (1080, 1920) and frame_size("square", 360) == (360, 360)
    assert frame_size("landscape", 900) == (1280, 720) and frame_size("landscape", 100) == (640, 360)  # rounds down to a known size


def test_document_rules():
    with pytest.raises(ValidationError):
        StudioDoc(scenes=[Scene(id="a"), Scene(id="a")])  # same id twice
    with pytest.raises(ValidationError):
        Scene(id="a", background="red")
    with pytest.raises(ValidationError):
        Scene(id="has space")
    for bad in ("Arial, Bold", "Evil{font}", "x" * 80):
        with pytest.raises(ValidationError):
            StudioText(id="t", text="hi", font=bad)
    assert StudioText(id="t", text="hi", font="Playfair Display SC").font == "Playfair Display SC"


def test_references_and_removing_a_file():
    a, b, c_ = "a" * 16, "b" * 16, "c" * 16
    doc = StudioDoc(scenes=[Scene(id="s1", visuals=[Visual(id="v1", asset_id=a), Visual(id="v2", asset_id=b)],
                                  voiceover={"asset_id": c_}, music={"asset_id": a}), Scene(id="s2")], bed_music={"asset_id": c_})
    assert doc.asset_ids() == {a, b, c_}
    cleaned = doc.without_assets({a, c_})
    assert [v.asset_id for v in cleaned.scenes[0].visuals] == [b]
    assert cleaned.scenes[0].voiceover is None and cleaned.scenes[0].music is None and cleaned.bed_music is None
    assert doc.scenes[0].voiceover is not None  # the original is untouched


# ---------- planning (no files, no FFmpeg) ----------

def test_scene_length_comes_from_its_clips_pictures_voiceover_and_minimum():
    refs = {"v": ref("video", 10.0, id="1" * 16), "i": ref("image", id="2" * 16), "m": ref("audio", 7.0, id="3" * 16)}
    refs = {k: engine.AssetRef(a.id, a.kind, a.path, a.duration, a.has_audio, a.name) for k, a in refs.items()}
    by_id = {a.id: a for a in refs.values()}
    # a trimmed clip + a picture (3 s by default)
    p = engine.plan_scene(Scene(id="s", visuals=[Visual(id="1", asset_id="1" * 16, start=2, length=4), Visual(id="2", asset_id="2" * 16)]), by_id)
    assert p.duration == 7.0 and p.hold == 0
    # a voice-over longer than the picture holds the last picture
    p = engine.plan_scene(Scene(id="s", visuals=[Visual(id="1", asset_id="2" * 16, length=2)], voiceover={"asset_id": "3" * 16}), by_id)
    assert p.duration == 7.0 and p.hold == 5.0
    # a voice-over that starts late
    p = engine.plan_scene(Scene(id="s", voiceover={"asset_id": "3" * 16, "offset": 1.5}, min_duration=2), by_id)
    assert p.duration == 8.5 and p.visuals == [] and p.hold == 0
    # a title card is just a minimum length
    assert engine.plan_scene(Scene(id="s", min_duration=3.01), by_id).duration == pytest.approx(3.0, abs=1 / 30)  # whole frames
    # a clip with no length plays to its end
    assert engine.plan_scene(Scene(id="s", visuals=[Visual(id="1", asset_id="1" * 16, start=4)]), by_id).duration == 6.0


def test_scene_problems_have_plain_messages():
    by_id = {"1" * 16: ref("video", 5.0, id="1" * 16, name="clip.mp4"), "3" * 16: ref("audio", 5.0, id="3" * 16, name="song.mp3")}
    cases = [
        (Scene(id="s", name="Empty"), "empty"),
        (Scene(id="s", visuals=[Visual(id="1", asset_id="1" * 16, start=9)]), "past its end"),
        (Scene(id="s", visuals=[Visual(id="1", asset_id="4" * 16)]), "deleted"),
        (Scene(id="s", visuals=[Visual(id="1", asset_id="3" * 16)]), "can't be used"),  # audio as a clip
        (Scene(id="s", voiceover={"asset_id": "1" * 16}), "can't be used"),  # clip as a voice-over
    ]
    for sc, word in cases:
        with pytest.raises(engine.StudioError, match=word):
            engine.plan_scene(sc, by_id)


def test_describe_scenes_never_raises_and_counts_crossfades():
    by_id = {"1" * 16: ref("video", 10.0, id="1" * 16)}
    doc = StudioDoc(scenes=[
        Scene(id="a", visuals=[Visual(id="1", asset_id="1" * 16, length=4)]),
        Scene(id="b", visuals=[Visual(id="2", asset_id="1" * 16, length=4)], transition_in="crossfade", crossfade_s=1.0),
        Scene(id="c", name="Broken"),
    ])
    infos, total = engine.describe_scenes(doc, by_id)
    assert [i["duration"] for i in infos] == [4.0, 4.0, None] and "empty" in infos[2]["problem"]
    assert total == 7.0  # 4 + 4 - 1 s blended


def test_a_crossfade_never_eats_more_than_half_of_a_short_scene():
    by_id = {"1" * 16: ref("video", 10.0, id="1" * 16)}
    long_, short = (Scene(id=i, visuals=[Visual(id="1", asset_id="1" * 16, length=n)]) for i, n in (("a", 6), ("b", 1)))
    short = short.model_copy(update={"transition_in": "crossfade", "crossfade_s": 4})
    plans = [engine.plan_scene(long_, by_id), engine.plan_scene(short, by_id)]
    assert engine.crossfade_seconds(plans) == [0.0, 0.5]


def test_plan_limits():
    doc = StudioDoc(scenes=[Scene(id=str(i)) for i in range(4)] +
                    [Scene(id="x", transition_in="crossfade", texts=[StudioText(id="t", text="hi", anim="zoom_in")])])
    standard = features.resolve("standard")
    problems = engine.check_doc_allowed(doc, standard)
    assert any("Cross-fade" in p for p in problems) and any("zoom" in p for p in problems)
    assert engine.check_doc_allowed(doc, features.resolve("pro")) == []
    tiny = dict(features.resolve("pro"), studio_max_scenes=3)
    assert "3 scenes" in engine.check_doc_allowed(doc, tiny)[0]
    first_only = StudioDoc(scenes=[Scene(id="a", transition_in="crossfade")])  # a cross-fade into nothing is not a cross-fade
    assert engine.check_doc_allowed(first_only, standard) == []


def test_text_lines_carry_font_and_zoom_and_skip_texts_that_start_too_late():
    t = StudioText(id="t", text="THE GREATEST SHOWMAN", font="Georgia", anim="zoom_in", x=0.5, y=0.5, size=9, start=1, end=4)
    line = engine.text_line(t, 1920, 1080, 6.0)
    assert line and "\\fnGeorgia" in line and "\\t(0,3000,\\fscx112\\fscy112)" in line and "\\pos(960,540)" in line
    assert "0:00:01.00,0:00:04.00" in line
    assert "\\t(0,3000,\\fscx88" in engine.text_line(t.model_copy(update={"anim": "zoom_out"}), 1920, 1080, 6.0)  # type: ignore[arg-type]
    assert engine.text_line(StudioText(id="u", text="late", start=9), 1920, 1080, 6.0) is None
    ass = engine.scene_ass([t], 1920, 1080, 6.0)
    assert "PlayResX: 1920" in ass and "Dialogue:" in ass


def test_the_graph_option_is_one_this_ffmpeg_knows():
    assert engine.graph_flag() in ("-/filter_complex", "-filter_complex_script")


def test_fonts_listing_survives_an_empty_or_broken_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(engine, "FONTS_DIR", tmp_path / "none")
    assert engine.font_families() == []
    (tmp_path / "bad.ttf").write_bytes(b"not a font")
    monkeypatch.setattr(engine, "FONTS_DIR", tmp_path)
    assert engine.font_families() == []


# ---------- uploading and saving ----------

def test_upload_each_kind_and_refuse_the_rest(client: TestClient, tmp_path: Path):
    pid = _new(client)
    clip = _asset(client, pid, make_clip(tmp_path / "a.mp4", seconds=2))
    tone = _asset(client, pid, make_tone(tmp_path / "t.wav", 1.5))
    pic = _asset(client, pid, png(), "p.png")
    p = client.get(f"/api/studio/projects/{pid}").json()
    by_id = {a["id"]: a for a in p["assets"]}
    assert by_id[clip]["kind"] == "video" and by_id[clip]["duration"] == pytest.approx(2.0, abs=0.2) and by_id[clip]["has_audio"]
    assert by_id[clip]["width"] == 640 and by_id[tone]["kind"] == "audio" and by_id[tone]["duration"] == pytest.approx(1.5, abs=0.1)
    assert by_id[pic]["kind"] == "image" and (by_id[pic]["width"], by_id[pic]["height"]) == (800, 450)
    for asset in (clip, pic):  # clips and pictures have a thumbnail; audio doesn't
        assert client.get(f"/api/studio/projects/{pid}/assets/{asset}/thumb").status_code == 200
    assert client.get(f"/api/studio/projects/{pid}/assets/{tone}/thumb").status_code == 404
    assert client.get(f"/api/studio/projects/{pid}/assets/{clip}/file").status_code == 200

    for name, data in (("notes.txt", b"hello"), ("fake.mp4", b"this is not a video"), ("fake.wav", b"nope"), ("fake.jpg", b"nope")):
        r = _upload(client, pid, data, name)
        assert r.status_code == 200 and r.json()["added"] == [] and r.json()["rejected"][0]["name"] == name, name
    assert len(client.get(f"/api/studio/projects/{pid}").json()["assets"]) == 3  # nothing half-kept
    files = list((Path(get_settings().storage_dir) / "studio" / pid / "assets").iterdir())
    assert len(files) == 3 and all(len(f.stem) == 16 for f in files)  # server-made names only


def test_saving_the_document_checks_the_files_exist(client: TestClient, tmp_path: Path):
    pid = _new(client)
    clip = _asset(client, pid, make_clip(tmp_path / "a.mp4", seconds=2))
    ok = _put(client, pid, [scene("s1", visuals=[vis("v1", clip, length=1)])])
    assert ok.status_code == 200 and ok.json()["scenes"][0]["duration"] == pytest.approx(1.0, abs=0.04)
    assert ok.json()["total_seconds"] == pytest.approx(1.0, abs=0.04)
    assert _put(client, pid, [scene("s1", visuals=[vis("v1", "f" * 16)])]).status_code == 422  # no such file
    assert _put(client, pid, [scene("s1"), scene("s1")]).status_code == 422  # same id twice
    assert client.put(f"/api/studio/projects/{pid}/doc", json={"scenes": [{"id": "s1", "background": "red"}]}).status_code == 422


def test_deleting_a_file_removes_it_from_every_scene(client: TestClient, tmp_path: Path):
    pid = _new(client)
    clip = _asset(client, pid, make_clip(tmp_path / "a.mp4", seconds=2))
    tone = _asset(client, pid, make_tone(tmp_path / "t.wav"))
    assert _put(client, pid, [scene("s1", visuals=[vis("v1", clip)], voiceover={"asset_id": tone})],
                bed_music={"asset_id": tone}).status_code == 200
    r = client.delete(f"/api/studio/projects/{pid}/assets/{tone}")
    assert r.status_code == 200
    doc = r.json()["doc"]
    assert doc["scenes"][0]["voiceover"] is None and doc["bed_music"] is None and len(doc["scenes"][0]["visuals"]) == 1
    assert [a["id"] for a in r.json()["assets"]] == [clip]
    assert client.delete(f"/api/studio/projects/{pid}/assets/{tone}").status_code == 404


def test_project_lifecycle_and_limits(client: TestClient, tmp_path: Path):
    ids = [_new(client, title=f"P{i}") for i in range(3)]
    assert len(client.get("/api/studio/projects").json()["projects"]) == 3
    assert client.delete(f"/api/studio/projects/{ids[0]}").status_code == 204
    assert client.get(f"/api/studio/projects/{ids[0]}").status_code == 404
    assert not (Path(get_settings().storage_dir) / "studio" / ids[0]).exists()
    assert client.get("/api/studio/info").json()["limits"]["max_scenes"] >= 1


def test_asset_count_size_and_storage_limits_come_from_the_plan(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tiny = dict(features.resolve("max", admin=True), studio_max_assets=2, studio_max_file_mb=1, studio_max_storage_mb=3)
    monkeypatch.setattr(engine, "owner_features", lambda project: tiny)
    monkeypatch.setattr(auth, "features_of", lambda user: tiny)
    pid = _new(client)
    _asset(client, pid, png(size=(64, 64)), "a.png")
    big = tmp_path / "big.wav"
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=15", str(big))  # ~1.4 MB: over the 1 MB file limit
    r = _upload(client, pid, big)
    assert r.json()["added"] == [] and "1 MB" in r.json()["rejected"][0]["reason"]
    _asset(client, pid, png(size=(65, 65)), "b.png")
    r = _upload(client, pid, png(size=(66, 66)), "c.png")
    assert r.json()["added"] == [] and "at most 2" in r.json()["rejected"][0]["reason"]


# ---------- rendering for real ----------

def test_one_scene_preview_is_small_and_has_picture_and_sound(client: TestClient, tmp_path: Path):
    pid = _new(client)
    clip = _asset(client, pid, make_clip(tmp_path / "blue.mp4", "blue", 2))
    assert _put(client, pid, [scene("s1", visuals=[vis("v1", clip, length=1.5)])]).status_code == 200
    assert _render(client, pid, kind="preview", scene_id="s1").status_code == 202
    done = _wait(client, pid)
    assert done["status"] == "completed", done["error"]
    assert done["preview"] == {"scene": "s1"} and done["has_output"] is False  # a preview is not the finished video
    video = _out_path(client, pid, "preview", tmp_path, "?scene=s1")
    info = subprocess.run([get_settings().ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                           "-of", "csv=p=0", str(video)], capture_output=True, text=True, check=True).stdout
    assert "640,360" in info and _streams(video) == {"video", "audio"}
    assert _near(_frame(video, 0.7, tmp_path).getpixel((320, 180)), (0, 0, 255))


def test_picture_fitting_modes(client: TestClient, tmp_path: Path):
    """A portrait picture in a landscape frame: blurred copy behind it, black bars, or cut to fill."""
    pid = _new(client)
    pic = _asset(client, pid, png((230, 20, 20), size=(300, 600)), "tall.png")
    corners = {}
    for mode in ("blur", "fit", "crop"):
        assert _put(client, pid, [scene("s", visuals=[vis("v", pic, length=1, fit=mode)])]).status_code == 200
        assert _render(client, pid, kind="preview", scene_id="s").status_code == 202
        assert _wait(client, pid)["status"] == "completed"
        video = _out_path(client, pid, "preview", tmp_path, "?scene=s")
        frame = _frame(video, 0.5, tmp_path)
        corners[mode] = (frame.getpixel((10, 10)), frame.getpixel((320, 180)))
    assert corners["blur"][0][0] > 50 and corners["blur"][0][1] < 60  # a dimmed red copy, not black
    assert corners["fit"][0] == (0, 0, 0) or max(corners["fit"][0]) < 20  # black bars
    assert _near(corners["crop"][0], (230, 20, 20), 50) and all(_near(c[1], (230, 20, 20), 50) for c in corners.values())


def test_the_whole_video_with_title_voiceover_crossfade_music_and_fades(client: TestClient, tmp_path: Path):
    pid = _new(client)
    red = _asset(client, pid, png((230, 20, 20)), "red.png")
    blue = _asset(client, pid, make_clip(tmp_path / "blue.mp4", "blue", 2))
    voice = _asset(client, pid, make_tone(tmp_path / "vo.wav", 1.0, 523))
    song = _asset(client, pid, make_tone(tmp_path / "song.wav", 3.0, 196))
    scenes = [
        # 1: a black title card with a zooming title and a voice-over, fading in (2 s)
        scene("s1", name="Title", min_duration=2, fade_in=0.3,
              texts=[{"id": "t1", "text": "THE GREAT SHOW", "x": 0.5, "y": 0.5, "size": 12, "anim": "zoom_in", "font": "Arial"}],
              voiceover={"asset_id": voice, "volume": 1}),
        # 2: a picture (2 s) that is blended in over half a second
        scene("s2", name="Picture", visuals=[vis("v2", red, length=2, zoom="in")], transition_in="crossfade", crossfade_s=0.5),
        # 3: a blue clip (2 s), muted, music under it, fading out
        scene("s3", name="Clip", visuals=[vis("v3", blue, length=2, volume=0)], music={"asset_id": song, "volume": 0.5, "fade_in": 0.2}, fade_out=0.5),
    ]
    assert _put(client, pid, scenes, bed_music={"asset_id": song, "volume": 0.2, "fade_out": 1}).status_code == 200
    saved = client.get(f"/api/studio/projects/{pid}").json()
    assert saved["total_seconds"] == pytest.approx(5.5, abs=0.05)  # 2 + 2 + 2 - 0.5 blended

    assert _render(client, pid).status_code == 202
    done = _wait(client, pid)
    assert done["status"] == "completed", done["error"]
    assert done["has_output"] and done["output"]["width"] == 1920 and done["output"]["height"] == 1080  # local use = everything on
    assert done["output"]["duration"] == pytest.approx(5.5, abs=0.2)
    video = _out_path(client, pid, "video", tmp_path)
    assert _streams(video) == {"video", "audio"}

    start = _frame(video, 0.05, tmp_path)
    assert max(start.getpixel((100, 100))) < 30  # fading in from black
    title = _frame(video, 1.2, tmp_path)
    bright = sum(1 for x in range(600, 1320, 12) for y in range(440, 640, 12) if min(title.getpixel((x, y))) > 200)
    assert bright > 20, "the title text is on screen"
    assert max(title.getpixel((60, 60))) < 30  # ...on black
    mid = _frame(video, 1.75, tmp_path).getpixel((60, 60))
    assert 50 < mid[0] < 190 and mid[1] < 60, f"half way through the cross-fade the red is partly in: {mid}"  # black -> red
    assert _near(_frame(video, 3.0, tmp_path).getpixel((60, 60)), (230, 20, 20), 50)  # the picture, fully there
    assert _near(_frame(video, 4.3, tmp_path).getpixel((960, 540)), (0, 0, 255), 50)  # the blue clip
    assert max(_frame(video, 5.45, tmp_path).getpixel((960, 540))) < 60  # fading out to black at the end


def test_a_scene_with_a_deleted_or_broken_file_fails_with_a_plain_message_and_costs_nothing(client: TestClient, tmp_path: Path):
    pid = _new(client)
    assert _render(client, pid).status_code == 422  # nothing to render
    assert _put(client, pid, [scene("s1", name="Intro")]).status_code == 200
    r = _render(client, pid)
    assert r.status_code == 422 and "Intro" in r.json()["detail"] and "empty" in r.json()["detail"]
    assert client.get(f"/api/studio/projects/{pid}").json()["status"] == "draft"
    r = _render(client, pid, kind="final", scene_id="s1")
    assert r.status_code == 422  # a finished video is always the whole project


def test_projects_are_kept_for_at_least_30_days(client: TestClient):
    from app import studio

    pid = _new(client)
    from app.studio import store

    store.update(pid, status="completed")
    assert studio.purge(7) == 0  # a week old is nothing for a Studio project
    assert store.get(pid) is not None
    assert studio.purge(0) == 0  # 0 = keep forever


# ---------- who may use it ----------

@pytest.fixture
def ac(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("MAX_ACTIVE_JOBS_PER_USER", "1")
    auth.reset_throttle()
    return request.getfixturevalue("client")


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _join(c: TestClient, email: str) -> str:
    r = c.post("/api/auth/signup", json={"invite_code": auth.new_invite(), "email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def test_without_the_studio_feature_every_route_says_no(ac: TestClient, tmp_path: Path):
    token = _join(ac, "std@example.com")  # a new account is on the standard plan: no Studio
    h = _h(token)
    for method, url, body in (("get", "/api/studio/info", None), ("get", "/api/studio/projects", None),
                              ("post", "/api/studio/projects", {"title": "x"})):
        r = ac.request(method, url, json=body, headers=h)
        assert r.status_code == 403 and "plan" in r.json()["detail"], url
    # the same account with Studio switched on for it alone (everything else stays standard)
    admin.main(["set-feature", "std@example.com", "studio", "on"])
    assert ac.get("/api/studio/info", headers=h).status_code == 200
    me = ac.get("/api/auth/me", headers=h).json()["user"]
    assert me["plan"] == "standard" and me["features"]["studio"] is True and me["features"]["studio_crossfade"] is False


def test_pro_plan_works_and_standard_limits_apply_per_account(ac: TestClient, tmp_path: Path):
    token = _join(ac, "pro@example.com")
    h = _h(token)
    admin.main(["set-plan", "pro@example.com", "pro"])
    pid = _new(ac, h)
    pic = _asset(ac, pid, png(), "p.png", h)
    two = [scene("a", visuals=[vis("1", pic)]), scene("b", visuals=[vis("2", pic)], transition_in="crossfade")]
    assert _put(ac, pid, two, h).status_code == 200  # pro: cross-fade included
    admin.main(["set-feature", "pro@example.com", "studio_crossfade", "off"])  # ...unless switched off for this account
    r = _put(ac, pid, two, h)
    assert r.status_code == 403 and "Cross-fade" in r.json()["detail"]
    admin.main(["set-feature", "pro@example.com", "studio_max_scenes", "1"])
    assert "1 scenes" in _put(ac, pid, [scene("a"), scene("b")], h).json()["detail"]
    admin.main(["set-feature", "pro@example.com", "studio_max_projects", "1"])
    assert ac.post("/api/studio/projects", json={}, headers=h).status_code == 409  # one project allowed, one exists


def test_finished_videos_use_the_daily_studio_limit_but_previews_and_refusals_do_not(ac: TestClient, tmp_path: Path):
    token = _join(ac, "q@example.com")
    h = _h(token)
    admin.main(["set-plan", "q@example.com", "pro"])
    admin.main(["set-feature", "q@example.com", "studio_renders_per_day", "1"])
    admin.main(["set-feature", "q@example.com", "studio_max_height", "720"])
    pid = _new(ac, h)
    clip = _asset(ac, pid, make_clip(tmp_path / "c.mp4", "green", 1), None, h)
    assert _put(ac, pid, [scene("s", visuals=[vis("v", clip)])], h).status_code == 200
    used = lambda: ac.get("/api/auth/me", headers=h).json()["user"]["quota"]["studio"]["used"]  # noqa: E731

    assert _render(ac, pid, h, kind="preview", scene_id="s").status_code == 202
    assert _wait(ac, pid, h)["status"] == "completed" and used() == 0  # previews are free
    assert _render(ac, pid, h, kind="final", scene_id="nope").status_code == 422 and used() == 0  # refused: nothing spent

    assert _render(ac, pid, h, kind="final").status_code == 202 and used() == 1
    done = _wait(ac, pid, h)
    assert done["status"] == "completed" and (done["output"]["width"], done["output"]["height"]) == (1280, 720)  # this account's quality cap
    r = _render(ac, pid, h, kind="final")
    assert r.status_code == 429 and "Studio video" in r.json()["detail"] and used() == 1


def test_a_video_longer_than_the_plan_allows_is_refused_before_it_costs_anything(ac: TestClient, tmp_path: Path):
    token = _join(ac, "long@example.com")
    h = _h(token)
    admin.main(["set-plan", "long@example.com", "pro"])
    admin.main(["set-feature", "long@example.com", "studio_max_minutes", "1"])
    pid = _new(ac, h)
    assert _put(ac, pid, [scene("s", min_duration=90)], h).status_code == 200
    r = _render(ac, pid, h, kind="final")
    assert r.status_code == 422 and "allows up to 1" in r.json()["detail"]
    assert ac.get("/api/auth/me", headers=h).json()["user"]["quota"]["studio"]["used"] == 0


def test_other_users_cannot_see_or_touch_a_project(ac: TestClient, tmp_path: Path):
    a, b = _h(_join(ac, "a@example.com")), _h(_join(ac, "b@example.com"))
    for who in ("a@example.com", "b@example.com"):
        admin.main(["set-plan", who, "pro"])
    pid = _new(ac, a)
    asset = _asset(ac, pid, png(), "p.png", a)
    for method, url in (("get", f"/api/studio/projects/{pid}"), ("delete", f"/api/studio/projects/{pid}"),
                        ("delete", f"/api/studio/projects/{pid}/assets/{asset}"), ("get", f"/api/studio/projects/{pid}/assets/{asset}/thumb"),
                        ("get", f"/api/studio/projects/{pid}/video")):
        assert ac.request(method, url, headers=b).status_code == 404, url
    assert ac.put(f"/api/studio/projects/{pid}/doc", json={"scenes": []}, headers=b).status_code == 404
    assert ac.post(f"/api/studio/projects/{pid}/render", json={"kind": "preview"}, headers=b).status_code == 404
    assert _upload(ac, pid, png(), "q.png", b).status_code == 404
    assert ac.get("/api/studio/projects", headers=b).json()["projects"] == []
    assert len(ac.get("/api/studio/projects", headers=a).json()["projects"]) == 1


def test_uploads_are_refused_before_being_read_when_not_signed_in(ac: TestClient):
    r = ac.post(f"/api/studio/projects/{'0' * 32}/assets", files=[("files", ("a.png", png(), "image/png"))])
    assert r.status_code == 401
