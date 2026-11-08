// Free text laid over a video, shared by photo mode and video mode. Pure helpers, no React.
// Positions are fractions (0..1) of the frame and mark the CENTRE of the text; sizes are a percentage of
// the frame width. The backend (app/editing/overlays.py) uses the same numbers and the same line-wrapping
// estimate, so what you drag in the preview is what gets rendered.

export type TextStyle = "outline" | "box" | "plain";

export type TextOverlay = {
  id: string;
  text: string;
  x: number;
  y: number;
  size: number; // % of frame width
  color: string; // #rrggbb
  style: TextStyle;
  bold: boolean;
  start: number; // seconds
  end: number | null; // null = until the end
  fade: boolean;
};

export const MAX_TEXTS = 30;
export const CHAR_WIDTH = 0.56; // average glyph width relative to the font size
export const MAX_LINE_FRACTION = 0.9;

export const TEXT_COLORS = ["#ffffff", "#000000", "#ffe600", "#ff4b4b", "#00e6ff", "#50e650", "#ff64c8", "#ff9600"];

export function charsPerLine(sizePct: number): number {
  return Math.max(4, Math.floor((MAX_LINE_FRACTION * 100) / (sizePct * CHAR_WIDTH)));
}

/** Break lines the way the renderer does (explicit line breaks are kept, long words are split). */
export function wrapText(text: string, sizePct: number): string {
  const width = charsPerLine(sizePct);
  const lines: string[] = [];
  for (const paragraph of text.split("\n")) {
    const words = paragraph.split(/\s+/).filter(Boolean);
    let line = "";
    for (let word of words) {
      while (word.length > width) {
        if (line) {
          lines.push(line);
          line = "";
        }
        lines.push(word.slice(0, width));
        word = word.slice(width);
      }
      if (!line) line = word;
      else if (line.length + 1 + word.length <= width) line += ` ${word}`;
      else {
        lines.push(line);
        line = word;
      }
    }
    lines.push(line);
  }
  return lines.join("\n");
}

export const clamp01 = (n: number) => Math.min(1, Math.max(0, n));

/** Is this text on screen at output time `t`? */
export function visibleAt(o: Pick<TextOverlay, "start" | "end">, t: number, total: number): boolean {
  return t >= o.start && t < Math.min(o.end ?? total, total) + 1e-6;
}

/** Snap a dragged coordinate to the middle of the frame when it is close. */
export function snapCenter(v: number, threshold = 0.02): number {
  return Math.abs(v - 0.5) <= threshold ? 0.5 : v;
}

let counter = 0;
export function newTextId(): string {
  counter += 1;
  return `t${Date.now().toString(36)}${counter}`;
}

export function newText(partial: Partial<TextOverlay> = {}): TextOverlay {
  return {
    id: newTextId(),
    text: "Your text",
    x: 0.5,
    y: 0.2,
    size: 8,
    color: "#ffffff",
    style: "outline",
    bold: true,
    start: 0,
    end: null,
    fade: true,
    ...partial,
  };
}
