"use client";

import { useEffect, useRef } from "react";
import { PURPOSE_LABEL, formatTime, snippetFor, type DraftClip } from "@/lib/timeline";
import Filmstrip from "./Filmstrip";
import TrimBar from "./TrimBar";

type Props = {
  jobId: string;
  aspect: number;
  duration: number;
  clips: DraftClip[];
  segments: { start: number; end: number; text: string }[];
  boundaries: number[];
  selected: number | null;
  playheadSrc: number | null;
  editable: boolean;
  onSelect: (index: number | null) => void;
  onChange: (clips: DraftClip[]) => void;
  onSeek: (src: number) => void;
};

// The short as a list of numbered parts: what each one is, what is said in it, and (when opened) a
// zoomed trim bar. Much easier to read than blocks on a timeline of the whole video.
export default function PartsPanel({ jobId, aspect, duration, clips, segments, boundaries, selected, playheadSrc, editable, onSelect, onChange, onSeek }: Props) {
  const openRef = useRef<HTMLLIElement | null>(null);
  useEffect(() => {
    openRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selected]);

  const total = clips.reduce((a, c) => a + (c.end - c.start), 0);
  return (
    <div className="space-y-3">
      <p className="text-sm text-white/60">
        Your short has <span className="font-medium text-white">{clips.length} part{clips.length === 1 ? "" : "s"}</span> ({formatTime(total).replace(/\.\d$/, "")} in total), played in this order.
        {editable && " Open a part to trim it, or remove the ones you don't want."}
      </p>
      <ol className="space-y-2">
        {clips.map((c, i) => {
          const open = selected === i;
          return (
            <li
              key={`${i}-${c.start}`}
              ref={open ? openRef : null}
              className={`rounded-xl border transition ${open ? "border-violet-400/70 bg-violet-500/[0.06]" : "border-white/10 bg-white/[0.02]"}`}
            >
              <div className="flex items-center gap-3 p-2.5">
                <div className="relative w-28 shrink-0 overflow-hidden rounded-lg border border-white/10">
                  <Filmstrip jobId={jobId} start={c.start} end={c.end} aspect={aspect} height={64} />
                  <span className="absolute left-1.5 top-1.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-violet-600 px-1 text-xs font-bold shadow">
                    {i + 1}
                  </span>
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">
                    {PURPOSE_LABEL[c.purpose]}
                    <span className="ml-2 text-xs font-normal tabular-nums text-white/50">
                      {formatTime(c.start).replace(/\.\d$/, "")} → {formatTime(c.end).replace(/\.\d$/, "")} · {Math.round(c.end - c.start)}s
                    </span>
                  </p>
                  <p className="line-clamp-2 text-xs text-white/55">{snippetFor(segments, c) || c.reason || "…"}</p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1 sm:flex-row">
                  <button
                    onClick={() => onSeek(c.start)}
                    className="rounded-md border border-white/15 px-2.5 py-1 text-xs hover:bg-white/10"
                    aria-label={`Play part ${i + 1}`}
                  >
                    ▶ Play
                  </button>
                  <button
                    onClick={() => onSelect(open ? null : i)}
                    aria-expanded={open}
                    className={`rounded-md border px-2.5 py-1 text-xs ${open ? "border-violet-400 bg-violet-500/20" : "border-white/15 hover:bg-white/10"}`}
                  >
                    {editable ? (open ? "Done" : "Trim") : open ? "Hide" : "Details"}
                  </button>
                  {editable && (
                    <button
                      disabled={clips.length <= 1}
                      onClick={() => {
                        onChange(clips.filter((_, k) => k !== i));
                        onSelect(null);
                      }}
                      title={clips.length <= 1 ? "At least one part has to stay" : "Take this part out of your short"}
                      aria-label={`Remove part ${i + 1}`}
                      className="rounded-md border border-red-400/30 px-2.5 py-1 text-xs text-red-300 hover:bg-red-500/10 disabled:opacity-30"
                    >
                      Remove
                    </button>
                  )}
                </div>
              </div>
              {open && (
                <div className="border-t border-white/10 p-3">
                  <TrimBar
                    jobId={jobId}
                    aspect={aspect}
                    clips={clips}
                    index={i}
                    duration={duration}
                    segments={segments}
                    boundaries={boundaries}
                    playheadSrc={playheadSrc}
                    editable={editable}
                    onChange={onChange}
                    onSeek={onSeek}
                  />
                </div>
              )}
            </li>
          );
        })}
      </ol>
      {editable && (
        <p className="text-xs text-white/40">
          Want to add a moment that isn&apos;t here? Open the <span className="text-white/60">Transcript</span> tab and click the sentences you want.
        </p>
      )}
    </div>
  );
}
