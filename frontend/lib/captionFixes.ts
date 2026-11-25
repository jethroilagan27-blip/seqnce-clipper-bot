// Corrections to the captions: "between these two moments of the original video, the words are these".
// Pure logic, no app imports (tested with `node --test`). Mirrors backend/app/editing/fixes.py.

export type CaptionFix = { start: number; end: number; text: string };
type Sentence = { start: number; end: number; text: string };

export const MAX_FIX_CHARS = 600;

const same = (fix: CaptionFix, s: { start: number; end: number }) => Math.abs(fix.start - s.start) < 0.05 && Math.abs(fix.end - s.end) < 0.05;
const tidy = (text: string) => text.replace(/\s+/g, " ").trim();

export const fixFor = (fixes: CaptionFix[], s: Sentence): CaptionFix | undefined => fixes.find((f) => same(f, s));

/** What the captions will say for this sentence. */
export const captionText = (fixes: CaptionFix[], s: Sentence): string => fixFor(fixes, s)?.text ?? s.text.trim();

/**
 * The new list after correcting one sentence. Typing back what was heard removes the correction; empty text is kept
 * (it hides the caption there).
 */
export function setFix(fixes: CaptionFix[], s: Sentence, text: string): CaptionFix[] {
  const others = fixes.filter((f) => !same(f, s));
  const value = tidy(text).slice(0, MAX_FIX_CHARS);
  if (value === tidy(s.text)) return others;
  return [...others, { start: s.start, end: s.end, text: value }].sort((a, b) => a.start - b.start);
}
