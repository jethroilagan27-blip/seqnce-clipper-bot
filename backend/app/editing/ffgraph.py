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


def compute_crop(src_w: int, src_h: int, focus_x: float) -> CropBox:
    """Largest 9:16 window inside the source, centred on the speaker horizontally."""
    target = OUT_W / OUT_H
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


def build_filtergraph(
    cuts: Sequence[Cut],
    crop: CropBox,
    *,
    captions: bool,
    music: bool,
    music_volume: float,
    total: float,
) -> str:
    if not cuts:
        raise ValueError("no cuts")
    parts: list[str] = []
    for i, c in enumerate(cuts):
        d = c.duration
        fade = min(CROSSFADE_S, d / 4)
        parts.append(
            f"[0:v]trim=start={c.start:.3f}:end={c.end:.3f},setpts=PTS-STARTPTS[v{i}]"
        )
        parts.append(
            f"[0:a]atrim=start={c.start:.3f}:end={c.end:.3f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={fade:.3f},afade=t=out:st={d - fade:.3f}:d={fade:.3f}[a{i}]"
        )
    inputs = "".join(f"[v{i}][a{i}]" for i in range(len(cuts)))
    parts.append(f"{inputs}concat=n={len(cuts)}:v=1:a=1[vcat][acat]")

    video = (
        f"[vcat]crop={crop.w}:{crop.h}:{crop.x}:{crop.y},"
        f"scale={OUT_W}:{OUT_H}:flags=lanczos,setsar=1,fps={OUT_FPS}"
    )
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
