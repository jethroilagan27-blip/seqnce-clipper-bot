"use client";

import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import type { AuthUser, Quota } from "@/lib/api";
import MobileMenu from "./MobileMenu";

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
    `flex-1 whitespace-nowrap rounded-lg px-2 py-2.5 text-center text-[13px] sm:flex-none sm:px-4 sm:text-sm ${on ? "bg-violet-600 font-semibold text-white" : "text-white/60 hover:bg-white/5 hover:text-white"}`;
  return (
    <nav aria-label="What do you want to edit?" className="mb-6 flex w-full gap-1 rounded-xl bg-white/5 p-1 sm:inline-flex sm:w-auto">
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
    <main className={`mx-auto w-full flex-1 px-4 pb-10 pt-3 sm:px-5 sm:pt-10 ${wide === "xl" ? "max-w-7xl" : wide ? "max-w-5xl" : "max-w-xl"}`}>
      {/* phone: logo in the corner, the name beside it, the menu on the right */}
      <header className="mb-5 flex items-center gap-3 sm:hidden">
        <Link href="/" className="flex min-w-0 flex-1 items-center gap-2.5" aria-label="Seqnce home">
          <Image src="/logo.png" alt="" width={40} height={40} priority className="h-10 w-10 shrink-0 rounded-xl" />
          <h1 className="truncate text-xl font-semibold">Seqnce</h1>
        </Link>
        <MobileMenu user={user} onSignOut={onSignOut} />
      </header>
      {/* wider screens */}
      <header className="mb-8 hidden flex-wrap items-center gap-x-3 gap-y-2 sm:flex">
        <Link href="/" className="flex min-w-0 flex-1 basis-56 items-center gap-3" aria-label="Seqnce home">
          <Image src="/logo.png" alt="" width={40} height={40} priority className="h-10 w-10 shrink-0 rounded-xl" />
          <div className="min-w-0">
            <h1 className="text-xl font-semibold leading-tight">Seqnce</h1>
            <p className="text-sm text-white/50">Turn raw footage into a ready-to-post short.</p>
          </div>
        </Link>
        {user && (
          <div className="w-full shrink-0 text-xs text-white/50 sm:w-auto sm:text-right">
            <p className="truncate sm:max-w-[11rem]" title={user.email}>
              {user.email}
            </p>
            <p>
              {left !== null && (
                <span className={left === 0 ? "text-amber-300" : "text-violet-300"}>
                  {left} of {v!.limit} video{v!.limit === 1 ? "" : "s"} left ·{" "}
                </span>
              )}
              {user.is_admin && (
                <>
                  <Link href="/admin" className="underline hover:text-white">
                    Admin
                  </Link>
                  {" · "}
                </>
              )}
              <Link href="/settings" className="underline hover:text-white">
                Settings
              </Link>
              {onSignOut && (
                <>
                  {" · "}
                  <button onClick={onSignOut} className="underline hover:text-white">
                    Sign out
                  </button>
                </>
              )}
            </p>
          </div>
        )}
      </header>
      {section && user?.ai?.mode === "own" && !user.ai.has_key && (
        <Link href="/settings" className="mb-5 block rounded-xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-100 hover:bg-amber-400/15">
          Add your Gemini key in Settings to turn the AI on. Until then videos get a basic cut and the chat can&apos;t answer. →
        </Link>
      )}
      {section && <ModeSwitch section={section} studio={showStudio} />}
      {children}
    </main>
  );
}
