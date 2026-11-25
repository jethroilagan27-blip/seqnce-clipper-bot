"use client";

import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import type { AuthUser, Quota } from "@/lib/api";
import BottomNav from "./BottomNav";

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

export type Section = "video" | "photos" | "studio" | "library" | "me" | "admin";

type Props = {
  user: AuthUser | null;
  onSignOut?: () => void;
  /** true = a wide page; "xl" = the widest (Studio). */
  wide?: boolean | "xl";
  /** Which page is open: lights up its tab. */
  section?: Section;
  /** false = no navigation (the screens before signing in). */
  nav?: boolean;
  children: ReactNode;
};

/** Studio is still rough: say so wherever it is offered. */
export const BetaBadge = () => <span className="rounded-full border border-amber-400/40 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">Beta (Tester)</span>;

// Desktop only: the mode switch ("Edit with video" / "Edit with photos" / "Studio"). On phones the home screen offers the
// modes. Photo mode and Studio are self-contained: to remove one, delete its entry here and on the home screen, plus its
// app/ folder and components/ folder.
function ModeSwitch({ section, studio }: { section: "video" | "photos" | "studio"; studio: boolean }) {
  const tab = (on: boolean) =>
    `flex items-center gap-2 whitespace-nowrap rounded-lg px-4 py-2.5 text-sm ${on ? "bg-violet-600 font-semibold text-white" : "text-white/60 hover:bg-white/5 hover:text-white"}`;
  return (
    <nav aria-label="What do you want to edit?" className="mb-6 hidden gap-1 rounded-xl bg-white/5 p-1 sm:inline-flex">
      <Link href="/" aria-current={section === "video" ? "page" : undefined} className={tab(section === "video")}>
        Edit with video
      </Link>
      <Link href="/photos" aria-current={section === "photos" ? "page" : undefined} className={tab(section === "photos")}>
        Edit with photos
      </Link>
      {studio && (
        <Link href="/studio" aria-current={section === "studio" ? "page" : undefined} className={tab(section === "studio")}>
          Studio <BetaBadge />
        </Link>
      )}
    </nav>
  );
}

/** Accounts without the Studio feature never see it (with no accounts: everyone has it). */
export const hasStudio = (user: AuthUser | null) => (user ? !!user.features?.studio : true);

export default function Shell({ user, onSignOut, wide, section, nav = true, children }: Props) {
  const v = user?.quota.videos;
  const left = v && v.limit !== null ? Math.max(0, v.limit - v.used) : null;
  const editing = section === "video" || section === "photos" || section === "studio";
  const link = (on: boolean) => `underline hover:text-white ${on ? "text-white" : ""}`;
  return (
    <main className={`mx-auto w-full flex-1 px-4 pt-3 sm:px-5 sm:pb-10 sm:pt-10 ${nav ? "pb-28" : "pb-10"} ${wide === "xl" ? "max-w-7xl" : wide ? "max-w-5xl" : "max-w-xl"}`}>
      {/* phone: logo in the corner, the name beside it (the navigation is at the bottom) */}
      <header className="mb-5 flex items-center sm:hidden">
        <Link href="/" className="flex min-w-0 items-center gap-2.5" aria-label="Seqnce home">
          <Image src="/logo.png" alt="" width={40} height={40} priority className="h-10 w-10 shrink-0 rounded-xl" />
          <h1 className="truncate text-xl font-semibold">Seqnce</h1>
        </Link>
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
        {nav && (
          <div className="shrink-0 text-right text-xs text-white/50">
            {user && (
              <p className="ml-auto max-w-[11rem] truncate" title={user.email}>
                {user.email}
              </p>
            )}
            <p>
              {left !== null && (
                <span className={left === 0 ? "text-amber-300" : "text-violet-300"}>
                  {left} of {v!.limit} video{v!.limit === 1 ? "" : "s"} left ·{" "}
                </span>
              )}
              <Link href="/library" className={link(section === "library")}>
                Library
              </Link>
              {" · "}
              <Link href="/me" className={link(section === "me")}>
                Me
              </Link>
              {user?.is_admin && (
                <>
                  {" · "}
                  <Link href="/admin" className={link(section === "admin")}>
                    Admin
                  </Link>
                </>
              )}
              {user && onSignOut && (
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
      {editing && user?.ai?.mode === "own" && !user.ai.has_key && (
        <Link href="/me" className="mb-5 block rounded-xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-100 hover:bg-amber-400/15">
          Add your Gemini key under Me to turn the AI on. Until then videos get a basic cut and the chat can&apos;t answer. →
        </Link>
      )}
      {editing && <ModeSwitch section={section} studio={hasStudio(user)} />}
      {section === "studio" && (
        <p className="mb-4 flex items-center gap-2 text-sm text-white/55 sm:hidden">
          Studio <BetaBadge />
        </p>
      )}
      {children}
      {nav && <BottomNav section={section} />}
    </main>
  );
}
