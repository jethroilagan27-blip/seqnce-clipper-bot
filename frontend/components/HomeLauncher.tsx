"use client";

import Link from "next/link";
import { useRef, type ReactNode } from "react";
import { fromFileList, type Picked } from "@/lib/pickFiles";
import { BetaBadge } from "./Shell";

type Props = {
  /** The videos chosen after tapping "+ New video" or "Highlight video". */
  onPick: (items: Picked[], style: "talking" | "highlight") => void;
  studio: boolean;
  /** Set when the daily limit is used up: "+ New video" is off and this says why. */
  blockedReason?: string | null;
  error?: string | null;
};

const MODE_CLASS = "flex w-full items-center gap-4 rounded-2xl border border-white/10 bg-white/[0.04] p-4 text-left hover:bg-white/[0.07] disabled:cursor-not-allowed disabled:opacity-40";

function ModeBody({ title, hint, badge, icon }: { title: string; hint: string; badge?: ReactNode; icon: ReactNode }) {
  return (
    <>
      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-white/[0.07]">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          {icon}
        </svg>
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2 font-semibold">
          {title} {badge}
        </span>
        <span className="block text-xs text-white/50">{hint}</span>
      </span>
      <span aria-hidden="true" className="text-white/40">
        ›
      </span>
    </>
  );
}

function Mode({ href, ...body }: { href: string; title: string; hint: string; badge?: ReactNode; icon: ReactNode }) {
  return (
    <Link href={href} className={MODE_CLASS}>
      <ModeBody {...body} />
    </Link>
  );
}

// The phone's start screen, in the style of CapCut: one big "+ New video", then the other ways to make a video.
export default function HomeLauncher({ onPick, studio, blockedReason, error }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const style = useRef<"talking" | "highlight">("talking"); // which button opened the file picker
  const open = (kind: "talking" | "highlight") => {
    style.current = kind;
    input.current?.click();
  };
  return (
    <div className="space-y-4">
      <input
        ref={input}
        type="file"
        multiple
        accept="video/*,.mov,.mkv,.m4v,.webm,.mp4"
        className="hidden"
        data-testid="new-video-input"
        onChange={(e) => {
          const items = fromFileList(e.target.files ?? []);
          e.target.value = "";
          if (items.length) onPick(items, style.current);
        }}
      />
      <button
        type="button"
        disabled={!!blockedReason}
        onClick={() => open("talking")}
        className="flex w-full flex-col items-center justify-center gap-2 rounded-3xl bg-violet-600 px-6 py-12 hover:bg-violet-500 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-white/40"
      >
        <span aria-hidden="true" className="flex h-14 w-14 items-center justify-center rounded-full border-2 border-current text-4xl font-light leading-none">
          +
        </span>
        <span className="text-xl font-semibold">New video</span>
        <span className="text-xs opacity-80">Choose the videos to edit</span>
      </button>

      {blockedReason && (
        <p role="status" className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
          {blockedReason}
        </p>
      )}
      {error && (
        <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </p>
      )}

      <button type="button" disabled={!!blockedReason} onClick={() => open("highlight")} className={MODE_CLASS}>
        <ModeBody
          title="Highlight video"
          badge={<span className="rounded-full border border-violet-400/60 px-1.5 py-0.5 text-[10px] font-semibold text-violet-300">New</span>}
          hint="The best moments, no talking needed"
          icon={<path d="m12 3 2.6 5.6 6.1.7-4.5 4.2 1.2 6L12 16.500 6.600 19.500l1.2-6-4.500-4.200 6.100-.7z" />}
        />
      </button>

      <Mode
        href="/photos"
        title="Edit with photos"
        hint="Turn your photos into a video with music"
        icon={
          <>
            <rect x="3" y="4" width="18" height="16" rx="3" />
            <circle cx="8.5" cy="9.500" r="1.500" />
            <path d="m21 16-5-5-9 9" />
          </>
        }
      />
      {studio && (
        <Mode
          href="/studio"
          title="Studio"
          badge={<BetaBadge />}
          hint="Longer, scripted videos. Still being tested: check the results."
          icon={
            <>
              <rect x="3" y="8" width="18" height="12" rx="2" />
              <path d="m3 8 2-4 4 .8L7 8m6-2.4 4 .8L15 8" />
            </>
          }
        />
      )}
    </div>
  );
}
