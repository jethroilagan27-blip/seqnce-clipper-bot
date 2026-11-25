// The two shapes a video can be made in, and the lengths that can be asked for. The numbers match the renderer
// (backend/app/plan/schema.py and editing/captions.py), so the preview looks like the finished video.

export type AspectRatio = "9:16" | "16:9";

export const SHAPES: { value: AspectRatio; label: string; hint: string }[] = [
  { value: "9:16", label: "Upright 9:16", hint: "TikTok, Reels, Shorts" },
  { value: "16:9", label: "Landscape 16:9", hint: "YouTube, TV, desktop" },
];

/** width / height */
export const ratioOf = (shape: AspectRatio | undefined) => (shape === "16:9" ? 16 / 9 : 9 / 16);

/** Where the lettering goes. Sizes are in % of the frame's width; they follow the frame's short side. */
export function lettering(shape: AspectRatio | undefined) {
  const ratio = ratioOf(shape);
  const wide = ratio > 1;
  const scale = Math.min(1, 1 / ratio);
  return { scale, hookTop: wide ? "7%" : "11.5%", captionBottom: wide ? "8%" : "22%" };
}

export const LENGTHS = [15, 20, 30, 45, 60, 75, 90, 120, 150, 180, 240, 300, 420, 600];

/** 45 -> "45s", 90 -> "90s", 150 -> "2 min 30s", 600 -> "10 min" */
export function lengthLabel(seconds: number): string {
  if (seconds <= 90) return `${seconds}s`;
  const rest = seconds % 60;
  return `${Math.floor(seconds / 60)} min${rest ? ` ${rest}s` : ""}`;
}

/** The slider step closest to a length (older jobs may have any number). */
export function lengthStep(seconds: number): number {
  let best = 0;
  LENGTHS.forEach((v, i) => {
    if (Math.abs(v - seconds) < Math.abs(LENGTHS[best] - seconds)) best = i;
  });
  return best;
}

/** CSS that places the source video inside the output frame, the way the renderer crops or fits it. */
export function framingStyle(
  source: number, // width / height of the original
  frame: number, // width / height of the output
  focusX: number,
  whole: boolean,
): Record<string, string | number> {
  const k = source / frame; // how many frames wide the video is when it fills the height
  if (whole) {
    return k >= 1
      ? { position: "absolute", left: 0, width: "100%", top: "50%", transform: "translateY(-50%)" }
      : { position: "absolute", top: 0, height: "100%", left: "50%", transform: "translateX(-50%)", maxWidth: "none" };
  }
  if (k >= 1) {
    const left = -Math.min(Math.max(focusX * k - 0.5, 0), k - 1) * 100;
    return { position: "absolute", top: 0, height: "100%", width: `${k * 100}%`, left: `${left}%`, maxWidth: "none" };
  }
  return { position: "absolute", left: 0, width: "100%", top: "50%", transform: "translateY(-50%)" };
}
