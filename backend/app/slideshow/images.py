"""Reading uploaded photos safely and making the three sizes photo mode needs.

Every upload is decoded with Pillow and re-saved as a fresh JPEG under a server-made name: whatever the
file claimed to be, only a plain picture is kept (no metadata, no odd payloads), phone rotation (EXIF)
is applied, and absurdly large images are refused before they eat memory.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError

try:  # iPhone photos (HEIC/HEIF)
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - optional
    pass

log = logging.getLogger(__name__)

MAX_PIXELS = 120_000_000  # ~ a 11000 x 11000 picture; bigger is refused as a "decompression bomb"
KEEP_LONG_SIDE = 2560  # plenty for a 1080p / vertical-1080 video, and keeps 400 photos manageable
PREVIEW_LONG_SIDE = 960
THUMB_HEIGHT = 160
EXIF_DATETIME_ORIGINAL = 36867
EXIF_IFD = 0x8769


class PhotoError(ValueError):
    """User-safe reason a photo was not accepted."""


def ingest(fileobj: BinaryIO, project_dir: Path, photo_id: str) -> tuple[int, int, str | None]:
    """Decode an uploaded photo and write photos/, previews/ and thumbs/ files. Returns (w, h, taken_at)."""
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(fileobj) as im:
            im.draft("RGB", (KEEP_LONG_SIDE * 2, KEEP_LONG_SIDE * 2))  # decode huge JPEGs at a reduced size
            taken = None
            try:
                exif = im.getexif()
                raw = exif.get_ifd(EXIF_IFD).get(EXIF_DATETIME_ORIGINAL) or exif.get(306)
                taken = str(raw).replace(":", "-", 2) if raw else None  # "2024:05:01 10:00:00" -> sortable text
            except Exception:  # broken EXIF is not a reason to refuse the picture
                taken = None
            im = ImageOps.exif_transpose(im)
            im = im.convert("RGB")
    except Image.DecompressionBombError as exc:
        raise PhotoError("That picture is too large (millions of pixels over the limit).") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise PhotoError("That file isn't a picture I can read (use JPG, PNG, WebP or HEIC).") from exc

    im.thumbnail((KEEP_LONG_SIDE, KEEP_LONG_SIDE), Image.Resampling.LANCZOS)
    width, height = im.size
    if width < 16 or height < 16:
        raise PhotoError("That picture is too small to use.")
    im.save(project_dir / "photos" / f"{photo_id}.jpg", "JPEG", quality=90, optimize=True)

    preview = im.copy()
    preview.thumbnail((PREVIEW_LONG_SIDE, PREVIEW_LONG_SIDE), Image.Resampling.LANCZOS)
    preview.save(project_dir / "previews" / f"{photo_id}.jpg", "JPEG", quality=82)

    thumb = im.copy()
    thumb.thumbnail((THUMB_HEIGHT * 3, THUMB_HEIGHT), Image.Resampling.LANCZOS)
    thumb.save(project_dir / "thumbs" / f"{photo_id}.jpg", "JPEG", quality=80)
    return width, height, taken


def make_canvas(src: Path, dst: Path, width: int, height: int, fill: str) -> None:
    """One photo -> a frame exactly width x height.

    fill="blur": the whole photo, on a blurred, darkened copy of itself (no black bars)
    fill="crop": cut the photo to the frame's shape   fill="black": the whole photo on black
    """
    with Image.open(src) as im:
        im = im.convert("RGB")
        iw, ih = im.size
        if fill == "crop" or abs(iw / ih - width / height) < 0.03:  # already (nearly) the right shape
            out = ImageOps.fit(im, (width, height), method=Image.Resampling.LANCZOS)
        else:
            if fill == "black":
                out = Image.new("RGB", (width, height), (0, 0, 0))
            else:
                small = ImageOps.fit(im, (max(width // 8, 8), max(height // 8, 8)), method=Image.Resampling.BILINEAR)
                small = small.filter(ImageFilter.GaussianBlur(5))
                out = ImageEnhance.Brightness(small.resize((width, height), Image.Resampling.BICUBIC)).enhance(0.55)
            fg = ImageOps.contain(im, (width, height), method=Image.Resampling.LANCZOS)
            out.paste(fg, ((width - fg.width) // 2, (height - fg.height) // 2))
        out.save(dst, "JPEG", quality=93)
