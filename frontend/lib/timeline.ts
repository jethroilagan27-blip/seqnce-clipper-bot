// Pure helpers for the timeline editor. No React, no imports: unit-tested with `npm test`.
// All times are seconds. "source" = position in the uploaded video, "out" = position in the edited short.

export type DraftClip = {
  start: number;
  end: number;
  purpose: "hook" | "main_content" | "example" | "conclusion";
  reason: string;
};

export type Range = { start: number; end: number };
export type Cut = { start: number; end: number; out_start: number };
export type Page = { start: number; end: number; text: string };

export const MIN_CLIP_S = 1.0; // the server rejects shorter clips
export const MERGE_GAP_S = 0.05; // touching/overlapping clips are merged (same rule as the server)

const r3 = (n: number) => Math.round(n * 1000) / 1000;

export function sortClips<T extends Range>(clips: T[]): T[] {
  return [...clips].sort((a, b) => a.start - b.start || a.end - b.end);
}

/** Sort and merge clips that overlap or touch. */
export function mergeClips(clips: DraftClip[]): DraftClip[] {
  const out: DraftClip[] = [];
  for (const c of sortClips(clips)) {
    const last = out[out.length - 1];
    if (last && c.start <= last.end + MERGE_GAP_S) last.end = Math.max(last.end, c.end);
    else out.push({ ...c });
  }
  return out;
}

/** Remove [a, b] from every clip. Leftover pieces shorter than MIN_CLIP_S disappear. */
export function subtractRange(clips: DraftClip[], a: number, b: number): DraftClip[] {
  const out: DraftClip[] = [];
  for (const c of clips) {
    if (b <= c.start || a >= c.end) {
      out.push({ ...c });
      continue;
    }
    if (a - c.start >= MIN_CLIP_S) out.push({ ...c, end: r3(a) });
    if (c.end - b >= MIN_CLIP_S) out.push({ ...c, start: r3(b) });
  }
  return out;
}

/** Add [a, b] as a clip (merging with neighbours). */
export function addRange(clips: DraftClip[], a: number, b: number, duration: number): DraftClip[] {
  const start = Math.max(0, a);
  const end = Math.min(duration, b);
  if (end - start < MIN_CLIP_S) {
    // a very short sentence: grow it around its middle so it stays a valid clip
    const mid = (start + end) / 2;
    return addRange(clips, Math.max(0, mid - MIN_CLIP_S / 2), Math.min(duration, mid + MIN_CLIP_S / 2), duration);
  }
  return mergeClips([...clips, { start: r3(start), end: r3(end), purpose: "main_content", reason: "Added by hand" }]);
}

/** Is the middle of this range inside a kept clip? */
export function isKept(clips: Range[], r: Range): boolean {
  const mid = (r.start + r.end) / 2;
  return clips.some((c) => mid >= c.start && mid <= c.end);
}

/** Click on a transcript sentence: keep it if it was cut, cut it if it was kept. */
export function toggleRange(clips: DraftClip[], r: Range, duration: number): DraftClip[] {
  return isKept(clips, r) ? subtractRange(clips, r.start, r.end) : addRange(clips, r.start, r.end, duration);
}

/**
 * Move one edge of clip `index` to `value`, without crossing the neighbours, going outside the
 * video or making the clip shorter than MIN_CLIP_S.
 */
export function setEdge(
  clips: DraftClip[],
  index: number,
  edge: "start" | "end",
  value: number,
  duration: number,
): DraftClip[] {
  const c = clips[index];
  if (!c) return clips;
  const prevEnd = index > 0 ? clips[index - 1].end + MERGE_GAP_S : 0;
  const nextStart = index < clips.length - 1 ? clips[index + 1].start - MERGE_GAP_S : duration;
  const next = { ...c };
  if (edge === "start") next.start = r3(Math.min(Math.max(value, prevEnd), c.end - MIN_CLIP_S));
  else next.end = r3(Math.max(Math.min(value, nextStart), c.start + MIN_CLIP_S));
  return clips.map((x, i) => (i === index ? next : x));
}

/** Snap `t` to the nearest word boundary if one is within `tolerance` seconds. */
export function snapToWords(t: number, boundaries: number[], tolerance: number): number {
  let best = t;
  let bestDist = tolerance;
  for (const b of boundaries) {
    const d = Math.abs(b - t);
    if (d <= bestDist) {
      best = b;
      bestDist = d;
    }
  }
  return best;
}

export function clipsEqual(a: Range[], b: Range[]): boolean {
  return a.length === b.length && a.every((x, i) => Math.abs(x.start - b[i].start) < 0.005 && Math.abs(x.end - b[i].end) < 0.005);
}

/** Index of the cut containing output time `t` (the last cut that has started). */
export function cutIndexAtOut(cuts: Cut[], t: number): number {
  let idx = 0;
  for (let i = 0; i < cuts.length; i++) if (cuts[i].out_start <= t + 1e-6) idx = i;
  return idx;
}

export function outToSource(cuts: Cut[], t: number): number {
  if (!cuts.length) return 0;
  const c = cuts[cutIndexAtOut(cuts, t)];
  return Math.min(c.end, c.start + Math.max(0, t - c.out_start));
}

/** Output time for a source time; a time between cuts maps to the start of the next cut. */
export function sourceToOut(cuts: Cut[], src: number): number {
  for (const c of cuts) {
    if (src < c.start) return c.out_start;
    if (src <= c.end) return c.out_start + (src - c.start);
  }
  const last = cuts[cuts.length - 1];
  return last ? last.out_start + (last.end - last.start) : 0;
}

export function pageAt(pages: Page[], t: number): Page | null {
  return pages.find((p) => t >= p.start && t < p.end) ?? null;
}

/** A readable ruler step (seconds) so labels are at least `minPx` apart. */
export function rulerStep(pxPerSec: number, minPx = 64): number {
  const steps = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  return steps.find((s) => s * pxPerSec >= minPx) ?? 600;
}

export function formatTime(t: number): string {
  const s = Math.max(0, t);
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(1).padStart(4, "0")}`;
}
