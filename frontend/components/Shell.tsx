"use client";

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
  wide?: boolean;
  children: ReactNode;
};

export default function Shell({ user, onSignOut, wide, children }: Props) {
  const v = user?.quota.videos;
  const left = v && v.limit !== null ? Math.max(0, v.limit - v.used) : null;
  return (
    <main className={`mx-auto w-full flex-1 px-5 py-10 ${wide ? "max-w-5xl" : "max-w-xl"}`}>
      <header className="mb-8 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-500 text-lg font-bold">
          S
        </div>
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
      {children}
    </main>
  );
}
