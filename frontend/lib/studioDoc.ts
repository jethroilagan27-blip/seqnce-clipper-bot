// The Studio project document and a few small pure helpers. No React and no `@/` imports, so `npm test` can run them.
// The document mirrors backend/app/studio/schemas.py. Lengths of scenes are worked out by the server and
// come back with every save (so the page and the renderer can never disagree).

import { newText, type TextOverlay } from "./overlays.ts";

export type Shape = "landscape" | "vertical" | "square";
export const SHAPE_RATIO: Record<Shape, number> = { landscape: 16 / 9, vertical: 9 / 16, square: 1 };
export const SHAPE_LABEL: Record<Shape, string> = { landscape: "Landscape (16:9)", vertical: "Vertical (9:16)", square: "Square (1:1)" };

export type Fit = "blur" | "crop" | "fit";
export type Zoom = "none" | "in" | "out";

export type Visual = {
  id: string;
  asset_id: string;
  start: number;
  length: number | null; // null = to the end of the clip (pictures: 3 s)
  fit: Fit;
  zoom: Zoom;
  volume: number;
};
export type Voiceover = { asset_id: string; volume: number; offset: number };
export type SceneMusic = { asset_id: string; start: number; volume: number; fade_in: number; fade_out: number; duck: boolean };
export type BedMusic = { asset_id: string; start: number; volume: number; fade_out: number; duck: boolean };

/** A picture or small clip laid over the scene for a while (a poster, a flag, a map). x/y = its centre, width = fraction of the frame's width. */
export type Overlay = {
  id: string;
  asset_id: string;
  x: number;
  y: number;
  width: number;
  start: number;
  end: number | null;
  fade: boolean;
  anim: "none" | "pop" | "zoom_in";
};
export type ShapeKind = "rect" | "ellipse" | "pin";
/** A drawn highlight: a box, a circle, a map pin. */
export type DrawnShape = {
  id: string;
  kind: ShapeKind;
  x: number;
  y: number;
  w: number;
  h: number;
  color: string;
  thickness: number;
  fill: number;
  start: number;
  end: number | null;
  fade: boolean;
  anim: "none" | "drop";
};
export type Grid = { cols: number; rows: number; gap: number; delay: number; cells: Visual[] };
export type Credits = { lines: string[]; size: number; color: string; font: string; seconds: number | null };

export type Scene = {
  id: string;
  name: string;
  visuals: Visual[];
  voiceover: Voiceover | null;
  music: SceneMusic | null;
  texts: TextOverlay[];
  overlays: Overlay[];
  shapes: DrawnShape[];
  grid: Grid | null;
  credits: Credits | null;
  background: string;
  min_duration: number | null;
  fit_to_voiceover: boolean;
  open_effect: "none" | "letterbox";
  open_s: number;
  fade_in: number;
  fade_out: number;
  transition_in: "cut" | "crossfade";
  crossfade_s: number;
};

export type StudioDoc = {
  title: string;
  shape: Shape;
  scenes: Scene[];
  bed_music: BedMusic | null;
  normalize_loudness: boolean;
};

export type AssetKind = "video" | "audio" | "image" | "font";
export type Asset = {
  id: string;
  kind: AssetKind;
  name: string | null;
  width: number | null;
  height: number | null;
  duration: number | null;
  has_audio: boolean;
  size_bytes: number;
  /** Fonts only: the name a text asks for to use this font. */
  family?: string | null;
};

let counter = 0;
/** A short id that is safe in the document (letters, digits, - and _ only). */
export function uid(prefix: string): string {
  counter += 1;
  return `${prefix}${Date.now().toString(36)}${counter.toString(36)}`;
}

/** A copy of `items` with the item at `from` moved to `to` (out-of-range moves leave the list as it is). */
export function moveItem<T>(items: T[], from: number, to: number): T[] {
  if (from < 0 || from >= items.length || to < 0 || to >= items.length || from === to) return items;
  const copy = items.slice();
  const [item] = copy.splice(from, 1);
  copy.splice(to, 0, item);
  return copy;
}

export function emptyScene(n: number): Scene {
  return {
    id: uid("s"),
    name: `Scene ${n}`,
    visuals: [],
    voiceover: null,
    music: null,
    texts: [],
    overlays: [],
    shapes: [],
    grid: null,
    credits: null,
    background: "#000000",
    min_duration: null,
    fit_to_voiceover: false,
    open_effect: "none",
    open_s: 1.2,
    fade_in: 0,
    fade_out: 0,
    transition_in: "cut",
    crossfade_s: 0.8,
  };
}

/** A scene with the clips side by side (3 across, 2 down), every one starting together. */
export function gridScene(n: number): Scene {
  return { ...emptyScene(n), name: `Grid ${n}`, grid: { cols: 3, rows: 2, gap: 8, delay: 0, cells: [] } };
}

/** The rolling credits at the end of a video. */
export function creditsScene(n: number): Scene {
  return { ...emptyScene(n), name: "Credits", credits: { lines: ["# Credits", "Name one", "Name two"], size: 3.4, color: "#ffffff", font: "", seconds: null } };
}

export function newOverlay(asset: Asset): Overlay {
  return { id: uid("o"), asset_id: asset.id, x: 0.5, y: 0.5, width: 0.4, start: 0, end: null, fade: true, anim: "none" };
}

export function newShape(kind: ShapeKind): DrawnShape {
  return {
    id: uid("h"),
    kind,
    x: 0.5,
    y: kind === "pin" ? 0.6 : 0.5,
    w: kind === "pin" ? 0.04 : 0.3,
    h: kind === "ellipse" ? 0.2 : 0.1,
    color: kind === "pin" ? "#ff3b30" : "#ffd400",
    thickness: 0.4,
    fill: kind === "rect" ? 0.3 : 0,
    start: 0,
    end: null,
    fade: true,
    anim: kind === "pin" ? "drop" : "none",
  };
}

export function newCell(asset: Asset): Visual {
  return { ...newVisual(asset), fit: "crop", volume: 0 };
}

/** A card on black with one big centred text (a question, a title): fades in and out, shown for 4 seconds. */
export function textCardScene(n: number): Scene {
  return {
    ...emptyScene(n),
    name: `Text card ${n}`,
    min_duration: 4,
    fade_in: 0.5,
    fade_out: 0.5,
    texts: [newText({ text: "Your text", x: 0.5, y: 0.5, size: 7, fade: false })],
  };
}

export function newVisual(asset: Asset): Visual {
  return { id: uid("v"), asset_id: asset.id, start: 0, length: null, fit: "blur", zoom: "none", volume: asset.kind === "video" ? 1 : 0 };
}

export function duplicateScene(scene: Scene, n: number): Scene {
  return {
    ...scene,
    id: uid("s"),
    name: `${scene.name} copy`.slice(0, 80) || `Scene ${n}`,
    visuals: scene.visuals.map((v) => ({ ...v, id: uid("v") })),
    texts: scene.texts.map((t) => ({ ...t, id: uid("t") })),
    overlays: scene.overlays.map((o) => ({ ...o, id: uid("o") })),
    shapes: scene.shapes.map((s) => ({ ...s, id: uid("h") })),
    grid: scene.grid ? { ...scene.grid, cells: scene.grid.cells.map((c) => ({ ...c, id: uid("v") })) } : null,
  };
}

export function formatSeconds(s: number): string {
  const total = Math.round(s * 10) / 10;
  const m = Math.floor(total / 60);
  const rest = total - m * 60;
  return m > 0 ? `${m}:${rest.toFixed(1).padStart(4, "0")}` : `${rest.toFixed(1)} s`;
}

export function formatMegabytes(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return mb >= 100 ? `${Math.round(mb)} MB` : `${mb.toFixed(1)} MB`;
}

/** Drop the references to an asset from a document (the server does the same when a file is deleted). */
export function withoutAsset(doc: StudioDoc, assetId: string): StudioDoc {
  return {
    ...doc,
    scenes: doc.scenes.map((s) => ({
      ...s,
      visuals: s.visuals.filter((v) => v.asset_id !== assetId),
      overlays: s.overlays.filter((o) => o.asset_id !== assetId),
      grid: s.grid ? { ...s.grid, cells: s.grid.cells.filter((c) => c.asset_id !== assetId) } : null,
      voiceover: s.voiceover?.asset_id === assetId ? null : s.voiceover,
      music: s.music?.asset_id === assetId ? null : s.music,
    })),
    bed_music: doc.bed_music?.asset_id === assetId ? null : doc.bed_music,
  };
}
