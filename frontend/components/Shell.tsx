"use client";

import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import type { AuthUser, Quota } from "@/lib/api";

/** "in about 3 hours" style wait until a quota unit frees up. */
export function waitPhrase(resetsAt: string | null): string {
  if (!resetsAt) return "later";
  const minutes = Math.max(1, Math.round((new Date(resetsAt).getTime() - Date.now()) / 60000));
  if (minutes < 90) return `in about ${minutes} minute${minutes === 1 ? "" : "s"}`;
  return `in about ${Math.round(minutes / 60)} hours`;
}

/** Why the user can't do this right now, or null when they still have some left. */
export function quotaBlock(q: Quota | undefined, singular: string, plural: string): string | null {
  if (!q || q.limit === null || q.used < q.limit) return null;
  return `You've used your ${q.limit} ${q.limit === 1 ? singular : plural} for the last 24 hours. More free up ${waitPhrase(q.resets_at)}.`;
}

type Props = {
  user: AuthUser | null;
  onSignOut?: () => void;
  /** true = a wide page; "xl" = the widest (Studio). */
  wide?: boolean | "xl";
  /** Which mode is open; shows the mode switch. */
  section?: "video" | "photos" | "studio";
  children: ReactNode;
};

// The mode switch ("Edit with video" / "Edit with photos" / "Studio"). Photo mode and Studio are self-contained: to
// remove one, delete its tab below, plus its app/ folder and components/ folder.
function ModeSwitch({ section, studio }: { section: "video" | "photos" | "studio"; studio: boolean }) {
  const tab = (on: boolean) =>
    `rounded-lg px-4 py-2 text-sm ${on ? "bg-violet-600 font-semibold text-white" : "text-white/60 hover:bg-white/5 hover:text-white"}`;
  return (
    <nav aria-label="What do you want to edit?" className="mb-6 inline-flex gap-1 rounded-xl bg-white/5 p-1">
      <Link href="/" aria-current={section === "video" ? "page" : undefined} className={tab(section === "video")}>
        Edit with video
      </Link>
      <Link href="/photos" aria-current={section === "photos" ? "page" : undefined} className={tab(section === "photos")}>
        Edit with photos
      </Link>
      {studio && (
        <Link href="/studio" aria-current={section === "studio" ? "page" : undefined} className={tab(section === "studio")}>
          Studio
        </Link>
      )}
    </nav>
  );
}

export default function Shell({ user, onSignOut, wide, section, children }: Props) {
  const v = user?.quota.videos;
  const left = v && v.limit !== null ? Math.max(0, v.limit - v.used) : null;
  const showStudio = user ? !!user.features?.studio : true; // accounts without the Studio feature never see the tab (with no accounts: everyone has it)
  return (
    <main className={`mx-auto w-full flex-1 px-5 py-10 ${wide === "xl" ? "max-w-7xl" : wide ? "max-w-5xl" : "max-w-xl"}`}>
      <header className="mb-8 flex items-center gap-3">
        <Image src="/logo.png" alt="" width={40} height={40} priority className="h-10 w-10 shrink-0 rounded-xl" />
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold leading-tight">Seqnce</h1>
          <p className="text-sm text-white/50">Turn raw footage into a ready-to-post short.</p>
        </div>
        {user && (
          <div className="shrink-0 text-right text-xs text-white/50">
            <p className="max-w-[11rem] truncate" title={user.email}>
              {user.email}
            </p>
            <p>
              {left !== null && (
                <span className={left === 0 ? "text-amber-300" : "text-violet-300"}>
                  {left} of {v!.limit} video{v!.limit === 1 ? "" : "s"} left ·{" "}
                </span>
              )}
              {onSignOut && (
                <button onClick={onSignOut} className="underline hover:text-white">
                  Sign out
                </button>
              )}
            </p>
          </div>
        )}
      </header>
      {section && <ModeSwitch section={section} studio={showStudio} />}
      {children}
    </main>
  );
}
