"""Photos (in order) + optional music + optional text -> one MP4, with FFmpeg.

Steps: fit every photo onto a frame (Pillow) -> one short clip per photo with a slow zoom (FFmpeg, a few
in parallel) -> join the clips, draw the texts, lay the music under it, encode once more.
All paths are ones we made; the user's text only ever reaches FFmpeg inside an ASS file, never a command line.
"""

from __future__ import annotations

import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from ..config import get_settings
from ..editing import captions as cap
from ..editing.overlays import TextOverlay
from ..services import media
from . import images, store
from .schemas import FPS, MAX_TOTAL_SECONDS, SIZES, SlideshowSettings

log = logging.getLogger(__name__)

ZOOM_AMOUNT = 0.08  # photos grow (or shrink) by 8 % over their time on screen
FADE_S = 0.15
MIN_PER_PHOTO, MAX_PER_PHOTO = 0.6, 10.0  # range allowed when the time per photo is fitted to the music


class SlideshowError(Exception):
    """A message that is safe to show to the user."""


def seconds_per_photo(settings: SlideshowSettings, n_photos: int, music_duration: float | None) -> float:
    """Time each photo is shown, rounded to a whole number of frames.

    A clip can only last a whole number of frames; if we planned with 0.857 s but each clip really lasted
    0.867 s, hundreds of photos would drift seconds off the planned timeline (texts, music fade-out)."""
    if settings.fit_music and music_duration and n_photos:
        per = min(max(music_duration / n_photos, MIN_PER_PHOTO), MAX_PER_PHOTO)
    else:
        per = settings.seconds_per_photo
    return round(max(1, round(per * FPS)) / FPS, 5)


def clip_filter(index: int, width: int, height: int, per: float, zoom: bool, fade: bool) -> str:
    """Video filter for one photo's clip: slow push-in (even) / pull-out (odd), quick dip at both ends."""
    parts: list[str] = []
    if zoom:
        progress = f"(t/{per:.3f})" if index % 2 == 0 else f"(1-t/{per:.3f})"
        scaled_w = f"trunc((iw*(1+{ZOOM_AMOUNT}*{progress}))/2)*2"  # grows a little each frame...
        scaled_h = f"trunc((ih*(1+{ZOOM_AMOUNT}*{progress}))/2)*2"
        parts.append(f"scale=w='{scaled_w}':h='{scaled_h}':eval=frame:flags=bicubic,crop={width}:{height}")  # ...then is cropped back
    if fade and per >= 0.7:
        parts.append(f"fade=t=in:st=0:d={FADE_S},fade=t=out:st={per - FADE_S:.3f}:d={FADE_S}")
    parts.append("format=yuv420p")
    return ",".join(parts)


def _render_clip(canvas: Path, out: Path, index: int, width: int, height: int, per: float, zoom: bool, fade: bool) -> None:
    cmd = [
        get_settings().ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-framerate", str(FPS), "-t", f"{per:.3f}", "-i", str(canvas),
        "-vf", clip_filter(index, width, height, per, zoom, fade),
        "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
        "-threads", "2", "-an", str(out),
    ]
    proc = media.run_tool(cmd, timeout=10 * 60)
    if proc.returncode != 0 or not out.is_file():
        log.error("clip %d failed: %s", index, proc.stderr.strip()[:300])
        raise SlideshowError("One of the photos could not be turned into video.")


def _music_filter(volume: float, total: float, fade_out: float) -> str:
    fade = min(fade_out, total / 2)
    chain = f"aresample=48000,aformat=channel_layouts=stereo,volume={volume:.3f},atrim=0:{total:.3f},asetpts=PTS-STARTPTS"
    if fade > 0.05:
        chain += f",afade=t=out:st={max(total - fade, 0):.3f}:d={fade:.3f}"
    return f"[1:a]{chain}[aout]"


def build_final_command(
    work: Path, out: Path, total: float, music: Path | None, settings: SlideshowSettings, has_texts: bool
) -> list[str]:
    cmd = [
        get_settings().ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1",
        "-f", "concat", "-safe", "0", "-i", "list.txt",
    ]
    if music is not None:
        cmd += ["-stream_loop", "-1", "-i", str(music), "-filter_complex", _music_filter(settings.music_volume, total, settings.music_fade_out_s)]
        audio_map = "[aout]"
    else:  # a silent track keeps players and upload sites happy
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        audio_map = "1:a"
    if has_texts:
        cmd += ["-vf", "ass=texts.ass"]
    cmd += [
        "-map", "0:v", "-map", audio_map,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", f"{total:.3f}", "-movflags", "+faststart", str(out),
    ]
    return cmd


def render(project_id: str, on_progress: Callable[[int], None] | None = None) -> dict[str, Any]:
    """Render the project's video. Returns the output's ffprobe info. Raises SlideshowError."""
    project = store.get(project_id)
    if project is None:
        raise SlideshowError("This project no longer exists.")
    settings = SlideshowSettings.model_validate(project["settings_json"])
    photo_rows = store.photos(project_id)
    if not photo_rows:
        raise SlideshowError("Add at least one photo first.")

    base = store.project_dir(project_id)
    width, height = SIZES[settings.size]
    music = base / project["music_file"] if project.get("music_file") else None
    if music is not None and not music.is_file():
        music = None
    per = seconds_per_photo(settings, len(photo_rows), project.get("music_duration"))
    total = round(per * len(photo_rows), 3)
    if total > MAX_TOTAL_SECONDS:
        raise SlideshowError(
            f"That would be a {total / 60:.0f}-minute video (the limit is {MAX_TOTAL_SECONDS // 60}). "
            "Use fewer photos or fewer seconds per photo."
        )

    work = base / "work"
    shutil.rmtree(work, ignore_errors=True)
    (work / "canvas").mkdir(parents=True)
    (work / "clips").mkdir()

    def progress(pct: int) -> None:
        if on_progress:
            on_progress(min(max(pct, 0), 99))

    workers = max(1, min(8, (os.cpu_count() or 2) // 2))
    n = len(photo_rows)
    progress(3)

    # 1) every photo onto a frame of the right shape
    def make(i_row: tuple[int, dict[str, Any]]) -> None:
        i, row = i_row
        images.make_canvas(base / "photos" / f"{row['id']}.jpg", work / "canvas" / f"{i:05d}.jpg", width, height, settings.fill)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, _ in enumerate(pool.map(make, enumerate(photo_rows)), 1):
            progress(3 + int(17 * done / n))

    # 2) one clip per photo
    def clip(i: int) -> None:
        _render_clip(work / "canvas" / f"{i:05d}.jpg", work / "clips" / f"{i:05d}.mp4", i, width, height, per,
                     settings.zoom, settings.fade)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, _ in enumerate(pool.map(clip, range(n)), 1):
            progress(20 + int(55 * done / n))

    # 3) join, texts, music, final encode
    (work / "list.txt").write_text("".join(f"file 'clips/{i:05d}.mp4'\n" for i in range(n)), encoding="utf-8")
    texts: list[TextOverlay] = list(settings.texts)
    if texts:
        (work / "texts.ass").write_text(cap.render_ass([], width, height, total=total, texts=texts), encoding="utf-8")

    partial = base / "output.partial.mp4"
    final = base / "output.mp4"
    partial.unlink(missing_ok=True)
    cmd = build_final_command(work, partial, total, music, settings, bool(texts))

    def on_encode(frac: float) -> None:
        progress(75 + int(24 * frac))

    try:
        media.run_ffmpeg_with_progress(cmd, work, total, on_encode)
        info = _verify(partial, total, width, height)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)  # the big intermediate clips are no longer needed
    partial.replace(final)
    return {**info.to_dict(), "path": str(final)}


def _verify(path: Path, expected: float, width: int, height: int) -> media.MediaInfo:
    if not path.is_file() or path.stat().st_size < 5_000:
        raise media.MediaError("The finished video is missing or empty.")
    info = media.probe(path)
    if (info.width, info.height) != (width, height):
        raise media.MediaError("The finished video has the wrong size.")
    if abs(info.duration - expected) > max(1.0, expected * 0.03):
        raise media.MediaError("The finished video has an unexpected length.")
    return info
