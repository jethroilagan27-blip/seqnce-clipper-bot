"use client";

import { useEffect, useRef, useState } from "react";
import { MAX_FIX_CHARS, captionText, fixFor, setFix, type CaptionFix } from "@/lib/captionFixes";
import { isKept, formatTime, type Range } from "@/lib/timeline";

type Sentence = { start: number; end: number; text: string };

type Props = {
  segments: Sentence[];
  clips: Range[];
  /** Position of the preview in the ORIGINAL video, to highlight the sentence being played. */
  playheadSrc: number | null;
  editable: boolean;
  onToggle: (segment: Range) => void;
  onSeek: (src: number) => void;
  /** The user's caption corrections, and where to send changes. */
  fixes: CaptionFix[];
  onFix: (fixes: CaptionFix[]) => void;
};

// Edit by reading: click a sentence to cut it out of the video, click again to put it back. The pencil corrects what
// the captions say (a misheard name, a wrong word) without cutting anything.
export default function TranscriptEditor({ segments, clips, playheadSrc, editable, onToggle, onSeek, fixes, onFix }: Props) {
  const activeRef = useRef<HTMLLIElement | null>(null);
  const [editing, setEditing] = useState<{ start: number; text: string } | null>(null);
  const active = playheadSrc === null ? -1 : segments.findIndex((s) => playheadSrc >= s.start && playheadSrc < s.end);

  useEffect(() => {
    if (!editing) activeRef.current?.scrollIntoView({ block: "nearest" });
  }, [active, editing]);

  if (!segments.length) return <p className="text-sm text-white/40">No transcript yet…</p>;

  const save = (s: Sentence, text: string) => {
    onFix(setFix(fixes, s, text));
    setEditing(null);
  };

  return (
    <ul className="max-h-96 space-y-1 overflow-y-auto pr-1 text-sm" aria-label="Transcript">
      {segments.map((s, i) => {
        const kept = isKept(clips, s);
        const fixed = fixFor(fixes, s);
        const shown = captionText(fixes, s);
        return (
          <li key={s.start} ref={i === active ? activeRef : null} className="flex items-start gap-2">
            <button
              onClick={() => onSeek(s.start)}
              className="mt-0.5 w-11 shrink-0 py-1 text-left text-xs tabular-nums text-violet-300 hover:underline"
              title="Play from here"
            >
              {formatTime(s.start).replace(/\.\d$/, "")}
            </button>
            {editing?.start === s.start ? (
              <div className="min-w-0 flex-1 space-y-2 rounded-md border border-violet-400/60 p-2">
                <textarea
                  autoFocus
                  rows={3}
                  maxLength={MAX_FIX_CHARS}
                  value={editing.text}
                  onChange={(e) => setEditing({ start: s.start, text: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") setEditing(null);
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      save(s, editing.text);
                    }
                  }}
                  aria-label="Caption text"
                  className="w-full rounded-md border border-white/10 bg-field px-2 py-1.5 text-sm focus:border-violet-400 focus:outline-none"
                />
                <p className="text-xs text-white/40">Fix the words as they should appear. Leave it empty to show no caption here.</p>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={() => save(s, editing.text)} className="rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white">
                    Done
                  </button>
                  <button type="button" onClick={() => setEditing(null)} className="rounded-lg border border-white/15 px-3 py-1.5 text-xs">
                    Cancel
                  </button>
                  {fixed && (
                    <button type="button" onClick={() => save(s, s.text)} className="rounded-lg border border-white/15 px-3 py-1.5 text-xs">
                      Use what was heard
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <>
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
                  {shown || <span className="italic text-white/40">(no caption)</span>}
                  {fixed && <span className="ml-1.5 whitespace-nowrap text-[10px] font-semibold uppercase text-emerald-300">edited</span>}
                </button>
                {editable && (
                  <button
                    type="button"
                    onClick={() => setEditing({ start: s.start, text: shown })}
                    aria-label={`Correct the caption at ${formatTime(s.start).replace(/\.\d$/, "")}`}
                    title="Correct the caption"
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-white/10 text-white/60 hover:bg-white/5 hover:text-white"
                  >
                    ✎
                  </button>
                )}
              </>
            )}
          </li>
        );
      })}
    </ul>
  );
}
