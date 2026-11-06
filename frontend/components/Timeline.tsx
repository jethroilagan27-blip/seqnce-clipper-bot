"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { formatTime, rulerStep, setEdge, snapToWords, type DraftClip, type Range } from "@/lib/timeline";

type Props = {
  duration: number;
  clips: DraftClip[];
  segments: { start: number; end: number; text: string }[];
  /** Word starts/ends (seconds): dragged edges snap to them. */
  boundaries: number[];
  /** Position of the preview in the ORIGINAL video. */
  playheadSrc: number | null;
  editable: boolean;
  /** Clips the previous version had that are gone now (drawn as dashed ghosts). */
  removed?: Range[];
  /** "added" / "trimmed" for clips that changed in this version (colours the block). */
  statusFor?: (c: DraftClip) => string | undefined;
  onChange: (clips: DraftClip[]) => void;
  onSeek: (src: number) => void;
};

const STATUS_CLS: Record<string, string> = {
  added: "border-emerald-400 bg-emerald-500/35",
  trimmed: "border-amber-300 bg-amber-400/30",
};

export default function Timeline({
  duration,
  clips,
  segments,
  boundaries,
  playheadSrc,
  editable,
  removed = [],
  statusFor,
  onChange,
  onSeek,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [viewW, setViewW] = useState(600);
  const [zoom, setZoom] = useState(1);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setViewW(Math.max(el.clientWidth, 200)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const pxPerSec = (viewW / Math.max(duration, 1)) * zoom;
  const trackW = Math.max(duration * pxPerSec, viewW);
  const step = rulerStep(pxPerSec);
  const ticks = useMemo(() => {
    const out: number[] = [];
    for (let t = 0; t <= duration; t += step) out.push(t);
    return out;
  }, [duration, step]);

  // Keep the playhead in view while the preview plays on a zoomed-in timeline.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || playheadSrc === null || zoom <= 1) return;
    const x = playheadSrc * pxPerSec;
    if (x < el.scrollLeft + 20 || x > el.scrollLeft + el.clientWidth - 20) el.scrollLeft = Math.max(0, x - el.clientWidth / 3);
  }, [playheadSrc, pxPerSec, zoom]);

  // Time under the pointer, measured against the track element that contains `from`.
  function timeAt(from: Element, clientX: number): number {
    const rect = from.closest("[data-track]")?.getBoundingClientRect();
    if (!rect) return 0;
    return Math.min(Math.max((clientX - rect.left) / pxPerSec, 0), duration);
  }

  function moveEdge(index: number, edge: "start" | "end", t: number) {
    onChange(setEdge(clips, index, edge, t, duration));
  }

  const sel = selected !== null ? clips[selected] : undefined;
  const nudge = (edge: "start" | "end", delta: number) =>
    selected !== null && sel && moveEdge(selected, edge, sel[edge] + delta);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3 text-xs text-white/50">
        <span>
          {clips.length} clip{clips.length === 1 ? "" : "s"} ·{" "}
          {formatTime(clips.reduce((a, c) => a + (c.end - c.start), 0))} kept of {formatTime(duration)}
        </span>
        <label className="flex items-center gap-2">
          Zoom
          <input
            type="range"
            min={1}
            max={24}
            step={0.5}
            value={zoom}
            onChange={(e) => setZoom(Number(e.target.value))}
            aria-label="Timeline zoom"
            className="w-28 accent-violet-500"
          />
        </label>
      </div>

      <div ref={scrollRef} className="overflow-x-auto rounded-lg border border-white/10 bg-[#101016]">
        <div
          data-track
          className="relative h-[116px] select-none"
          style={{ width: trackW }}
          onClick={(e) => onSeek(timeAt(e.currentTarget, e.clientX))}
        >
          {/* ruler */}
          {ticks.map((t) => (
            <div key={t} className="absolute top-0 h-5 border-l border-white/15 pl-1 text-[10px] text-white/40" style={{ left: t * pxPerSec }}>
              {formatTime(t).replace(/\.0$/, "")}
            </div>
          ))}

          {/* what was said (thin strip) */}
          <div className="absolute inset-x-0 top-6 h-2">
            {segments.map((s, i) => (
              <div
                key={i}
                title={s.text}
                className="absolute h-full rounded-sm bg-white/15"
                style={{ left: s.start * pxPerSec, width: Math.max((s.end - s.start) * pxPerSec - 1, 1) }}
              />
            ))}
          </div>

          {/* clips removed compared with the previous version */}
          {removed.map((r, i) => (
            <div
              key={`ghost-${i}`}
              title="Removed in this version"
              className="pointer-events-none absolute top-10 h-[60px] rounded-md border border-dashed border-red-400/50 bg-red-500/5"
              style={{ left: r.start * pxPerSec, width: Math.max((r.end - r.start) * pxPerSec, 2) }}
            />
          ))}

          {/* the kept clips */}
          {clips.map((c, i) => {
            const status = statusFor?.(c);
            const isSel = selected === i;
            return (
              <div
                key={`${i}-${c.start}`}
                onClick={(e) => {
                  e.stopPropagation();
                  setSelected(i);
                  onSeek(timeAt(e.currentTarget, e.clientX));
                }}
                className={`absolute top-10 h-[60px] cursor-pointer rounded-md border-2 px-2 py-1 text-[11px] leading-tight ${
                  (status && STATUS_CLS[status]) || "border-violet-400/70 bg-violet-500/30"
                } ${isSel ? "ring-2 ring-white/70" : ""}`}
                style={{ left: c.start * pxPerSec, width: Math.max((c.end - c.start) * pxPerSec, 8) }}
              >
                <span className="pointer-events-none block truncate font-medium text-white/90">
                  {c.purpose.replace("_", " ")}
                </span>
                <span className="pointer-events-none block truncate text-white/60">
                  {formatTime(c.end - c.start)}
                </span>
                {editable &&
                  (["start", "end"] as const).map((edge) => (
                    <button
                      key={edge}
                      role="slider"
                      aria-label={`Clip ${i + 1} ${edge}`}
                      aria-valuemin={0}
                      aria-valuemax={duration}
                      aria-valuenow={Math.round(c[edge] * 10) / 10}
                      title={`Drag to trim the ${edge} (arrow keys: 0.1 s, with Shift: 1 s)`}
                      className={`absolute top-0 h-full w-3 cursor-ew-resize bg-white/60 hover:bg-white ${
                        edge === "start" ? "-left-0.5 rounded-l-md" : "-right-0.5 rounded-r-md"
                      }`}
                      onClick={(e) => e.stopPropagation()}
                      onPointerDown={(e) => {
                        e.stopPropagation();
                        e.currentTarget.setPointerCapture(e.pointerId);
                        setSelected(i);
                      }}
                      onPointerMove={(e) => {
                        if (!e.currentTarget.hasPointerCapture(e.pointerId)) return; // not dragging
                        moveEdge(i, edge, snapToWords(timeAt(e.currentTarget, e.clientX), boundaries, 8 / pxPerSec));
                      }}
                      onPointerUp={(e) => {
                        e.currentTarget.releasePointerCapture(e.pointerId);
                      }}
                      onKeyDown={(e) => {
                        const dir = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
                        if (!dir) return;
                        e.preventDefault();
                        moveEdge(i, edge, c[edge] + dir * (e.shiftKey ? 1 : 0.1));
                      }}
                    />
                  ))}
              </div>
            );
          })}

          {/* playhead */}
          {playheadSrc !== null && (
            <div
              className="pointer-events-none absolute top-0 h-full w-px bg-white"
              style={{ left: playheadSrc * pxPerSec }}
            >
              <div className="absolute -left-1 top-0 h-2 w-2 rotate-45 bg-white" />
            </div>
          )}
        </div>
      </div>

      {editable && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-white/60">
          {sel ? (
            <>
              <span className="font-medium text-white/80">Clip {selected! + 1}</span>
              {(["start", "end"] as const).map((edge) => (
                <span key={edge} className="flex items-center gap-1.5">
                  {edge} <span className="tabular-nums text-violet-300">{formatTime(sel[edge])}</span>
                  <button onClick={() => nudge(edge, -0.1)} aria-label={`Move ${edge} earlier by 0.1 seconds`} className="rounded border border-white/15 px-1.5 hover:bg-white/10">−0.1</button>
                  <button onClick={() => nudge(edge, 0.1)} aria-label={`Move ${edge} later by 0.1 seconds`} className="rounded border border-white/15 px-1.5 hover:bg-white/10">+0.1</button>
                </span>
              ))}
            </>
          ) : (
            <span>Drag a clip&apos;s white edge to trim it, or click a clip to nudge it. Edges snap to words.</span>
          )}
        </div>
      )}
    </div>
  );
}
