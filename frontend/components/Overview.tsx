"use client";

import { formatTime, type DraftClip, type Range } from "@/lib/timeline";
import Filmstrip from "./Filmstrip";

type Props = {
  jobId: string;
  duration: number;
  aspect: number;
  clips: DraftClip[];
  /** Parts the previous version had that are gone now (dashed outlines). */
  ghosts?: Range[];
  selected: number | null;
  /** Position of the preview in the ORIGINAL video. */
  playheadSrc: number | null;
  /** True while the AI hasn't chosen anything yet (the bar shimmers). */
  pending?: boolean;
  onSelect?: (index: number) => void;
  onSeek: (src: number) => void;
};

const pct = (t: number, duration: number) => `${(Math.min(Math.max(t, 0), duration) / duration) * 100}%`;

// The whole uploaded video as a strip of frames. Bright = in your short, dimmed = cut out.
// Read-only on purpose: trimming happens on the part cards, where the scale is readable.
export default function Overview({ jobId, duration, aspect, clips, ghosts = [], selected, playheadSrc, pending, onSelect, onSeek }: Props) {
  const sorted = clips.map((c, i) => ({ ...c, i })).sort((a, b) => a.start - b.start);
  // the dimmed stretches between the kept parts
  const gaps: Range[] = [];
  let cursor = 0;
  for (const c of sorted) {
    if (c.start > cursor) gaps.push({ start: cursor, end: c.start });
    cursor = Math.max(cursor, c.end);
  }
  if (cursor < duration) gaps.push({ start: cursor, end: duration });
  const dim = pending || clips.length === 0 ? [{ start: 0, end: duration }] : gaps;

  return (
    <div className="space-y-1.5">
      <div
        className="relative h-14 cursor-pointer overflow-hidden rounded-lg border border-white/10"
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          onSeek(((e.clientX - rect.left) / rect.width) * duration);
        }}
      >
        <Filmstrip jobId={jobId} start={0} end={duration} aspect={aspect} height={56} className="absolute inset-0" />

        {dim.map((g, k) => (
          <div
            key={`dim-${k}`}
            className="pointer-events-none absolute inset-y-0 bg-black/70"
            style={{ left: pct(g.start, duration), width: `${((g.end - g.start) / duration) * 100}%` }}
          />
        ))}
        {pending && <div className="seqnce-shimmer pointer-events-none absolute inset-0" />}

        {ghosts.map((g, k) => (
          <div
            key={`ghost-${k}`}
            title="Removed in this version"
            className="pointer-events-none absolute inset-y-0 border-x border-dashed border-red-400/60"
            style={{ left: pct(g.start, duration), width: `${Math.max(((g.end - g.start) / duration) * 100, 0.3)}%` }}
          />
        ))}

        {sorted.map((c) => (
          <button
            key={`${c.i}-${c.start}`}
            onClick={(e) => {
              e.stopPropagation();
              onSelect?.(c.i);
              onSeek(c.start);
            }}
            aria-label={`Part ${c.i + 1}, ${formatTime(c.start)} to ${formatTime(c.end)}`}
            className={`seqnce-pop absolute inset-y-0 border-y-2 border-violet-400 ${
              selected === c.i ? "border-x-2 border-white shadow-[0_0_0_2px_rgba(255,255,255,0.35)]" : "border-x border-x-violet-300/70"
            }`}
            style={{ left: pct(c.start, duration), width: `${((c.end - c.start) / duration) * 100}%`, minWidth: 14 }}
          >
            <span className="absolute left-1/2 top-1/2 flex h-4 min-w-4 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-violet-600 px-1 text-[10px] font-bold text-white shadow">
              {c.i + 1}
            </span>
          </button>
        ))}

        {playheadSrc !== null && (
          <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-white shadow" style={{ left: pct(playheadSrc, duration) }} />
        )}
      </div>
      <div className="flex justify-between text-[11px] text-white/40">
        <span>0:00</span>
        <span>Your video · {formatTime(duration).replace(/\.\d$/, "")}</span>
      </div>
    </div>
  );
}
