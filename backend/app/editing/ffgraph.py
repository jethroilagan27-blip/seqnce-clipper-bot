"""Build the FFmpeg filtergraph for a plan. Pure functions: easy to unit-test.

Everything interpolated into the graph is a number we computed or a fixed
filename we chose; no AI/user text ever reaches the filtergraph.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .cuts import Cut

OUT_W, OUT_H = 1080, 1920
OUT_FPS = 30
CROSSFADE_S = 0.03  # tiny audio fade at each cut to avoid clicks
ASS_NAME = "captions.ass"  # referenced relative to ffmpeg's cwd (avoids Windows path escaping)


@dataclass
class CropBox:
    w: int
    h: int
    x: int
    y: int


def compute_crop(src_w: int, src_h: int, focus_x: float, size: tuple[int, int] = (OUT_W, OUT_H)) -> CropBox:
    """Largest window of the output's shape inside the source, centred on the speaker horizontally."""
    target = size[0] / size[1]
    if src_w / src_h >= target:
        h = src_h - src_h % 2
        w = int(h * target) - int(h * target) % 2
        w = min(w, src_w - src_w % 2)
        x = round(min(max(focus_x * src_w - w / 2, 0), src_w - w))
        return CropBox(w, h, x - x % 2, 0)
    w = src_w - src_w % 2
    h = int(w / target) - int(w / target) % 2
    h = min(h, src_h - src_h % 2)
    y = (src_h - h) // 2
    return CropBox(w, h, 0, y - y % 2)


def _whole_picture(trim: str, i: int, size: tuple[int, int]) -> str:
    """The full picture, fitted inside the output frame, over a dimmed and blurred copy of itself that fills the rest.
    (The background is blurred small and then enlarged: far cheaper than blurring at full size.)"""
    w, h = size
    small = f"{w // 4}:{h // 4}"
    return (
        f"{trim},split=2[wb{i}][wf{i}];"
        f"[wb{i}]scale={small}:force_original_aspect_ratio=increase,crop={small},boxblur=8:2,eq=brightness=-0.18,"
        f"scale={w}:{h}[bg{i}];"
        f"[wf{i}]scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos[fg{i}];"
        f"[bg{i}][fg{i}]overlay=(W-w)/2:(H-h)/2,setsar=1[v{i}]"
    )


def build_filtergraph(
    cuts: Sequence[Cut],
    crop: CropBox,
    *,
    captions: bool,
    music: bool,
    music_volume: float,
    total: float,
    crops: Sequence[CropBox] | None = None,
    has_audio: bool = True,
    size: tuple[int, int] = (OUT_W, OUT_H),
) -> str:
    """`crops` (one per cut, all the same size) crops each piece around its own action instead of the single `crop`.
    `has_audio=False` (a silent source) puts silence under every piece, so the output still has a sound track."""
    if not cuts:
        raise ValueError("no cuts")
    if crops is not None and len(crops) != len(cuts):
        raise ValueError("one crop per cut")
    parts: list[str] = []
    # Some pieces show the whole picture: then every piece is brought to the output size before they are joined.
    mixed = any(c.framing == "whole" for c in cuts)
    for i, c in enumerate(cuts):
        d = c.duration
        fade = min(CROSSFADE_S, d / 4)
        trim = f"[0:v]trim=start={c.start:.3f}:end={c.end:.3f},setpts=PTS-STARTPTS"
        own = f",crop={crops[i].w}:{crops[i].h}:{crops[i].x}:{crops[i].y}" if crops else ""
        if mixed and c.framing == "whole":
            parts.append(_whole_picture(trim, i, size))
        elif mixed:
            box = crops[i] if crops else crop
            parts.append(f"{trim},crop={box.w}:{box.h}:{box.x}:{box.y},scale={size[0]}:{size[1]}:flags=lanczos,setsar=1[v{i}]")
        else:
            parts.append(f"{trim}{own}[v{i}]")
        if has_audio:
            parts.append(
                f"[0:a]atrim=start={c.start:.3f}:end={c.end:.3f},asetpts=PTS-STARTPTS,"
                f"afade=t=in:st=0:d={fade:.3f},afade=t=out:st={d - fade:.3f}:d={fade:.3f}[a{i}]"
            )
        else:
            parts.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={d:.3f},asetpts=PTS-STARTPTS[a{i}]")
    inputs = "".join(f"[v{i}][a{i}]" for i in range(len(cuts)))
    parts.append(f"{inputs}concat=n={len(cuts)}:v=1:a=1[vcat][acat]")

    if mixed:  # already cropped / fitted piece by piece
        video = f"[vcat]fps={OUT_FPS}"
    else:
        one_crop = "" if crops else f"crop={crop.w}:{crop.h}:{crop.x}:{crop.y},"
        video = f"[vcat]{one_crop}scale={size[0]}:{size[1]}:flags=lanczos,setsar=1,fps={OUT_FPS}"
    if captions:
        video += f",ass={ASS_NAME}"
    parts.append(video + "[vout]")

    speech = "[acat]aresample=48000,aformat=channel_layouts=stereo[sp]"
    parts.append(speech)
    if music:
        fade_out = min(1.0, total / 2)
        parts.append(
            f"[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={music_volume:.3f},"
            f"atrim=end={total:.3f},afade=t=out:st={max(total - fade_out, 0):.3f}:d={fade_out:.3f}[mu]"
        )
        parts.append("[sp][mu]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]")
        parts.append("[mix]loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
    else:
        parts.append("[sp]loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
    return ";\n".join(parts)
