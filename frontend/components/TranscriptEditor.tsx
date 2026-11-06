"use client";

import { useEffect, useRef } from "react";
import { isKept, formatTime, type Range } from "@/lib/timeline";

type Props = {
  segments: { start: number; end: number; text: string }[];
  clips: Range[];
  /** Position of the preview in the ORIGINAL video, to highlight the sentence being played. */
  playheadSrc: number | null;
  editable: boolean;
  onToggle: (segment: Range) => void;
  onSeek: (src: number) => void;
};

// Edit by reading: click a sentence to cut it out of the video, click again to put it back.
export default function TranscriptEditor({ segments, clips, playheadSrc, editable, onToggle, onSeek }: Props) {
  const activeRef = useRef<HTMLLIElement | null>(null);
  const active = playheadSrc === null ? -1 : segments.findIndex((s) => playheadSrc >= s.start && playheadSrc < s.end);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!segments.length) return <p className="text-sm text-white/40">No transcript yet…</p>;

  return (
    <ul className="max-h-72 space-y-1 overflow-y-auto pr-1 text-sm" aria-label="Transcript">
      {segments.map((s, i) => {
        const kept = isKept(clips, s);
        return (
          <li key={i} ref={i === active ? activeRef : null} className="flex items-start gap-2">
            <button
              onClick={() => onSeek(s.start)}
              className="mt-0.5 w-11 shrink-0 text-left text-xs tabular-nums text-violet-300 hover:underline"
              title="Play from here"
            >
              {formatTime(s.start).replace(/\.\d$/, "")}
            </button>
            <button
              disabled={!editable}
              onClick={() => onToggle(s)}
              aria-pressed={kept}
              title={editable ? (kept ? "Click to cut this out" : "Click to add this back") : undefined}
              className={`min-w-0 flex-1 rounded-md px-2 py-1 text-left transition ${
                kept
                  ? "bg-violet-500/15 text-white/90 hover:bg-violet-500/25"
                  : "text-white/35 line-through decoration-white/20 hover:bg-white/5"
              } ${i === active ? "ring-1 ring-white/60" : ""} disabled:cursor-default`}
            >
              {s.text.trim()}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
