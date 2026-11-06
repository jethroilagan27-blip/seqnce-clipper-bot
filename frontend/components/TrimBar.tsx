"use client";

import {
  contextWindow,
  formatTime,
  niceStep,
  setEdge,
  snapToWords,
  type DraftClip,
} from "@/lib/timeline";
import Filmstrip from "./Filmstrip";

type Props = {
  jobId: string;
  aspect: number;
  clips: DraftClip[];
  index: number;
  duration: number;
  segments: { start: number; end: number; text: string }[];
  /** Word starts/ends (seconds): dragged edges snap to them. */
  boundaries: number[];
  playheadSrc: number | null;
  editable: boolean;
  onChange: (clips: DraftClip[]) => void;
  onSeek: (src: number) => void;
};

const NUDGES = [-1, -0.1, 0.1, 1];

// Trimming one part: a zoomed strip of frames around it (so the scale is readable even for a
// long video), draggable handles, and the sentences near both edges.
export default function TrimBar({ jobId, aspect, clips, index, duration, segments, boundaries, playheadSrc, editable, onChange, onSeek }: Props) {
  const clip = clips[index];
  if (!clip) return null;
  const win = contextWindow(clip, duration);
  const len = win.end - win.start;
  const pos = (t: number) => `${((Math.min(Math.max(t, win.start), win.end) - win.start) / len) * 100}%`;
  const step = niceStep(len);
  const ticks: number[] = [];
  for (let t = Math.ceil(win.start / step) * step; t <= win.end; t += step) ticks.push(t);

  const move = (edge: "start" | "end", t: number) => onChange(setEdge(clips, index, edge, t, duration));
  const timeAt = (from: Element, clientX: number) => {
    const rect = from.closest("[data-trackbar]")?.getBoundingClientRect();
    if (!rect) return win.start;
    return win.start + Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1) * len;
  };
  const tolerance = (from: Element) => {
    const w = from.closest("[data-trackbar]")?.getBoundingClientRect().width ?? 600;
    return (10 / w) * len; // snap to a word when within ~10 px
  };

  const near = segments.filter((s) => s.end > win.start && s.start < win.end);

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <div data-trackbar className="relative h-16 select-none overflow-hidden rounded-lg border border-white/15">
          <Filmstrip jobId={jobId} start={win.start} end={win.end} aspect={aspect} height={64} className="absolute inset-0" />
          <div className="pointer-events-none absolute inset-y-0 left-0 bg-black/70" style={{ width: pos(clip.start) }} />
          <div className="pointer-events-none absolute inset-y-0 right-0 bg-black/70" style={{ left: pos(clip.end) }} />
          <div
            className="pointer-events-none absolute inset-y-0 border-y-2 border-violet-400"
            style={{ left: pos(clip.start), width: `${((clip.end - clip.start) / len) * 100}%` }}
          />
          {playheadSrc !== null && playheadSrc >= win.start && playheadSrc <= win.end && (
            <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-white shadow" style={{ left: pos(playheadSrc) }} />
          )}
          {(["start", "end"] as const).map((edge) => (
            <button
              key={edge}
              role="slider"
              aria-label={`Part ${index + 1} ${edge}`}
              aria-valuemin={0}
              aria-valuemax={duration}
              aria-valuenow={Math.round(clip[edge] * 10) / 10}
              aria-valuetext={formatTime(clip[edge])}
              disabled={!editable}
              title={edge === "start" ? "Drag to change where this part starts" : "Drag to change where this part ends"}
              className="absolute inset-y-0 flex w-6 -translate-x-1/2 cursor-ew-resize items-center justify-center disabled:cursor-default"
              style={{ left: pos(clip[edge]) }}
              onPointerDown={(e) => e.currentTarget.setPointerCapture(e.pointerId)}
              onPointerMove={(e) => {
                if (!e.currentTarget.hasPointerCapture(e.pointerId)) return;
                move(edge, snapToWords(timeAt(e.currentTarget, e.clientX), boundaries, tolerance(e.currentTarget)));
              }}
              onPointerUp={(e) => e.currentTarget.releasePointerCapture(e.pointerId)}
              onKeyDown={(e) => {
                const dir = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
                if (!dir) return;
                e.preventDefault();
                move(edge, clip[edge] + dir * (e.shiftKey ? 1 : 0.1));
              }}
            >
              <span className="flex h-10 w-3 items-center justify-center gap-px rounded-md bg-violet-500 shadow-lg ring-1 ring-white/60">
                <span className="h-4 w-px bg-white/90" />
                <span className="h-4 w-px bg-white/90" />
              </span>
            </button>
          ))}
        </div>
        <div className="relative h-4 text-[10px] text-white/40">
          {ticks.map((t) => (
            <span key={t} className="absolute -translate-x-1/2" style={{ left: pos(t) }}>
              {formatTime(t).replace(/\.0$/, "")}
            </span>
          ))}
        </div>
      </div>

      {editable && (
        <div className="grid gap-2 text-xs text-white/60 sm:grid-cols-2">
          {(["start", "end"] as const).map((edge) => (
            <div key={edge} className="flex flex-wrap items-center gap-1.5 rounded-lg bg-white/[0.03] px-2.5 py-2">
              <span className="w-20 text-white/70">
                {edge === "start" ? "Starts at" : "Ends at"} <span className="tabular-nums text-violet-300">{formatTime(clip[edge])}</span>
              </span>
              {NUDGES.map((d) => (
                <button
                  key={d}
                  onClick={() => move(edge, clip[edge] + d)}
                  aria-label={`Move ${edge === "start" ? "start" : "end"} ${d < 0 ? "earlier" : "later"} by ${Math.abs(d)} second${Math.abs(d) === 1 ? "" : "s"}`}
                  className="rounded border border-white/15 px-1.5 py-0.5 tabular-nums hover:bg-white/10"
                >
                  {d > 0 ? "+" : "−"}
                  {Math.abs(d)}s
                </button>
              ))}
            </div>
          ))}
        </div>
      )}

      <div>
        <p className="mb-1 text-xs text-white/50">
          What&apos;s said here{editable ? " — click a dimmed sentence to include it" : ""}
        </p>
        <ul className="max-h-36 space-y-0.5 overflow-y-auto pr-1 text-sm">
          {near.map((s, i) => {
            const inside = (s.start + s.end) / 2 >= clip.start && (s.start + s.end) / 2 <= clip.end;
            const before = s.end <= clip.start + 0.01;
            return (
              <li key={i}>
                <button
                  disabled={!editable && !inside}
                  onClick={() => {
                    if (inside) onSeek(s.start);
                    else if (editable) move(before ? "start" : "end", before ? s.start : s.end);
                  }}
                  title={inside ? "Play from here" : "Include this sentence"}
                  className={`flex w-full gap-2 rounded px-2 py-1 text-left ${
                    inside ? "text-white/90 hover:bg-violet-500/15" : "text-white/35 hover:bg-white/5"
                  }`}
                >
                  <span className="w-9 shrink-0 text-xs tabular-nums text-violet-300/80">{formatTime(s.start).replace(/\.\d$/, "")}</span>
                  <span className="min-w-0">{s.text.trim()}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
