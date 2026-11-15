"""Studio renderer: scenes -> one MP4, with FFmpeg.

How it works, in three steps (every step is one FFmpeg run, arguments are always passed as a list):
  1. every scene is rendered on its own into a lossless-ish intermediate: its clips and pictures one after
     another (fitted to the frame, optional slow zoom), the black card when it has none, the texts, the
     voice-over and music mixed under, and the fade from / to black;
  2. scenes that are joined by a cross-fade are blended pairwise into one piece;
  3. the pieces are joined, the music under the whole video is added, the loudness is evened out, and the
     result is encoded once into the final MP4.
The user's text only ever reaches FFmpeg inside an ASS file, never in a command line.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from .. import auth, db, features
from ..config import get_settings
from ..editing import overlays as ov
from ..services import media
from . import store
from .schemas import (
    AUDIO_RATE,
    DEFAULT_IMAGE_S,
    FPS,
    MAX_SCENE_SECONDS,
    Credits,
    Overlay,
    Scene,
    Shape,
    StudioDoc,
    StudioText,
    Visual,
    frame_size,
)

log = logging.getLogger(__name__)

FONTS_DIR = Path(__file__).parent / "fonts"  # font files shipped with Studio (the title fonts)
ZOOM_AMOUNT = 0.10  # a zoomed clip grows (or shrinks) by 10 % over its time on screen
LOUDNESS = "loudnorm=I=-16:TP=-1.5:LRA=11"
# music gets quieter while speech is on: the speech is the "side chain" (about -28 dB and up triggers it)
DUCK = "threshold=0.04:ratio=9:attack=20:release=450:makeup=1"


class StudioError(Exception):
    """A message that is safe to show to the user."""


@dataclass
class AssetRef:
    id: str
    kind: str  # video | audio | image
    path: Path
    duration: float  # seconds (0 for pictures)
    has_audio: bool
    name: str = ""


@dataclass
class ScenePlan:
    scene: Scene
    duration: float  # frame-exact
    visuals: list[tuple[Visual, AssetRef, float]]  # each with the seconds of it that is used (a grid scene: its cells)
    hold: float  # seconds the last visual is held (a still frame) to fill the scene
    voiceover: AssetRef | None
    music: AssetRef | None
    overlays: list[tuple[Overlay, AssetRef]] = field(default_factory=list)
    is_grid: bool = False
    duck: bool = False  # the music lowers while the voice-over speaks


CREDITS_PX_PER_SECOND = 0.10  # a comfortable reading speed: the frame's height in ten seconds
CREDITS_LINE_HEIGHT = 1.35
HEADING_SCALE = 1.45


def credits_block_height(credits: Credits, height: int, width: int) -> float:
    """Pixels the whole list of credits takes up on screen."""
    size = credits.size / 100 * width
    return sum(size * (HEADING_SCALE if line.startswith("# ") else 1.0) * CREDITS_LINE_HEIGHT for line in credits.lines) or size


def credits_seconds(credits: Credits) -> float:
    """How long the roll lasts: what was asked for, or enough for a comfortable reading speed (measured on a 1920x1080 frame)."""
    if credits.seconds:
        return float(credits.seconds)
    return max(4.0, (1080 + credits_block_height(credits, 1080, 1920)) / (1080 * CREDITS_PX_PER_SECOND))


def frames(seconds: float) -> int:
    return max(1, round(seconds * FPS))


def snap(seconds: float) -> float:
    """Round to a whole number of frames, so scenes add up exactly."""
    return round(frames(seconds) / FPS, 5)


# ---------------------------------------------------------------------------
# planning (pure, no files touched)
# ---------------------------------------------------------------------------

def visual_length(v: Visual, asset: AssetRef) -> float:
    if asset.kind == "image":
        return snap(v.length or DEFAULT_IMAGE_S)
    available = asset.duration - v.start
    if available < 0.1:
        raise StudioError(f"The start point of “{asset.name or 'a clip'}” is past its end ({asset.duration:.1f} s long).")
    return snap(min(v.length, available) if v.length else available)


def plan_scene(scene: Scene, assets: dict[str, AssetRef], *, duck_allowed: bool = False) -> ScenePlan:
    def need(asset_id: str, kinds: tuple[str, ...], what: str) -> AssetRef:
        a = assets.get(asset_id)
        if a is None:
            raise StudioError(f"Scene “{scene.name}” uses a file that was deleted ({what}). Remove it from the scene or upload it again.")
        if a.kind not in kinds:
            raise StudioError(f"Scene “{scene.name}”: “{a.name}” can't be used as {what}.")
        return a

    is_grid = scene.grid is not None
    sources = scene.grid.cells if scene.grid else scene.visuals
    vo = need(scene.voiceover.asset_id, ("audio",), "a voice-over") if scene.voiceover else None
    music = need(scene.music.asset_id, ("audio",), "music") if scene.music else None
    overlays = [(o, need(o.asset_id, ("video", "image"), "a picture over the scene")) for o in scene.overlays]
    vo_end = scene.voiceover.offset + vo.duration if scene.voiceover and vo else 0.0

    # an equal share of the voice-over (or of the minimum length) for every clip, when asked for
    target = max(vo_end, scene.min_duration or 0.0)
    share = snap(target / len(sources)) if scene.fit_to_voiceover and not is_grid and sources and target > 0 else None

    visuals: list[tuple[Visual, AssetRef, float]] = []
    for v in sources:
        a = need(v.asset_id, ("video", "image"), "a clip or picture")
        if share is not None:
            length = share if a.kind == "image" else snap(min(share, max(a.duration - v.start, 1 / FPS)))
        else:
            length = visual_length(v, a)
        visuals.append((v, a, length))

    if is_grid:  # every cell plays together, after the (optional) wait
        visual_total = max((length for _, _, length in visuals), default=0.0) + (scene.grid.delay if visuals and scene.grid else 0.0)
    else:
        visual_total = sum(length for _, _, length in visuals)
    credits_s = credits_seconds(scene.credits) if scene.credits and scene.credits.lines else 0.0
    longest = max(visual_total, vo_end, scene.min_duration or 0.0, credits_s)
    if longest <= 0:
        raise StudioError(f"Scene “{scene.name}” is empty. Add a clip, a picture or a voice-over, or give it a minimum length.")
    duration = snap(longest)
    if duration > MAX_SCENE_SECONDS:
        raise StudioError(f"Scene “{scene.name}” is longer than {MAX_SCENE_SECONDS // 60} minutes.")
    hold = round(duration - visual_total, 5) if visuals and not is_grid and duration - visual_total > 0.5 / FPS else 0.0
    duck = bool(duck_allowed and scene.music and scene.music.duck and scene.voiceover)
    return ScenePlan(scene, duration, visuals, hold, vo, music, overlays, is_grid, duck)


def check_doc_allowed(doc: StudioDoc, feats: dict[str, Any]) -> list[str]:
    """What the document uses that the account's plan doesn't include (empty = fine)."""
    problems: list[str] = []
    if len(doc.scenes) > feats["studio_max_scenes"]:
        problems.append(f"Your plan allows up to {feats['studio_max_scenes']} scenes in a project.")
    if not feats["studio_crossfade"] and any(s.transition_in == "crossfade" for s in doc.scenes[1:]):
        problems.append("Cross-fade between scenes isn't included in your plan (fade through black is).")
    if not feats["studio_text_effects"] and any(t.font or t.anim != "none" for s in doc.scenes for t in s.texts):
        problems.append("Title fonts and the zoom animation aren't included in your plan.")
    if not feats["studio_overlays"] and any(s.overlays or s.shapes or s.open_effect != "none" for s in doc.scenes):
        problems.append("Pictures over a scene, highlights, pins and the narrow-frame opening aren't included in your plan.")
    if not feats["studio_grid"] and any(s.grid for s in doc.scenes):
        problems.append("Grid scenes (several clips at once) aren't included in your plan.")
    if not feats["studio_credits"] and any(s.credits for s in doc.scenes):
        problems.append("Rolling credits aren't included in your plan.")
    if not feats["studio_auto_montage"] and any(s.fit_to_voiceover for s in doc.scenes):
        problems.append("Spreading clips evenly under a voice-over isn't included in your plan.")
    if not feats["studio_text_effects"] and any(s.credits and s.credits.font for s in doc.scenes):
        problems.append("Title fonts aren't included in your plan.")
    return problems


# ---------------------------------------------------------------------------
# text (ASS)
# ---------------------------------------------------------------------------

_ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: TextOutline,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,4,1,5,0,0,0,1
Style: TextBox,Arial,60,&H00FFFFFF,&H000000FF,&H99000000,&H99000000,-1,0,0,0,100,100,0,0,3,8,0,5,0,0,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""


def text_line(t: StudioText, width: int, height: int, total: float) -> str | None:
    start = min(t.start, total)
    end = min(t.end if t.end is not None else total, total)
    if end - start < 0.05:
        return None  # starts after the scene ends
    size_px = max(8, round(t.size / 100 * width))
    tags = ["\\an5", f"\\pos({t.x * width:.0f},{t.y * height:.0f})", f"\\fs{size_px}", f"\\c{ov.hex_to_ass(t.color)}", f"\\b{1 if t.bold else 0}"]
    if t.font:
        tags.append(f"\\fn{t.font}")
    if t.style == "plain":
        tags += ["\\bord0", "\\shad0"]
    elif t.style == "box":
        tags += [f"\\bord{max(4, round(size_px * 0.28))}", "\\shad0"]
    else:
        tags += [f"\\bord{max(2, round(size_px * 0.09))}", f"\\shad{max(1, round(size_px * 0.03))}"]
    if t.fade:
        tags.append("\\fad(150,150)")
    ms = max(1, int((end - start) * 1000))
    if t.anim == "zoom_in":
        tags += ["\\fscx88\\fscy88", f"\\t(0,{ms},\\fscx112\\fscy112)"]
    elif t.anim == "zoom_out":
        tags += ["\\fscx112\\fscy112", f"\\t(0,{ms},\\fscx88\\fscy88)"]
    style = "TextBox" if t.style == "box" else "TextOutline"
    body = ov._escape(ov.wrap_text(t.text, t.size))
    return f"Dialogue: 2,{ov._ts(start)},{ov._ts(end)},{style},,0,0,0,,{{{''.join(tags)}}}{body}"


_KAPPA = 0.5523  # how far a bezier control point sits from the ends so four curves make a circle


def _ellipse_path(cx: float, cy: float, rx: float, ry: float) -> str:
    k = _KAPPA
    pts = [
        ("m", cx - rx, cy),
        ("b", cx - rx, cy - k * ry, cx - k * rx, cy - ry, cx, cy - ry),
        ("b", cx + k * rx, cy - ry, cx + rx, cy - k * ry, cx + rx, cy),
        ("b", cx + rx, cy + k * ry, cx + k * rx, cy + ry, cx, cy + ry),
        ("b", cx - k * rx, cy + ry, cx - rx, cy + k * ry, cx - rx, cy),
    ]
    return " ".join(f"{op} " + " ".join(f"{v:.1f}" for v in nums) for op, *nums in pts)


def shape_line(s: Shape, width: int, height: int, total: float) -> str | None:
    """A drawn shape as an ASS vector drawing (positions in pixels of the frame)."""
    start = min(s.start, total)
    end = min(s.end if s.end is not None else total, total)
    if end - start < 0.05:
        return None
    cx, cy = s.x * width, s.y * height
    if s.kind == "rect":
        x0, x1, y0, y1 = cx - s.w * width / 2, cx + s.w * width / 2, cy - s.h * height / 2, cy + s.h * height / 2
        path = f"m {x0:.1f} {y0:.1f} l {x1:.1f} {y0:.1f} l {x1:.1f} {y1:.1f} l {x0:.1f} {y1:.1f}"
        fill = s.fill
    elif s.kind == "ellipse":
        path = _ellipse_path(cx, cy, s.w * width / 2, s.h * height / 2)
        fill = s.fill
    else:  # a map pin: (x, y) is the point it marks; the round head sits above it
        r = s.w * width / 2
        head = cy - 2.0 * r
        path = _ellipse_path(cx, head, r, r) + f" m {cx - 0.85 * r:.1f} {head + 0.6 * r:.1f} l {cx:.1f} {cy:.1f} l {cx + 0.85 * r:.1f} {head + 0.6 * r:.1f}"
        fill = max(s.fill, 1.0)
    colour = ov.hex_to_ass(s.color)
    alpha = f"&H{int(round((1 - fill) * 255)):02X}&"
    border = max(0.0, s.thickness / 100 * width) if s.kind != "pin" else 0.0
    ms = 350
    tags = ["\\an7", f"\\move(0,{-0.2 * height:.0f},0,0,0,{ms})" if s.anim == "drop" else "\\pos(0,0)", f"\\c{colour}", f"\\1a{alpha}",
            f"\\3c{colour}", f"\\bord{border:.1f}", "\\shad0"]
    if s.fade:
        tags.append("\\fad(150,150)")
    return f"Dialogue: 1,{ov._ts(start)},{ov._ts(end)},TextOutline,,0,0,0,,{{{''.join(tags)}\\p1}}{path}{{\\p0}}"


def credits_line(c: Credits, width: int, height: int, total: float) -> str | None:
    """The whole list as one block of text that scrolls from below the frame to above it."""
    if not c.lines:
        return None
    size = c.size / 100 * width
    seconds = min(credits_seconds(c), total)
    block = credits_block_height(c, height, width)
    parts: list[str] = []
    for line in c.lines:
        if line.startswith("# "):
            parts.append(f"{{\\fs{size * HEADING_SCALE:.0f}\\b1}}{ov._escape(line[2:].strip()) or ' '}{{\\fs{size:.0f}\\b0}}")
        else:
            parts.append(ov._escape(line.strip()) or " ")
    tags = ["\\an8", f"\\move({width / 2:.0f},{height},{width / 2:.0f},{-block:.0f},0,{int(seconds * 1000)})", f"\\fs{size:.0f}", f"\\c{ov.hex_to_ass(c.color)}",
            "\\b0", "\\bord2", "\\shad1", "\\fad(400,400)"]
    if c.font:
        tags.append(f"\\fn{c.font}")
    return f"Dialogue: 3,{ov._ts(0)},{ov._ts(seconds)},TextOutline,,0,0,0,,{{{''.join(tags)}}}{'\\N'.join(parts)}"


def scene_ass(texts: list[StudioText], width: int, height: int, total: float, shapes: list[Shape] | None = None,
              credits: Credits | None = None) -> str:
    lines = [ln for s in (shapes or []) if (ln := shape_line(s, width, height, total))]
    lines += [ln for t in texts if (ln := text_line(t, width, height, total))]
    if credits and (ln := credits_line(credits, width, height, total)):
        lines.append(ln)
    return _ASS_HEAD.format(w=width, h=height) + "\n".join(lines) + "\n"


def font_families() -> list[str]:
    """Family names of the fonts shipped in app/studio/fonts/ (empty until some are added)."""
    names: list[str] = []
    try:
        from PIL import ImageFont

        for f in sorted(FONTS_DIR.glob("*")):
            if f.suffix.lower() in (".ttf", ".otf"):
                family = ImageFont.truetype(str(f), 20).getname()[0]
                if family and family not in names:
                    names.append(family)
    except Exception:  # an unreadable font file must never break the page
        log.exception("could not read the Studio fonts")
    return names


# ---------------------------------------------------------------------------
# FFmpeg command building
# ---------------------------------------------------------------------------

_graph_flag: str | None = None


def graph_flag() -> str:
    """How this FFmpeg reads a filter graph from a file: `-/filter_complex` (FFmpeg 7+) or `-filter_complex_script` (older).

    Long scenes make filter graphs too long for a Windows command line, so they always go through a file."""
    global _graph_flag
    if _graph_flag is None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            g = Path(tmp) / "g.txt"
            g.write_text("anullsrc=r=8000:cl=mono,atrim=0:0.1[a]", encoding="utf-8")
            for flag in ("-/filter_complex", "-filter_complex_script"):
                proc = media.run_tool(
                    [get_settings().ffmpeg, "-y", "-hide_banner", "-loglevel", "error", flag, str(g), "-map", "[a]", "-f", "null", "-"],
                    timeout=30,
                )
                if proc.returncode == 0:
                    _graph_flag = flag
                    break
            else:
                raise StudioError("This FFmpeg is too old or broken to render Studio videos.")
    return _graph_flag


def _even(n: float) -> int:
    return max(2, int(n) // 2 * 2)


def _fit_chain(idx: int, v: Visual, w: int, h: int) -> list[str]:
    """Filters that turn input idx into a frame exactly w x h, ending in label [f{idx}]."""
    pre = f"[{idx}:v]fps={FPS},setpts=PTS-STARTPTS"
    if v.fit == "crop":
        return [f"{pre},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1[f{idx}]"]
    if v.fit == "fit":
        return [f"{pre},scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[f{idx}]"]
    sw, sh = _even(w / 8), _even(h / 8)  # blurred copy behind: made small, then enlarged (cheap and smooth)
    return [
        f"{pre},split=2[s{idx}a][s{idx}b]",
        f"[s{idx}a]scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},boxblur=3:2,scale={w}:{h},eq=brightness=-0.12[bg{idx}]",
        f"[s{idx}b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg{idx}]",
        f"[bg{idx}][fg{idx}]overlay=(W-w)/2:(H-h)/2,setsar=1[f{idx}]",
    ]


def _visual_filters(idx: int, v: Visual, asset: AssetRef, w: int, h: int, length: float, hold: float, lead: float = 0.0) -> list[str]:
    """Filters for one clip or picture. `lead` = seconds of black (and silence) before it starts (grid cells that appear late)."""
    total = length + hold
    chain = _fit_chain(idx, v, w, h)
    tail = ""
    if v.zoom != "none":
        p = f"min(t/{length:.3f},1)" if v.zoom == "in" else f"(1-min(t/{length:.3f},1))"
        grown_w = f"trunc({w}*(1+{ZOOM_AMOUNT}*{p})/2)*2"
        grown_h = f"trunc({h}*(1+{ZOOM_AMOUNT}*{p})/2)*2"
        tail += f"scale=w='{grown_w}':h='{grown_h}':eval=frame:flags=bicubic,crop={w}:{h},"
    if asset.kind == "video" and hold > 0:
        tail += f"tpad=stop_mode=clone:stop_duration={hold:.3f},"
    wait = f",tpad=start_duration={lead:.3f}:start_mode=add:color=black" if lead > 0 else ""
    chain.append(f"[f{idx}]{tail}format=yuv420p,trim=duration={total:.3f},setpts=PTS-STARTPTS{wait}[v{idx}]")
    if asset.kind == "video" and asset.has_audio and v.volume > 0:
        late = f",adelay={int(lead * 1000)}:all=1" if lead > 0 else ""
        chain.append(
            f"[{idx}:a]aresample={AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,volume={v.volume:.3f},"
            f"apad=whole_dur={total:.3f},atrim=0:{total:.3f},asetpts=PTS-STARTPTS{late}[a{idx}]"
        )
    else:
        chain.append(
            f"anullsrc=r={AUDIO_RATE}:cl=stereo,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:{total + lead:.3f},asetpts=PTS-STARTPTS[a{idx}]"
        )
    return chain


def _encode_args(quality: Literal["final", "preview"]) -> list[str]:
    preset, crf = ("veryfast", "14") if quality == "final" else ("ultrafast", "26")
    return ["-c:v", "libx264", "-preset", preset, "-crf", crf, "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "pcm_s16le", "-ar", str(AUDIO_RATE), "-ac", "2"]


def build_scene_graph(plan: ScenePlan, w: int, h: int, has_text: bool) -> tuple[list[str], str]:
    """(input arguments, filter graph text) for one scene."""
    scene, total = plan.scene, plan.duration
    inputs: list[str] = []
    parts: list[str] = []
    n_inputs = 0

    if plan.visuals and plan.is_grid and scene.grid:
        grid = scene.grid
        cells = plan.visuals[: grid.cols * grid.rows]
        gap = round(grid.gap * w / 1920)
        cell_w = _even((w - gap * (grid.cols + 1)) / grid.cols)
        cell_h = _even((h - gap * (grid.rows + 1)) / grid.rows)
        vlabels, alabels, layout = "", "", []
        for i, (v, asset, length) in enumerate(cells):
            hold = max(total - grid.delay - length, 0.0)  # a cell whose clip is shorter than the scene holds its last frame
            if asset.kind == "image":
                inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{length + hold:.3f}", "-i", str(asset.path)]
            else:
                inputs += ["-ss", f"{v.start:.3f}", "-t", f"{length:.3f}", "-i", str(asset.path)]
            parts += _visual_filters(n_inputs, v, asset, cell_w, cell_h, length, hold, lead=grid.delay)
            vlabels += f"[v{n_inputs}]"
            alabels += f"[a{n_inputs}]"
            layout.append(f"{(i % grid.cols) * (cell_w + gap)}_{(i // grid.cols) * (cell_h + gap)}")
            n_inputs += 1
        used_cols = min(grid.cols, len(cells))
        used_rows = -(-len(cells) // grid.cols)
        stacked = f"{vlabels}xstack=inputs={len(cells)}:layout={'|'.join(layout)}:fill=black" if len(cells) > 1 else f"{vlabels}null"
        parts.append(f"{stacked}[gx]")
        pad_w, pad_h = used_cols * cell_w + (used_cols - 1) * gap, used_rows * cell_h + (used_rows - 1) * gap
        parts.append(f"[gx]pad={w}:{h}:{(w - pad_w) // 2}:{(h - pad_h) // 2}:color={scene.background}[vc]")
        parts.append(f"{alabels}amix=inputs={len(cells)}:duration=longest:normalize=0[ac]" if len(cells) > 1 else f"{alabels}anull[ac]")
    elif plan.visuals:
        labels = ""
        last = len(plan.visuals) - 1
        for i, (v, asset, length) in enumerate(plan.visuals):
            hold = plan.hold if i == last else 0.0
            if asset.kind == "image":
                inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{length + hold:.3f}", "-i", str(asset.path)]
            else:
                inputs += ["-ss", f"{v.start:.3f}", "-t", f"{length:.3f}", "-i", str(asset.path)]
            parts += _visual_filters(n_inputs, v, asset, w, h, length, hold)
            labels += f"[v{n_inputs}][a{n_inputs}]"
            n_inputs += 1
        parts.append(f"{labels}concat=n={len(plan.visuals)}:v=1:a=1[vc][ac]")
    else:
        parts.append(f"color=c={scene.background}:s={w}x{h}:r={FPS}:d={total:.3f},format=yuv420p[vc]")
        parts.append(f"anullsrc=r={AUDIO_RATE}:cl=stereo,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:{total:.3f},asetpts=PTS-STARTPTS[ac]")

    # picture: pictures and clips laid over the scene, then the drawn shapes / texts / credits, then the opening effect
    video = "[vc]"
    for k, (o, asset) in enumerate(plan.overlays):
        start = min(o.start, total)
        end = min(o.end if o.end is not None else total, total)
        if end - start < 0.05:
            continue  # starts after the scene ends
        if asset.kind == "image":
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total:.3f}", "-i", str(asset.path)]
        else:
            inputs += ["-t", f"{total:.3f}", "-i", str(asset.path)]
        ow = _even(o.width * w)
        if o.anim == "pop":
            factor = f"(0.8+0.2*min(max((t-{start:.3f})/0.3,0),1))"
        elif o.anim == "zoom_in":
            factor = f"(1+0.1*min(max((t-{start:.3f})/{end - start:.3f},0),1))"
        else:
            factor = None
        scale = f"scale=w={ow}:h=-2" if factor is None else f"scale=w='trunc({ow}*{factor}/2)*2':h=-2:eval=frame"
        chain = f"[{n_inputs}:v]format=rgba,setpts=PTS-STARTPTS+{start:.3f}/TB,{scale}"
        if o.fade and end - start > 0.7:
            chain += f",fade=t=in:st={start:.3f}:d=0.3:alpha=1,fade=t=out:st={end - 0.3:.3f}:d=0.3:alpha=1"
        parts.append(f"{chain}[ov{k}]")
        parts.append(
            f"{video}[ov{k}]overlay=x='{o.x * w:.1f}-w/2':y='{o.y * h:.1f}-h/2':eval=frame:eof_action=pass:"
            f"enable='between(t,{start:.3f},{end:.3f})'[vo{k}]"
        )
        video = f"[vo{k}]"
        n_inputs += 1
    if has_text:
        parts.append(f"{video}ass=scene.ass:fontsdir=fonts[vt]")
        video = "[vt]"
    if scene.open_effect == "letterbox":
        bar_h, band, d = _even(h / 2), 0.4 * h, scene.open_s  # two black bars start covering 40 % each, then slide away
        for k, y_expr in enumerate((f"-{bar_h}+{band:.1f}*(1-min(t/{d:.3f},1))", f"{h}-{band:.1f}*(1-min(t/{d:.3f},1))")):
            parts.append(f"color=c=black:s={w}x{bar_h}:r={FPS}:d={total:.3f},format=yuv420p[bar{k}]")
            parts.append(f"{video}[bar{k}]overlay=x=0:y='{y_expr}':eval=frame[lb{k}]")
            video = f"[lb{k}]"
    fades = []
    if scene.fade_in > 0:
        fades.append(f"fade=t=in:st=0:d={min(scene.fade_in, total):.3f}")
    if scene.fade_out > 0:
        d = min(scene.fade_out, total)
        fades.append(f"fade=t=out:st={total - d:.3f}:d={d:.3f}")
    parts.append(f"{video}{','.join(fades) if fades else 'null'}[vout]")

    # sound: the clips' own sound, the voice-over and the music, mixed
    parts.append(f"[ac]apad=whole_dur={total:.3f},atrim=0:{total:.3f},asetpts=PTS-STARTPTS[abase]")
    mix = ["[abase]"]
    if plan.voiceover and scene.voiceover:
        inputs += ["-i", str(plan.voiceover.path)]
        ms = int(scene.voiceover.offset * 1000)
        parts.append(
            f"[{n_inputs}:a]aresample={AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,volume={scene.voiceover.volume:.3f},"
            f"adelay={ms}:all=1,atrim=0:{total:.3f},asetpts=PTS-STARTPTS[avo{'0' if plan.duck else ''}]"
        )
        if plan.duck:  # one copy goes into the mix, the other tells the music when to get quieter
            parts.append("[avo0]asplit=2[avo][avosc]")
        mix.append("[avo]")
        n_inputs += 1
    if plan.music and scene.music:
        m = scene.music
        inputs += ["-stream_loop", "-1", "-ss", f"{m.start:.3f}", "-i", str(plan.music.path)]
        chain = (f"[{n_inputs}:a]aresample={AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,volume={m.volume:.3f},"
                 f"atrim=0:{total:.3f},asetpts=PTS-STARTPTS")
        if m.fade_in > 0:
            chain += f",afade=t=in:st=0:d={min(m.fade_in, total):.3f}"
        if m.fade_out > 0:
            d = min(m.fade_out, total)
            chain += f",afade=t=out:st={total - d:.3f}:d={d:.3f}"
        if plan.duck:
            parts.append(chain + "[amu0]")
            parts.append(f"[amu0][avosc]sidechaincompress={DUCK}[amu]")
        else:
            parts.append(chain + "[amu]")
        mix.append("[amu]")
        n_inputs += 1
    mixed = "".join(mix)
    audio_chain = f"{mixed}amix=inputs={len(mix)}:duration=first:normalize=0" if len(mix) > 1 else f"{mixed}anull"
    afades = []
    if scene.fade_in > 0:
        afades.append(f"afade=t=in:st=0:d={min(scene.fade_in, total):.3f}")
    if scene.fade_out > 0:
        d = min(scene.fade_out, total)
        afades.append(f"afade=t=out:st={total - d:.3f}:d={d:.3f}")
    parts.append(",".join([audio_chain, *afades, "alimiter=limit=0.97:level=0"]) + "[aout]")
    return inputs, ";\n".join(parts)


def _run(cmd: list[str], work: Path, total: float, on_frac: Callable[[float], None]) -> None:
    media.run_ffmpeg_with_progress(cmd, work, total, on_frac)


def render_scene(plan: ScenePlan, w: int, h: int, work: Path, out: Path, quality: Literal["final", "preview"],
                 on_frac: Callable[[float], None]) -> None:
    """One scene -> out (an .mkv intermediate)."""
    scene = plan.scene
    has_ass = bool(scene.texts or scene.shapes or (scene.credits and scene.credits.lines))
    if has_ass:
        (work / "scene.ass").write_text(scene_ass(list(scene.texts), w, h, plan.duration, list(scene.shapes), scene.credits), encoding="utf-8")
    else:
        (work / "scene.ass").unlink(missing_ok=True)
    inputs, graph = build_scene_graph(plan, w, h, has_ass)
    (work / "graph.txt").write_text(graph, encoding="utf-8")
    cmd = [get_settings().ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1",
           *inputs, graph_flag(), "graph.txt", "-map", "[vout]", "-map", "[aout]", *_encode_args(quality),
           "-t", f"{plan.duration:.3f}", str(out)]
    try:
        _run(cmd, work, plan.duration, on_frac)
    except media.MediaError as exc:
        log.error("scene %r failed: %s", plan.scene.name, exc)
        raise StudioError(f"Scene “{plan.scene.name}” could not be made. Check its clips (a damaged or unusual file can cause this).") from exc
    if not out.is_file() or out.stat().st_size < 1000:
        raise StudioError(f"Scene “{plan.scene.name}” came out empty.")


def crossfade_graph(durations: list[float], fades: list[float]) -> tuple[str, float]:
    """Filter graph blending pieces 0..n-1 with a cross-fade of fades[i] seconds into piece i. Returns (graph, total length)."""
    # every piece gets the same frame rate and timebase first: xfade refuses inputs that differ
    parts: list[str] = [f"[0:v]fps={FPS},settb=AVTB[n0v]"]
    cur_v, cur_a, length = "[n0v]", "[0:a]", durations[0]
    for i in range(1, len(durations)):
        d = fades[i]
        parts.append(f"[{i}:v]fps={FPS},settb=AVTB[n{i}v]")
        parts.append(f"{cur_v}[n{i}v]xfade=transition=fade:duration={d:.3f}:offset={length - d:.3f}[xv{i}]")
        parts.append(f"{cur_a}[{i}:a]acrossfade=d={d:.3f}:c1=tri:c2=tri[xa{i}]")
        cur_v, cur_a = f"[xv{i}]", f"[xa{i}]"
        length = length + durations[i] - d
    parts.append(f"{cur_v}null[vout]")
    parts.append(f"{cur_a}anull[aout]")
    return ";\n".join(parts), round(length, 5)


def render_crossfade_run(pieces: list[Path], durations: list[float], fades: list[float], work: Path, out: Path,
                         quality: Literal["final", "preview"], on_frac: Callable[[float], None]) -> float:
    graph, length = crossfade_graph(durations, fades)
    (work / "xgraph.txt").write_text(graph, encoding="utf-8")
    cmd = [get_settings().ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1"]
    for p in pieces:
        cmd += ["-i", str(p)]
    cmd += [graph_flag(), "xgraph.txt", "-map", "[vout]", "-map", "[aout]", *_encode_args(quality), "-t", f"{length:.3f}", str(out)]
    try:
        _run(cmd, work, length, on_frac)
    except media.MediaError as exc:
        raise StudioError("Two scenes could not be blended with a cross-fade.") from exc
    return length


def build_final_command(listing: str, total: float, out: Path, bed: AssetRef | None, doc: StudioDoc,
                        quality: Literal["final", "preview"], duck: bool = False) -> tuple[list[str], str]:
    """Join the pieces (concat list file), add the music under the video, even out the loudness, encode once.

    Returns (command, filter graph). The graph must be written to fgraph.txt in the working folder: the command
    reads it from there."""
    cmd = [get_settings().ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1",
           "-f", "concat", "-safe", "0", "-i", listing]
    chain = [f"[0:a]aresample={AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo[main]"]
    last = "[main]"
    if bed is not None and doc.bed_music is not None:
        b = doc.bed_music
        cmd += ["-stream_loop", "-1", "-ss", f"{b.start:.3f}", "-i", str(bed.path)]
        fade = min(b.fade_out, total)
        bed_chain = (f"[1:a]aresample={AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,volume={b.volume:.3f},"
                     f"atrim=0:{total:.3f},asetpts=PTS-STARTPTS")
        if fade > 0.05:
            bed_chain += f",afade=t=out:st={total - fade:.3f}:d={fade:.3f}"
        if duck:  # the bed gets quieter whenever anything in the video speaks
            chain[0] = f"[0:a]aresample={AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,asplit=2[main][mainsc]"
            chain.append(bed_chain + "[bed0]")
            chain.append(f"[bed0][mainsc]sidechaincompress={DUCK}[bed]")
        else:
            chain.append(bed_chain + "[bed]")
        chain.append("[main][bed]amix=inputs=2:duration=first:normalize=0[mixed]")
        last = "[mixed]"
    tail = f"{LOUDNESS},aresample={AUDIO_RATE}," if doc.normalize_loudness else ""
    chain.append(f"{last}{tail}alimiter=limit=0.97:level=0[aout]")
    if quality == "final":
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS),
               "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_RATE)]
    else:
        enc = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p", "-r", str(FPS),
               "-c:a", "aac", "-b:a", "96k", "-ar", str(AUDIO_RATE)]
    return [*cmd, graph_flag(), "fgraph.txt", "-map", "0:v", "-map", "[aout]", *enc, "-t", f"{total:.3f}",
            "-movflags", "+faststart", str(out)], ";\n".join(chain)


# ---------------------------------------------------------------------------
# putting it together
# ---------------------------------------------------------------------------

def owner_features(project: dict[str, Any]) -> dict[str, Any]:
    uid = project.get("user_id")
    if uid is None or not get_settings().auth_enabled:
        return features.resolve("max", admin=True)
    row = db.get_user(uid)
    return auth.features_of(auth._to_user(row)) if row else features.resolve(features.DEFAULT_PLAN)


def asset_refs(project_id: str) -> dict[str, AssetRef]:
    base = store.project_dir(project_id) / "assets"
    return {
        a["id"]: AssetRef(a["id"], a["kind"], base / a["file"], float(a["duration"] or 0), bool(a["has_audio"]), a["original_name"] or "")
        for a in store.assets(project_id)
        if (base / a["file"]).is_file()
    }


@dataclass
class Prepared:
    doc: StudioDoc
    plans: list[ScenePlan]
    joins: list[float]  # seconds each scene is blended into the one before it (0 = a plain cut)
    total: float  # length of the finished video
    width: int
    height: int
    bed: AssetRef | None
    duck_bed: bool = False


def crossfade_seconds(plans: list[ScenePlan]) -> list[float]:
    """How long each scene is blended into the one before it (never the first; never more than half of either scene)."""
    joins = [0.0] * len(plans)
    for i in range(1, len(plans)):
        s = plans[i].scene
        if s.transition_in == "crossfade":
            joins[i] = round(min(s.crossfade_s, plans[i - 1].duration / 2, plans[i].duration / 2), 3)
    return joins


def describe_scenes(doc: StudioDoc, refs: dict[str, AssetRef]) -> tuple[list[dict[str, Any]], float]:
    """What the editor page shows next to each scene: its length, or what is wrong with it. Never raises."""
    infos: list[dict[str, Any]] = []
    plans: list[ScenePlan] = []
    for s in doc.scenes:
        try:
            p = plan_scene(s, refs)
            infos.append({"id": s.id, "duration": p.duration, "problem": None})
            plans.append(p)
        except StudioError as exc:
            infos.append({"id": s.id, "duration": None, "problem": str(exc)})
            plans.append(ScenePlan(s, 0.0, [], 0.0, None, None))
    joins = crossfade_seconds(plans)
    return infos, round(sum(p.duration for p in plans) - sum(joins), 5)


def prepare(project: dict[str, Any], kind: Literal["final", "preview"], scene_id: str | None) -> Prepared:
    """Everything that can be checked before any work is done. Raises StudioError (message fit to show)."""
    doc = StudioDoc.model_validate(project["doc_json"])
    feats = owner_features(project)
    problems = check_doc_allowed(doc, feats)
    if problems:
        raise StudioError(problems[0])
    scenes = [s for s in doc.scenes if scene_id is None or s.id == scene_id]
    if not scenes:
        raise StudioError("That scene no longer exists." if scene_id else "Add a scene first.")
    refs = asset_refs(project["id"])
    plans = [plan_scene(s, refs, duck_allowed=bool(feats["studio_ducking"])) for s in scenes]
    joins = crossfade_seconds(plans)
    total = round(sum(p.duration for p in plans) - sum(joins), 5)
    if kind == "final" and total > feats["studio_max_minutes"] * 60 + 0.5:
        raise StudioError(f"That video is {total / 60:.1f} minutes long; your plan allows up to {feats['studio_max_minutes']}.")
    w, h = frame_size(doc.shape, min(feats["studio_max_height"], 1080) if kind == "final" else 360)
    bed = refs.get(doc.bed_music.asset_id) if doc.bed_music else None
    if doc.bed_music and (bed is None or bed.kind != "audio"):
        raise StudioError("The music under the whole video was deleted. Remove it or choose another file.")
    if scene_id is not None:
        bed = None  # a single scene is previewed without the music under the whole video
    duck_bed = bool(bed is not None and doc.bed_music and doc.bed_music.duck and feats["studio_ducking"])
    return Prepared(doc, plans, joins, total, w, h, bed, duck_bed)


def render(project_id: str, kind: Literal["final", "preview"], scene_id: str | None,
           on_progress: Callable[[int], None] | None = None, on_stage: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Render the project (kind="final") or a quick low-quality preview of it or of one scene.

    Returns {"path": ..., **ffprobe info}. Raises StudioError (message fit to show)."""
    project = store.get(project_id)
    if project is None:
        raise StudioError("This project no longer exists.")
    prep = prepare(project, kind, scene_id)
    doc, plans, joins, total, w, h, bed = prep.doc, prep.plans, prep.joins, prep.total, prep.width, prep.height, prep.bed
    refs = asset_refs(project_id)
    quality: Literal["final", "preview"] = "final" if kind == "final" else "preview"

    base = store.project_dir(project_id)
    work = base / "work"
    shutil.rmtree(work, ignore_errors=True)
    (work / "fonts").mkdir(parents=True)
    if FONTS_DIR.is_dir():
        for f in FONTS_DIR.glob("*"):
            if f.suffix.lower() in (".ttf", ".otf"):
                shutil.copy2(f, work / "fonts" / f.name)
    for a in refs.values():  # the fonts the user uploaded to this project
        if a.kind == "font":
            shutil.copy2(a.path, work / "fonts" / a.path.name)

    done_s = 0.0
    scene_s = sum(p.duration for p in plans)

    def progress(frac_of_total: float) -> None:
        if on_progress:
            on_progress(min(max(int(frac_of_total * 100), 0), 99))

    try:
        pieces: list[Path] = []
        for i, plan in enumerate(plans):
            if on_stage:
                on_stage(f"Scene {i + 1} of {len(plans)}: {plan.scene.name}")
            out = work / f"scene_{i:03d}.mkv"
            before = done_s

            def on_frac(f: float, before: float = before, d: float = plan.duration) -> None:
                progress(0.85 * (before + f * d) / scene_s)

            render_scene(plan, w, h, work, out, quality, on_frac)
            done_s += plan.duration
            pieces.append(out)

        # blend the cross-faded scenes into single pieces
        if any(j > 0 for j in joins):
            if on_stage:
                on_stage("Blending scenes")
            merged: list[tuple[Path, float]] = []
            i = 0
            while i < len(plans):
                j = i + 1
                while j < len(plans) and joins[j] > 0:
                    j += 1
                if j - i == 1:
                    merged.append((pieces[i], plans[i].duration))
                else:
                    out = work / f"run_{i:03d}.mkv"
                    length = render_crossfade_run(pieces[i:j], [p.duration for p in plans[i:j]], joins[i:j], work, out, quality,
                                                  lambda f: progress(0.85 + 0.05 * f))
                    merged.append((out, length))
                i = j
        else:
            merged = [(p, plans[i].duration) for i, p in enumerate(pieces)]
        progress(0.9)

        if on_stage:
            on_stage("Putting it together")
        (work / "list.txt").write_text("".join(f"file '{p.name}'\n" for p, _ in merged), encoding="utf-8")
        if kind == "final":
            final = base / "output.mp4"
        else:
            final = base / "previews" / f"{scene_id or 'all'}.mp4"
        partial = final.with_suffix(".partial.mp4")
        partial.unlink(missing_ok=True)
        cmd, graph = build_final_command("list.txt", total, partial, bed, doc, quality, prep.duck_bed)
        (work / "fgraph.txt").write_text(graph, encoding="utf-8")
        try:
            _run(cmd, work, total, lambda f: progress(0.9 + 0.09 * f))
            info = _verify(partial, total, w, h)
        except media.MediaError as exc:
            partial.unlink(missing_ok=True)
            raise StudioError("Putting the scenes together failed. Check the server log.") from exc
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        final.parent.mkdir(parents=True, exist_ok=True)
        partial.replace(final)
        return {**info.to_dict(), "path": str(final)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _verify(path: Path, expected: float, width: int, height: int) -> media.MediaInfo:
    if not path.is_file() or path.stat().st_size < 3_000:
        raise media.MediaError("The finished video is missing or empty.")
    info = media.probe(path)
    if (info.width, info.height) != (width, height):
        raise media.MediaError("The finished video has the wrong size.")
    if abs(info.duration - expected) > max(1.0, expected * 0.03):
        raise media.MediaError(f"The finished video has an unexpected length ({info.duration:.1f} s, expected {expected:.1f} s).")
    return info
