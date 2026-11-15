"""Reading uploaded clips, audio and pictures safely and making their thumbnails.

The user's file name is only ever kept as a label. Files are stored under a server-made name with an
extension from our own list, pictures are decoded and re-saved as plain JPEGs, and everything is probed
with ffprobe before it is accepted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import get_settings
from ..services import media
from .schemas import AUDIO_SUFFIXES, FONT_SUFFIXES, IMAGE_SUFFIXES, MAX_ASSET_SECONDS, VIDEO_SUFFIXES

try:  # iPhone photos (HEIC/HEIF)
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - optional
    pass

log = logging.getLogger(__name__)

MAX_PIXELS = 120_000_000
KEEP_LONG_SIDE = 2560
THUMB_HEIGHT = 160


class AssetError(ValueError):
    """User-safe reason a file was not accepted."""


@dataclass
class Ingested:
    kind: str  # video | audio | image | font
    file: str  # name inside the project's assets/ folder
    width: int | None
    height: int | None
    duration: float | None
    has_audio: bool
    size_bytes: int


def kind_of(name: str) -> str | None:
    suffix = Path(name).suffix.lower()
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in FONT_SUFFIXES:
        return "font"
    return None


def _copy_limited(src: BinaryIO, dest: Path, max_bytes: int) -> int:
    written = 0
    with dest.open("wb") as out:
        while chunk := src.read(1024 * 1024):
            written += len(chunk)
            if written > max_bytes:
                raise AssetError(f"That file is bigger than {max_bytes // (1024 * 1024)} MB.")
            out.write(chunk)
    return written


def _audio_info(path: Path) -> float:
    proc = media.run_tool(
        [get_settings().ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        timeout=60,
    )
    try:
        value = float(proc.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        raise AssetError("I can't find any audio in that file.") from None
    if value <= 0:
        raise AssetError("That audio file is empty.")
    return value


def _video_thumb(video: Path, dest: Path, duration: float) -> None:
    """One frame from near the start (not the very first: those are often black)."""
    at = min(1.0, max(duration / 2, 0.0))
    proc = media.run_tool(
        [get_settings().ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", str(video),
         "-frames:v", "1", "-vf", f"scale=-2:{THUMB_HEIGHT},format=yuvj420p", "-q:v", "4", str(dest)],
        timeout=60,
    )
    if proc.returncode != 0 or not dest.is_file():
        log.warning("studio thumbnail failed: %s", proc.stderr.strip()[:200])  # not fatal: the page shows a placeholder


def font_family(path: Path) -> str:
    """The family name inside a font file (what a text has to ask for to use it). Raises AssetError if it isn't a font."""
    try:
        from PIL import ImageFont

        family = ImageFont.truetype(str(path), 24).getname()[0]
    except Exception as exc:
        raise AssetError("That isn't a font file I can read (use .ttf or .otf).") from exc
    if not family or any(c in family for c in ",{}\\\n"):
        raise AssetError("That font's name has characters I can't use.")
    return family


def _ingest_image(fileobj: BinaryIO, assets_dir: Path, asset_id: str, thumb: Path) -> tuple[str, int, int]:
    """Decode and re-save a picture. Pictures with see-through parts stay PNG (logos, map highlights), the rest become JPEG."""
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(fileobj) as im:
            im.draft("RGB", (KEEP_LONG_SIDE * 2, KEEP_LONG_SIDE * 2))
            im = ImageOps.exif_transpose(im)
            has_alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
            im = im.convert("RGBA" if has_alpha else "RGB")
    except Image.DecompressionBombError as exc:
        raise AssetError("That picture is too large (millions of pixels over the limit).") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AssetError("That file isn't a picture I can read (use JPG, PNG, WebP or HEIC).") from exc
    im.thumbnail((KEEP_LONG_SIDE, KEEP_LONG_SIDE), Image.Resampling.LANCZOS)
    if im.width < 16 or im.height < 16:
        raise AssetError("That picture is too small to use.")
    name = f"{asset_id}.png" if has_alpha else f"{asset_id}.jpg"
    if has_alpha:
        im.save(assets_dir / name, "PNG", optimize=True)
    else:
        im.save(assets_dir / name, "JPEG", quality=92, optimize=True)
    small = im.copy()
    small.thumbnail((THUMB_HEIGHT * 3, THUMB_HEIGHT), Image.Resampling.LANCZOS)
    if has_alpha:  # a JPEG can't be see-through: show it on a grey board
        board = Image.new("RGB", small.size, (70, 70, 84))
        board.paste(small, mask=small.getchannel("A"))
        small = board
    small.convert("RGB").save(thumb, "JPEG", quality=80)
    return name, im.width, im.height


def ingest(fileobj: BinaryIO, name: str, project_dir: Path, asset_id: str, max_bytes: int) -> Ingested:
    """Check and store one uploaded file. Raises AssetError with a message fit to show. Nothing is left behind on failure."""
    kind = kind_of(name)
    if kind is None:
        raise AssetError("Use a video (MP4, MOV, MKV, WebM), an audio file (MP3, WAV, M4A, AAC, OGG, FLAC) or a picture (JPG, PNG, WebP, HEIC).")
    assets_dir, thumbs_dir = project_dir / "assets", project_dir / "thumbs"
    thumb = thumbs_dir / f"{asset_id}.jpg"
    suffix = ".jpg" if kind == "image" else Path(name).suffix.lower()
    dest = assets_dir / f"{asset_id}{suffix}"  # server-made name
    try:
        if kind == "image":
            fileobj.seek(0, 2)
            size = fileobj.tell()
            fileobj.seek(0)
            if size > max_bytes:
                raise AssetError(f"That file is bigger than {max_bytes // (1024 * 1024)} MB.")
            stored, width, height = _ingest_image(fileobj, assets_dir, asset_id, thumb)
            return Ingested("image", stored, width, height, None, False, (assets_dir / stored).stat().st_size)
        size = _copy_limited(fileobj, dest, max_bytes)
        if kind == "font":
            font_family(dest)
            return Ingested("font", dest.name, None, None, None, False, size)
        if kind == "audio":
            return Ingested("audio", dest.name, None, None, round(_audio_info(dest), 3), True, size)
        try:
            info = media.probe(dest)
        except media.MediaError as exc:
            raise AssetError(str(exc)) from exc
        if info.duration > MAX_ASSET_SECONDS:
            raise AssetError(f"That clip is longer than {MAX_ASSET_SECONDS // 60} minutes.")
        _video_thumb(dest, thumb, info.duration)
        return Ingested("video", dest.name, info.width, info.height, info.duration, info.has_audio, size)
    except BaseException:
        dest.unlink(missing_ok=True)
        (assets_dir / f"{asset_id}.png").unlink(missing_ok=True)
        thumb.unlink(missing_ok=True)
        raise
