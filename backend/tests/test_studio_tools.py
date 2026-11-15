"""Studio's tools for heavier edits: pictures over a scene, highlights, grid, credits, ducking, fonts.

Real FFmpeg, real renders. Helpers come from test_studio.py."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from app import admin, features
from app.config import get_settings
from app.studio import engine
from app.studio.schemas import Credits, Grid, Overlay, Scene, Shape, StudioDoc, Visual

from .test_studio import (  # noqa: F401  (ac is a fixture)
    _asset,
    _frame,
    _h,
    _join,
    _near,
    _new,
    _out_path,
    _put,
    _render,
    _streams,
    _upload,
    _wait,
    ac,
    make_clip,
    make_tone,
    png,
    ref,
    scene,
    vis,
)


def _half_red_png() -> bytes:
    """200 x 200: the left half solid red, the right half see-through."""
    im = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    im.paste((230, 20, 20, 255), (0, 0, 100, 200))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _preview(c: TestClient, pid: str, scene_id: str, tmp: Path) -> Path:
    assert _render(c, pid, kind="preview", scene_id=scene_id).status_code == 202
    done = _wait(c, pid)
    assert done["status"] == "completed", done["error"]
    return _out_path(c, pid, "preview", tmp, f"?scene={scene_id}")


def _mean_volume(path: Path) -> float:
    proc = subprocess.run([get_settings().ffmpeg, "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True)
    line = next(ln for ln in proc.stderr.splitlines() if "mean_volume" in ln)
    return float(line.split("mean_volume:")[1].split("dB")[0])


GREEN = (0, 128, 0)  # what ffmpeg's "green" is


def test_see_through_pictures_stay_see_through_and_plain_ones_become_jpeg(client: TestClient):
    pid = _new(client)
    logo = _asset(client, pid, _half_red_png(), "logo.png")
    plain = _asset(client, pid, png(), "plain.png")
    files = {f.stem: f.suffix for f in (Path(get_settings().storage_dir) / "studio" / pid / "assets").iterdir()}
    assert files[logo] == ".png" and files[plain] == ".jpg"
    assert client.get(f"/api/studio/projects/{pid}/assets/{logo}/thumb").status_code == 200


def test_pictures_over_a_scene_show_only_while_they_should_and_keep_their_see_through_parts(client: TestClient, tmp_path: Path):
    pid = _new(client)
    base = _asset(client, pid, make_clip(tmp_path / "green.mp4", "green", 2, audio=False))
    logo = _asset(client, pid, _half_red_png(), "logo.png")
    s = scene("s", visuals=[vis("v", base)], overlays=[{"id": "o1", "asset_id": logo, "x": 0.5, "y": 0.5, "width": 0.4, "start": 0.5, "end": 1.5}])
    assert _put(client, pid, [s]).status_code == 200
    video = _preview(client, pid, "s", tmp_path)
    assert _near(_frame(video, 0.2, tmp_path).getpixel((250, 180)), GREEN)  # not there yet
    on = _frame(video, 1.0, tmp_path)
    assert _near(on.getpixel((250, 180)), (230, 20, 20)) and _near(on.getpixel((390, 180)), GREEN)  # red half is there, the other is see-through
    assert _near(_frame(video, 1.8, tmp_path).getpixel((250, 180)), GREEN)  # gone again


def test_highlights_and_pins_are_drawn_and_the_narrow_frame_opens(client: TestClient, tmp_path: Path):
    pid = _new(client)
    base = _asset(client, pid, make_clip(tmp_path / "green.mp4", "green", 2, audio=False))
    shapes = [
        {"id": "r", "kind": "rect", "x": 0.15, "y": 0.2, "w": 0.2, "h": 0.2, "color": "#ffd400", "thickness": 1.0, "fill": 0},
        {"id": "p", "kind": "pin", "x": 0.8, "y": 0.8, "w": 0.06, "color": "#ff0000"},
        {"id": "e", "kind": "ellipse", "x": 0.5, "y": 0.6, "w": 0.2, "h": 0.2, "color": "#0000ff", "fill": 1.0, "thickness": 0, "start": 1.2},
    ]
    s = scene("s", visuals=[vis("v", base)], shapes=shapes, open_effect="letterbox", open_s=1.0)
    assert _put(client, pid, [s]).status_code == 200
    video = _preview(client, pid, "s", tmp_path)
    early, late = _frame(video, 0.05, tmp_path), _frame(video, 1.5, tmp_path)
    assert max(early.getpixel((320, 20))) < 25 and max(early.getpixel((320, 340))) < 25  # the bars cover the top and the bottom
    assert _near(early.getpixel((320, 180)), GREEN)  # the middle band shows the picture
    assert _near(late.getpixel((320, 20)), GREEN)  # opened
    edge = [late.getpixel((x, 72)) for x in range(24, 41)]
    assert any(p[0] > 200 and p[1] > 170 and p[2] < 100 for p in edge), "the yellow box's edge"
    assert _near(late.getpixel((512, 250)), (255, 0, 0), 70), "the pin's round head"
    assert _near(late.getpixel((320, 216)), (0, 0, 255), 70), "the filled circle that appears at 1.2 s"
    assert not _near(_frame(video, 0.9, tmp_path).getpixel((320, 216)), (0, 0, 255), 70)  # ...and not before


def test_a_grid_shows_every_clip_at_once_in_its_own_cell(client: TestClient, tmp_path: Path):
    pid = _new(client)
    colours = {"red": (255, 0, 0), "lime": (0, 255, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0), "cyan": (0, 255, 255), "magenta": (255, 0, 255)}
    cells = []
    for i, name in enumerate(colours):
        clip = _asset(client, pid, make_clip(tmp_path / f"{name}.mp4", name, 1.5, audio=False, size="320x180"))
        cells.append(vis(f"c{i}", clip, fit="crop", volume=0))
    s = scene("g", grid={"cols": 3, "rows": 2, "gap": 8, "cells": cells})
    saved = _put(client, pid, [s]).json()
    assert saved["scenes"][0]["duration"] == pytest.approx(1.5, abs=0.04)  # all cells play together
    video = _preview(client, pid, "g", tmp_path)
    frame = _frame(video, 0.7, tmp_path)
    centres = [(109, 91), (320, 91), (531, 91), (109, 268), (320, 268), (531, 268)]
    for (name, rgb), xy in zip(colours.items(), centres):
        assert _near(frame.getpixel(xy), rgb, 60), (name, xy, frame.getpixel(xy))
    assert max(frame.getpixel((2, 2))) < 25  # the background around the cells


def test_grid_cells_can_appear_together_after_a_dark_start_while_the_voiceover_already_plays(client: TestClient, tmp_path: Path):
    """The last scene of the script: the voice-over begins on a dark screen, then all six members suddenly appear."""
    pid = _new(client)
    cells = []
    for i, name in enumerate(("red", "lime", "blue", "yellow", "cyan", "magenta")):
        clip = _asset(client, pid, make_clip(tmp_path / f"{name}.mp4", name, 1.5, audio=False, size="320x180"))
        cells.append(vis(f"c{i}", clip, fit="crop", volume=0))
    voice = _asset(client, pid, make_tone(tmp_path / "vo.wav", 2.0, 440))
    s = scene("g", voiceover={"asset_id": voice, "volume": 1}, grid={"cols": 3, "rows": 2, "gap": 8, "delay": 1.0, "cells": cells})
    saved = _put(client, pid, [s]).json()
    assert saved["scenes"][0]["duration"] == pytest.approx(2.5, abs=0.04)  # 1 s dark + 1.5 s of clips (the voice-over, 2 s, fits inside)
    video = _preview(client, pid, "g", tmp_path)
    assert max(_frame(video, 0.5, tmp_path).getpixel((109, 91))) < 25  # still dark
    after = _frame(video, 1.5, tmp_path)
    assert _near(after.getpixel((109, 91)), (255, 0, 0), 60) and _near(after.getpixel((531, 268)), (255, 0, 255), 60)  # all there at once
    assert _mean_volume(video) > -40  # the voice-over plays during the dark part too


def test_credits_scroll_up_the_screen_for_the_time_asked(client: TestClient, tmp_path: Path):
    pid = _new(client)
    lines = ["# THE CAST", "Hugh Jackman", "Zac Efron", "", "# THE TEAM", "Michael Gracey", "Benj Pasek"]
    s = scene("c", credits={"lines": lines, "seconds": 4, "size": 6})
    saved = _put(client, pid, [s]).json()
    assert saved["scenes"][0]["duration"] == pytest.approx(4.0, abs=0.04)
    video = _preview(client, pid, "c", tmp_path)

    def white(frame: Image.Image, y0: int, y1: int) -> int:
        return sum(1 for x in range(0, 640, 4) for y in range(y0, y1, 3) if min(frame.getpixel((x, y))) > 200)

    assert white(_frame(video, 0.05, tmp_path), 0, 360) < 15  # still below the screen
    assert white(_frame(video, 2.0, tmp_path), 0, 360) > 40  # in the middle of the roll
    assert white(_frame(video, 3.9, tmp_path), 200, 360) < 15  # almost all gone off the top


def test_credits_get_a_comfortable_length_by_themselves_and_clips_can_share_a_voiceover_evenly():
    short, long_ = Credits(lines=["a"]), Credits(lines=[f"line {i}" for i in range(60)])
    assert 8 < engine.credits_seconds(short) < 14  # even one line has to travel the whole way up the screen
    assert engine.credits_seconds(long_) > engine.credits_seconds(Credits(lines=["a"] * 20)) > engine.credits_seconds(short)
    assert engine.credits_seconds(Credits(lines=["a"], seconds=9)) == 9.0
    imgs = {c * 16: ref("image", id=c * 16) for c in "123"} | {"4" * 16: ref("audio", 6.0, id="4" * 16), "5" * 16: ref("video", 1.0, id="5" * 16)}
    three = [Visual(id=str(i), asset_id=c * 16) for i, c in enumerate("123")]
    p = engine.plan_scene(Scene(id="s", visuals=three, voiceover={"asset_id": "4" * 16}, fit_to_voiceover=True), imgs)
    assert [length for _, _, length in p.visuals] == [2.0, 2.0, 2.0] and p.duration == 6.0 and p.hold == 0
    # a clip shorter than its share plays what it has; the last one is held to fill the rest
    mix = [Visual(id="a", asset_id="1" * 16), Visual(id="b", asset_id="5" * 16)]
    p = engine.plan_scene(Scene(id="s", visuals=mix, voiceover={"asset_id": "4" * 16}, fit_to_voiceover=True), imgs)
    assert [length for _, _, length in p.visuals] == [3.0, 1.0] and p.duration == 6.0 and p.hold == 2.0
    # off by default: pictures keep their own 3 seconds
    assert engine.plan_scene(Scene(id="s", visuals=three, voiceover={"asset_id": "4" * 16}), imgs).duration == 9.0


def test_music_ducks_under_speech_only_when_asked_and_allowed(client: TestClient, tmp_path: Path):
    by_id = {"1" * 16: ref("audio", 3.0, id="1" * 16), "2" * 16: ref("audio", 3.0, id="2" * 16)}
    sc = Scene(id="s", min_duration=3, voiceover={"asset_id": "1" * 16}, music={"asset_id": "2" * 16})
    assert engine.plan_scene(sc, by_id, duck_allowed=True).duck is True
    assert engine.plan_scene(sc, by_id, duck_allowed=False).duck is False  # the plan doesn't include it
    assert engine.plan_scene(sc.model_copy(update={"music": sc.music.model_copy(update={"duck": False})}), by_id, duck_allowed=True).duck is False
    assert engine.plan_scene(Scene(id="s", min_duration=3, music={"asset_id": "2" * 16}), by_id, duck_allowed=True).duck is False  # nobody speaks
    _, graph = engine.build_scene_graph(engine.plan_scene(sc, by_id, duck_allowed=True), 640, 360, False)
    assert "sidechaincompress" in graph and "sidechaincompress" not in engine.build_scene_graph(engine.plan_scene(sc, by_id), 640, 360, False)[1]

    pid = _new(client)
    voice = _asset(client, pid, make_tone(tmp_path / "vo.wav", 3.0, 523))
    song = _asset(client, pid, make_tone(tmp_path / "song.wav", 3.0, 196))
    means = {}
    for duck in (False, True):
        # ffmpeg's test tone peaks at 0.125. A quiet voice (still above the ducking trigger) over loud music makes the effect
        # big enough to measure: the loud music is what gets lowered.
        s = scene("s", min_duration=3, voiceover={"asset_id": voice, "volume": 0.6}, music={"asset_id": song, "volume": 2.0, "duck": duck})
        assert _put(client, pid, [s], normalize_loudness=False).status_code == 200  # "even out the volume" would hide the difference
        means[duck] = _mean_volume(_preview(client, pid, "s", tmp_path))
    assert means[True] < means[False] - 1.0, f"ducked {means[True]} dB vs not ducked {means[False]} dB"


def test_a_font_file_can_be_uploaded_and_is_used_by_name(client: TestClient, tmp_path: Path):
    pid = _new(client)
    bad = _upload(client, pid, b"this is not a font", "fake.ttf")
    assert bad.json()["added"] == [] and "font" in bad.json()["rejected"][0]["reason"]
    candidates = [Path("C:/Windows/Fonts/arial.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/Library/Fonts/Arial.ttf")]
    font = next((p for p in candidates if p.is_file()), None)
    if font is None:
        pytest.skip("no font file on this computer to upload")
    asset = _asset(client, pid, font)
    listed = {a["id"]: a for a in client.get(f"/api/studio/projects/{pid}").json()["assets"]}
    assert listed[asset]["kind"] == "font" and listed[asset]["family"]
    base = _asset(client, pid, make_clip(tmp_path / "g.mp4", "black", 1, audio=False))
    text = {"id": "t", "text": "HELLO", "x": 0.5, "y": 0.5, "size": 14, "font": listed[asset]["family"]}
    assert _put(client, pid, [scene("s", visuals=[vis("v", base)], texts=[text])]).status_code == 200
    frame = _frame(_preview(client, pid, "s", tmp_path), 0.5, tmp_path)
    assert sum(1 for x in range(100, 540, 6) for y in range(120, 240, 6) if min(frame.getpixel((x, y))) > 200) > 15
    # a font can't be used as a clip
    assert _put(client, pid, [scene("s", visuals=[vis("v", asset)])]).status_code == 200
    assert _render(client, pid, kind="preview", scene_id="s").status_code == 422


def test_the_plan_decides_which_tools_a_document_may_use():
    asset = "1" * 16
    standard, pro = features.resolve("standard"), features.resolve("pro")
    uses = {
        "overlays": Scene(id="a", overlays=[Overlay(id="o", asset_id=asset)]),
        "highlight": Scene(id="b", shapes=[Shape(id="s")]),
        "opening": Scene(id="c", open_effect="letterbox"),
        "grid": Scene(id="d", grid=Grid()),
        "credits": Scene(id="e", credits=Credits(lines=["x"])),
        "montage": Scene(id="f", fit_to_voiceover=True),
    }
    for name, sc in uses.items():
        assert engine.check_doc_allowed(StudioDoc(scenes=[sc]), standard), name
        assert engine.check_doc_allowed(StudioDoc(scenes=[sc]), pro) == [], name
    with pytest.raises(ValidationError):
        Overlay(id="o", asset_id=asset, start=3, end=2)
    with pytest.raises(ValidationError):
        Shape(id="s", color="yellow")
    off = dict(pro, studio_overlays=False)  # switched off for one account
    assert engine.check_doc_allowed(StudioDoc(scenes=[uses["grid"], uses["overlays"]]), off)[0].startswith("Pictures over a scene")


def test_removing_a_file_also_removes_it_from_overlays_and_grid_cells():
    a, b = "a" * 16, "b" * 16
    doc = StudioDoc(scenes=[Scene(id="s", overlays=[{"id": "o", "asset_id": a}, {"id": "p", "asset_id": b}],
                                  grid={"cells": [{"id": "c1", "asset_id": a}, {"id": "c2", "asset_id": b}]})])
    assert doc.asset_ids() == {a, b}
    cleaned = doc.without_assets({a})
    assert [o.asset_id for o in cleaned.scenes[0].overlays] == [b] and [c.asset_id for c in cleaned.scenes[0].grid.cells] == [b]


def test_an_account_without_the_tool_is_told_so_when_saving(ac: TestClient):
    token = _join(ac, "tools@example.com")
    h = _h(token)
    admin.main(["set-feature", "tools@example.com", "studio", "on"])  # studio alone, on the standard plan
    pid = _new(ac, h)
    r = _put(ac, pid, [scene("s", credits={"lines": ["x"]})], h)
    assert r.status_code == 403 and "credits" in r.json()["detail"].lower()
    font = _upload(ac, pid, b"x", "f.ttf", h)
    assert "plan" in font.json()["rejected"][0]["reason"]
    admin.main(["set-feature", "tools@example.com", "studio_credits", "on"])
    assert _put(ac, pid, [scene("s", credits={"lines": ["x"]})], h).status_code == 200


def test_the_quick_preview_of_the_whole_project_is_small_and_has_every_scene(client: TestClient, tmp_path: Path):
    pid = _new(client)
    red = _asset(client, pid, make_clip(tmp_path / "r.mp4", "red", 1.5, audio=False))
    blue = _asset(client, pid, make_clip(tmp_path / "b.mp4", "blue", 1.5, audio=False))
    song = _asset(client, pid, make_tone(tmp_path / "song.wav", 2.0))
    scenes = [scene("a", visuals=[vis("1", red)]), scene("b", visuals=[vis("2", blue)], transition_in="crossfade", crossfade_s=0.5)]
    assert _put(client, pid, scenes, bed_music={"asset_id": song}).status_code == 200
    assert _render(client, pid, kind="preview").status_code == 202  # no scene given: everything
    done = _wait(client, pid)
    assert done["status"] == "completed", done["error"]
    assert done["preview"] == {"scene": None} and done["has_output"] is False
    video = _out_path(client, pid, "preview", tmp_path)  # no ?scene=
    assert _frame(video, 0.5, tmp_path).size == (640, 360) and _streams(video) == {"video", "audio"}
    assert _near(_frame(video, 0.5, tmp_path).getpixel((320, 180)), (255, 0, 0)) and _near(_frame(video, 2.3, tmp_path).getpixel((320, 180)), (0, 0, 255))
