// Numbers behind the admin page's usage graph. Pure functions, so they can be tested without a browser.

export type Counts = { videos: number; changes: number; ai: number; ai_own: number };

export const NO_USE: Counts = { videos: 0, changes: 0, ai: 0, ai_own: 0 };

/** "Video edits": new videos plus changes to videos. */
export const edits = (c: Counts) => c.videos + c.changes;
/** Requests sent to the AI, on any key. */
export const aiRequests = (c: Counts) => c.ai + c.ai_own;

/** Clean whole-number gridlines from 0 up to at least `max` (about four of them). */
export function niceTicks(max: number): number[] {
  const wanted = Math.max(max, 4) / 4;
  const power = 10 ** Math.floor(Math.log10(wanted));
  const step = Math.max(1, [1, 2, 5, 10].map((m) => m * power).find((s) => s >= wanted) ?? 10 * power);
  const ticks = [0];
  while (ticks[ticks.length - 1] < Math.max(max, 1)) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

/** "2026-11-05" -> "Nov 5". The date is a calendar day: it is not shifted by the time zone. */
export function dayLabel(date: string, locale?: string): string {
  const [y, m, d] = date.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(locale, { month: "short", day: "numeric" });
}

/** Which days get a label under the graph: evenly spread, always the first and the last. */
export function labelledDays(count: number, room: number): number[] {
  if (count <= 0) return [];
  const wanted = Math.max(2, Math.min(count, room));
  return [...new Set(Array.from({ length: wanted }, (_, i) => Math.round((i * (count - 1)) / Math.max(wanted - 1, 1))))];
}

/** A limit typed on the admin page: empty = whatever the plan says (null); otherwise a whole number 0..10000. */
export function parseLimit(text: string): number | null | undefined {
  const t = text.trim();
  if (!t) return null;
  const n = Number(t);
  return /^\d+$/.test(t) && n <= 10_000 ? n : undefined; // undefined = not a usable number
}
