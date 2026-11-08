"""Photo mode (photos + music + text -> video). Uses the real FFmpeg and real image decoding."""

from __future__ import annotations

import io
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import auth, db
from app.config import get_settings
from app.slideshow import engine, images, store
from app.slideshow.schemas import SlideshowSettings

RED, GREEN, BLUE = (230, 20, 20), (20, 200, 20), (20, 20, 230)


def _jpeg(color=RED, size=(600, 900), orientation: int | None = None, fmt="JPEG") -> bytes:
    im = Image.new("RGB", size, color)
    buf = io.BytesIO()
    kwargs = {}
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        kwargs["exif"] = exif
    im.save(buf, fmt, **kwargs)
    return buf.getvalue()


@pytest.fixture
def tone(tmp_path: Path) -> Path:
    path = tmp_path / "song.wav"
    subprocess.run([get_settings().ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100",
                    "-t", "4", str(path)], check=True)
    return path


def _new(c: TestClient, headers: dict | None = None) -> str:
    r = c.post("/api/slideshows", headers=headers or {})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add(c: TestClient, pid: str, photos: list[tuple[str, bytes]], headers: dict | None = None):
    return c.post(f"/api/slideshows/{pid}/photos", files=[("files", (n, b, "image/jpeg")) for n, b in photos], headers=headers or {})


def _wait(c: TestClient, pid: str, headers: dict | None = None, timeout: float = 90) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        p = c.get(f"/api/slideshows/{pid}", headers=headers or {}).json()
        if p["status"] in ("completed", "failed"):
            return p
        time.sleep(0.3)
    raise AssertionError("render did not finish")


def _frame(video: Path, t: float, tmp: Path) -> Image.Image:
    out = tmp / f"f{t}.png"
    subprocess.run([get_settings().ffmpeg, "-y", "-loglevel", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1", str(out)], check=True)
    return Image.open(out).convert("RGB")


def _near(pixel, color, tol=40) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(pixel, color))


# ---------- images ----------

def test_ingest_applies_phone_rotation_and_makes_three_sizes(tmp_path: Path):
    for sub in ("photos", "previews", "thumbs"):
        (tmp_path / sub).mkdir()
    # a landscape picture marked "rotate 90 degrees" (what a phone does for a portrait shot)
    w, h, taken = images.ingest(io.BytesIO(_jpeg(size=(400, 200), orientation=6)), tmp_path, "aaaa")
    assert (w, h) == (200, 400)
    assert Image.open(tmp_path / "photos" / "aaaa.jpg").size == (200, 400)
    assert max(Image.open(tmp_path / "previews" / "aaaa.jpg").size) <= images.PREVIEW_LONG_SIDE
    assert Image.open(tmp_path / "thumbs" / "aaaa.jpg").size[1] <= images.THUMB_HEIGHT
    assert taken is None
    big = images.ingest(io.BytesIO(_jpeg(size=(4000, 3000))), tmp_path, "bbbb")
    assert max(big[:2]) == images.KEEP_LONG_SIDE  # shrunk to a manageable size


def test_ingest_accepts_png_and_rejects_non_pictures(tmp_path: Path):
    for sub in ("photos", "previews", "thumbs"):
        (tmp_path / sub).mkdir()
    assert images.ingest(io.BytesIO(_jpeg(fmt="PNG")), tmp_path, "cccc")[:2] == (600, 900)
    for bad in (b"not an image at all", b"", b"\x89PNG\r\n\x1a\n" + b"junk"):
        with pytest.raises(images.PhotoError):
            images.ingest(io.BytesIO(bad), tmp_path, "dddd")
    with pytest.raises(images.PhotoError):
        images.ingest(io.BytesIO(_jpeg(size=(8, 8))), tmp_path, "eeee")  # too small
    assert not (tmp_path / "photos" / "dddd.jpg").exists()  # nothing half-written for a refused file


def test_canvas_fills_the_frame_in_every_mode(tmp_path: Path):
    src = tmp_path / "wide.jpg"
    Image.new("RGB", (900, 300), RED).save(src)
    for fill in ("blur", "crop", "black"):
        out = tmp_path / f"{fill}.jpg"
        images.make_canvas(src, out, 540, 960, fill)
        assert Image.open(out).size == (540, 960)
    blur, black, crop = (Image.open(tmp_path / f"{f}.jpg").convert("RGB") for f in ("blur", "black", "crop"))
    assert _near(black.getpixel((270, 20)), (0, 0, 0), 12)  # bars are black
    assert blur.getpixel((270, 20))[0] > 60  # ...or a dimmed copy of the picture, not black
    assert _near(crop.getpixel((270, 20)), RED, 25) and _near(blur.getpixel((270, 480)), RED, 25)  # photo itself is intact


# ---------- timing ----------

def test_time_per_photo_follows_the_music_when_asked():
    s = SlideshowSettings(seconds_per_photo=3, fit_music=True)
    assert engine.seconds_per_photo(s, 4, 20.0) == 5.0
    assert engine.seconds_per_photo(s, 100, 20.0) == engine.MIN_PER_PHOTO  # never frantic
    assert engine.seconds_per_photo(s, 1, 120.0) == engine.MAX_PER_PHOTO  # never a slideshow of one frozen frame
    assert engine.seconds_per_photo(s, 4, None) == 3  # no music: the fixed time
    assert engine.seconds_per_photo(SlideshowSettings(seconds_per_photo=2, fit_music=False), 4, 20.0) == 2


def test_time_per_photo_is_a_whole_number_of_frames_so_long_slideshows_do_not_drift():
    s = SlideshowSettings(seconds_per_photo=0.857)  # 25.7 frames: would really last 26
    per = engine.seconds_per_photo(s, 400, None)
    assert per == pytest.approx(26 / 30, abs=1e-4)
    assert round(per * 30) == per * 30 or abs(per * 30 - round(per * 30)) < 1e-3
    fitted = engine.seconds_per_photo(SlideshowSettings(fit_music=True), 14, 12.0)
    assert abs(fitted * 30 - round(fitted * 30)) < 1e-3  # 12 s / 14 = 0.857 -> 26 frames


def test_clip_filter_alternates_zoom_and_skips_fade_for_very_short_photos():
    a, b = engine.clip_filter(0, 1080, 1920, 2.0, True, True), engine.clip_filter(1, 1080, 1920, 2.0, True, True)
    assert "(t/2.000)" in a and "(1-t/2.000)" in b and "crop=1080:1920" in a and "fade=t=in" in a
    assert "fade" not in engine.clip_filter(0, 1080, 1920, 0.5, True, True)
    assert engine.clip_filter(0, 1080, 1920, 2.0, False, False) == "format=yuv420p"


# ---------- API + real renders ----------

def test_full_flow_photos_in_order_with_music_and_text(client: TestClient, tmp_path: Path, tone: Path):
    pid = _new(client)
    r = _add(client, pid, [("1.jpg", _jpeg(RED)), ("2.jpg", _jpeg(GREEN, (900, 600))), ("3.jpg", _jpeg(BLUE, (700, 700))),
                           ("broken.jpg", b"nope")])
    body = r.json()
    assert r.status_code == 200 and len(body["added"]) == 3 and body["photo_count"] == 3
    assert body["rejected"] == [{"name": "broken.jpg", "reason": "That file isn't a picture I can read (use JPG, PNG, WebP or HEIC)."}]

    photos = client.get(f"/api/slideshows/{pid}").json()["photos"]
    red, green, blue = (p["id"] for p in photos)
    # new order: blue, red, green  (and "green" listed twice + an unknown id are harmless)
    order = client.put(f"/api/slideshows/{pid}/order", json={"order": [blue, red, green, green, "f" * 16]})
    assert [p["id"] for p in order.json()["photos"]] == [blue, red, green]

    with tone.open("rb") as f:
        m = client.post(f"/api/slideshows/{pid}/music", files={"file": ("my song.wav", f, "audio/wav")})
    assert m.status_code == 200 and m.json()["music"] == {"name": "my song.wav", "duration": 4.0}

    settings = {"size": "vertical", "seconds_per_photo": 1.0, "zoom": True, "fade": True, "fill": "blur", "music_volume": 0.8,
                "music_fade_out_s": 1.0,
                "texts": [{"id": "t1", "text": "SALE", "x": 0.5, "y": 0.5, "size": 20, "color": "#ffffff", "style": "plain",
                           "start": 0, "end": 3, "fade": False}]}
    assert client.put(f"/api/slideshows/{pid}/settings", json=settings).status_code == 200
    assert client.post(f"/api/slideshows/{pid}/render").status_code == 202
    done = _wait(client, pid)
    assert done["status"] == "completed", done
    assert done["output"]["width"] == 1080 and done["output"]["height"] == 1920 and abs(done["output"]["duration"] - 3.0) < 0.2

    video = tmp_path / "out.mp4"
    video.write_bytes(client.get(f"/api/slideshows/{pid}/video").content)
    probe = subprocess.run([get_settings().ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(video)],
                           capture_output=True, text=True).stdout.split()
    assert "video" in probe and "audio" in probe  # the music is in there

    # the photos appear in the order we set: blue, then red, then green (look at the middle of each second)
    f0, f1, f2 = (_frame(video, t, tmp_path) for t in (0.5, 1.5, 2.5))
    # (the pixel can sit on the dimmed blurred bar around a photo that isn't the frame's shape: darker, same hue)
    hue = lambda im: max(range(3), key=im.getpixel((100, 300)).__getitem__)  # 0 = red, 1 = green, 2 = blue
    strong = lambda im: sorted(im.getpixel((100, 300)))[-1] - sorted(im.getpixel((100, 300)))[-2] > 40
    assert (hue(f0), hue(f1), hue(f2)) == (2, 0, 1) and strong(f0) and strong(f1) and strong(f2)
    # the text is drawn over the middle: plenty of near-white pixels there, and fewer in a copy without it
    white = lambda im: sum(1 for x in range(380, 700, 6) for y in range(850, 1070, 6) if min(im.getpixel((x, y))) > 225)
    assert white(f0) > 40

    assert client.get(f"/api/slideshows/{pid}/download").headers["content-disposition"].startswith("attachment")
    assert client.get(f"/api/slideshows/{pid}/music/file").status_code == 200
    assert client.get(f"/api/slideshows/{pid}/photos/{blue}/thumb").headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/slideshows/{pid}/photos/{blue}/preview").status_code == 200


def test_without_text_nothing_is_drawn_and_without_music_the_video_is_silent_but_valid(client: TestClient, tmp_path: Path):
    pid = _new(client)
    _add(client, pid, [("a.jpg", _jpeg((10, 10, 10)))])
    client.put(f"/api/slideshows/{pid}/settings", json={"seconds_per_photo": 1.0, "fade": False, "zoom": False, "size": "square"})
    client.post(f"/api/slideshows/{pid}/render")
    done = _wait(client, pid)
    assert done["status"] == "completed" and (done["output"]["width"], done["output"]["height"]) == (1080, 1080)
    video = tmp_path / "o.mp4"
    video.write_bytes(client.get(f"/api/slideshows/{pid}/video").content)
    white = lambda im: sum(1 for x in range(0, 1080, 20) for y in range(0, 1080, 20) if min(im.getpixel((x, y))) > 200)
    assert white(_frame(video, 0.5, tmp_path)) == 0
    assert "audio" in subprocess.run([get_settings().ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(video)],
                                     capture_output=True, text=True).stdout


def test_fit_music_makes_the_video_as_long_as_the_song(client: TestClient, tone: Path):
    pid = _new(client)
    _add(client, pid, [(f"{i}.jpg", _jpeg(RED)) for i in range(3)])
    with tone.open("rb") as f:
        client.post(f"/api/slideshows/{pid}/music", files={"file": ("s.wav", f, "audio/wav")})
    client.put(f"/api/slideshows/{pid}/settings", json={"fit_music": True, "seconds_per_photo": 9, "zoom": False})
    client.post(f"/api/slideshows/{pid}/render")
    done = _wait(client, pid)
    assert done["status"] == "completed" and abs(done["output"]["duration"] - 4.0) < 0.2  # 3 photos over a 4 s song


def test_validation_and_state_rules(client: TestClient, tone: Path, monkeypatch: pytest.MonkeyPatch):
    pid = _new(client)
    assert client.post(f"/api/slideshows/{pid}/render").status_code == 422  # no photos yet
    for bad in ({"seconds_per_photo": 0.1}, {"size": "huge"}, {"music_volume": 3}, {"texts": [{"id": "a", "text": "x", "color": "red"}]},
                {"texts": [{"id": f"t{i}", "text": "x"} for i in range(31)]}):
        assert client.put(f"/api/slideshows/{pid}/settings", json=bad).status_code == 422, bad

    monkeypatch.setattr("app.slideshow.api.MAX_PHOTOS", 2)
    r = _add(client, pid, [(f"{i}.jpg", _jpeg()) for i in range(4)]).json()
    assert len(r["added"]) == 2 and len(r["rejected"]) == 2 and "at most 2" in r["rejected"][0]["reason"]
    assert _add(client, pid, [("big.jpg", b"x" * 10)]).json()["rejected"]  # unreadable -> listed, not fatal

    assert client.post(f"/api/slideshows/{pid}/music", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 415
    assert client.post(f"/api/slideshows/{pid}/music", files={"file": ("silence.mp3", b"not audio", "audio/mpeg")}).status_code == 422
    assert not list(store.project_dir(pid).glob("music.*"))  # the refused file was not kept

    store.update(pid, status="rendering")  # pretend it's busy
    for call in (lambda: _add(client, pid, [("z.jpg", _jpeg())]), lambda: client.delete(f"/api/slideshows/{pid}"),
                 lambda: client.put(f"/api/slideshows/{pid}/settings", json={}), lambda: client.post(f"/api/slideshows/{pid}/render")):
        assert call().status_code == 409
    store.update(pid, status="draft")
    assert client.delete(f"/api/slideshows/{pid}").status_code == 204
    assert client.get(f"/api/slideshows/{pid}").status_code == 404
    assert not store.project_dir(pid).exists()


def test_order_endpoint_deletes_left_out_photos_and_their_files(client: TestClient):
    pid = _new(client)
    _add(client, pid, [(f"{i}.jpg", _jpeg()) for i in range(3)])
    ids = [p["id"] for p in client.get(f"/api/slideshows/{pid}").json()["photos"]]
    kept = client.put(f"/api/slideshows/{pid}/order", json={"order": [ids[2], ids[0]]}).json()["photos"]
    assert [p["id"] for p in kept] == [ids[2], ids[0]]
    base = store.project_dir(pid)
    assert not (base / "photos" / f"{ids[1]}.jpg").exists() and not (base / "thumbs" / f"{ids[1]}.jpg").exists()
    assert (base / "photos" / f"{ids[0]}.jpg").exists()


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
def test_browser_preflight_allows_every_method_photo_mode_uses(client: TestClient, method: str):
    """A browser asks first ("may I PUT?"). Without this the page can't save settings or reorder photos
    (the TestClient doesn't enforce CORS, so only a test like this catches it)."""
    r = client.options("/api/slideshows/" + "0" * 32 + "/settings", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": "content-type,authorization"})
    assert r.status_code == 200 and method in r.headers["access-control-allow-methods"]
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_bad_ids_and_listing(client: TestClient):
    assert client.get("/api/slideshows/not-an-id").status_code == 422
    assert client.get(f"/api/slideshows/{'0' * 32}").status_code == 404
    pid = _new(client)
    assert [p["id"] for p in client.get("/api/slideshows").json()["projects"]] == [pid]
    assert client.get(f"/api/slideshows/{pid}/photos/{'0' * 16}/thumb").status_code == 404
    assert client.get(f"/api/slideshows/{pid}/photos/{'0' * 16}/huge").status_code == 422


def test_old_projects_are_purged_and_interrupted_renders_requeued(client: TestClient):
    pid = _new(client)
    store.update(pid, status="rendering")
    assert store.requeue_interrupted() == 1 and store.get(pid)["status"] == "queued"
    store.update(pid, status="draft")
    with db.connect() as conn:
        conn.execute("UPDATE slideshows SET updated_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (pid,))
    assert store.purge_old(7) == 1 and store.get(pid) is None and not store.project_dir(pid).exists()
    busy = _new(client)
    store.update(busy, status="rendering")
    with db.connect() as conn:
        conn.execute("UPDATE slideshows SET updated_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (busy,))
    assert store.purge_old(7) == 0  # never delete something that is being rendered


# ---------- accounts on: login, ownership, quota, upload gate ----------

@pytest.fixture
def ac(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("DAILY_VIDEO_LIMIT", "1")
    auth.reset_throttle()
    return request.getfixturevalue("client")


def _join(c: TestClient, email: str) -> dict:
    r = c.post("/api/auth/signup", json={"invite_code": auth.new_invite(), "email": email, "password": "correct horse battery"})
    assert r.status_code == 201, r.text
    return r.json()


def test_photo_mode_needs_a_login_and_is_private(ac: TestClient):
    assert ac.post("/api/slideshows").status_code == 401 and ac.get("/api/slideshows").status_code == 401
    a, b = _join(ac, "a@example.com"), _join(ac, "b@example.com")
    ha, hb = {"Authorization": f"Bearer {a['token']}"}, {"Authorization": f"Bearer {b['token']}"}
    pid = _new(ac, ha)
    photo = _add(ac, pid, [("a.jpg", _jpeg())], ha).json()["added"][0]["id"]

    assert ac.get(f"/api/slideshows/{pid}", headers=hb).status_code == 404  # looks like it doesn't exist
    assert _add(ac, pid, [("x.jpg", _jpeg())], hb).status_code == 404
    assert ac.put(f"/api/slideshows/{pid}/order", json={"order": []}, headers=hb).status_code == 404
    assert ac.delete(f"/api/slideshows/{pid}", headers=hb).status_code == 404
    assert ac.get("/api/slideshows", headers=hb).json()["projects"] == []

    thumb = f"/api/slideshows/{pid}/photos/{photo}/thumb"
    assert ac.get(thumb).status_code == 401
    assert ac.get(f"{thumb}?st={a['media_token']}").status_code == 200
    assert ac.get(f"{thumb}?st={b['media_token']}").status_code == 404
    assert ac.get(f"/api/slideshows/{pid}?st={a['media_token']}").status_code == 401  # a media token is not a login


def test_render_uses_the_daily_video_quota_and_uploads_are_gated(ac: TestClient):
    a = _join(ac, "a@example.com")
    ha = {"Authorization": f"Bearer {a['token']}"}
    pid = _new(ac, ha)
    _add(ac, pid, [("a.jpg", _jpeg())], ha)
    ac.put(f"/api/slideshows/{pid}/settings", json={"seconds_per_photo": 1.0, "zoom": False}, headers=ha)
    assert ac.post(f"/api/slideshows/{pid}/render", headers=ha).status_code == 202
    assert _wait(ac, pid, ha)["status"] == "completed"
    again = ac.post(f"/api/slideshows/{pid}/render", headers=ha)
    assert again.status_code == 429 and "1 video" in again.json()["detail"]
    assert ac.get("/api/auth/me", headers=ha).json()["user"]["quota"]["videos"]["used"] == 1

    # photos are refused on the headers alone: no login, or a declared size over the cap
    big = {"content-type": "multipart/form-data; boundary=x", "content-length": "900000000"}
    assert ac.post(f"/api/slideshows/{pid}/photos", content=b"x", headers=big).status_code == 401
    assert ac.post(f"/api/slideshows/{pid}/photos", content=b"x", headers={**big, **ha}).status_code == 413
    assert ac.post(f"/api/slideshows/{pid}/music", content=b"x", headers={**big, **ha}).status_code == 413


def test_project_cap_per_user(ac: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.slideshow.api.MAX_PROJECTS_PER_USER", 2)
    ha = {"Authorization": f"Bearer {_join(ac, 'a@example.com')['token']}"}
    _new(ac, ha)
    _new(ac, ha)
    third = ac.post("/api/slideshows", headers=ha)
    assert third.status_code == 409 and "Delete an old one" in third.json()["detail"]
