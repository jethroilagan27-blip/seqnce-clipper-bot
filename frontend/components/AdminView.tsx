"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, getAdminUsers, type AdminOverview } from "@/lib/api";
import type { AccountInfo } from "./AuthGate";
import Shell from "./Shell";

const joined = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
const planName = (plan: string) => plan.charAt(0).toUpperCase() + plan.slice(1);

// The admin page: everyone who has an account. Read-only. The server only answers admins; this page just shows it.
export default function AdminView({ account }: { account: AccountInfo }) {
  const isAdmin = !!account.user?.is_admin;
  const [data, setData] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [attempt, setAttempt] = useState(0); // "Refresh" asks again

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    getAdminUsers()
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Couldn't load the accounts.");
      });
    return () => {
      cancelled = true;
    };
  }, [isAdmin, attempt]);

  const wanted = search.trim().toLowerCase();
  const shown = data?.users.filter((u) => u.email.toLowerCase().includes(wanted)) ?? [];

  return (
    <Shell user={account.user} onSignOut={account.user ? account.signOut : undefined} wide section="admin">
      <div className="space-y-5">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">Accounts</h2>
          <Link href="/" className="text-sm text-violet-300 underline">
            ← Back to editing
          </Link>
        </div>

        {!isAdmin ? (
          <p className="rounded-lg border border-white/10 px-3 py-2 text-sm text-white/60">
            {account.user ? "This page is for the Seqnce team." : "There are no accounts on this computer: this page is for the public site."}
          </p>
        ) : (
          <>
            {data && (
              <dl className="grid grid-cols-3 gap-2">
                {(
                  [
                    ["Accounts", data.totals.accounts],
                    ["New today", data.totals.new_24h],
                    ["New this week", data.totals.new_7d],
                  ] as const
                ).map(([label, value]) => (
                  <div key={label} className="flex flex-col-reverse rounded-xl border border-white/10 bg-white/[0.02] p-3">
                    <dt className="text-xs text-white/55">{label}</dt>
                    <dd className="text-2xl font-semibold">{value}</dd>
                  </div>
                ))}
              </dl>
            )}

            <div className="flex gap-2">
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by email"
                aria-label="Search by email"
                className="min-w-0 flex-1 rounded-lg border border-white/10 bg-field px-3 py-2.5 text-sm placeholder:text-white/30 focus:border-violet-400 focus:outline-none"
              />
              <button type="button" onClick={() => setAttempt((n) => n + 1)} className="rounded-lg border border-white/15 px-4 py-2.5 text-sm text-white/80 hover:bg-white/5">
                Refresh
              </button>
            </div>

            {error && (
              <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                {error}
              </p>
            )}
            {!data && !error && <p className="text-sm text-white/50">Loading…</p>}
            {data && shown.length === 0 && <p className="text-sm text-white/50">No account matches that.</p>}

            <ul className="space-y-2" aria-label="Accounts">
              {shown.map((u) => (
                <li key={u.id} className="rounded-xl border border-white/10 bg-white/[0.02] p-3 sm:flex sm:items-center sm:justify-between sm:gap-4">
                  <div className="min-w-0">
                    <p className="break-all text-sm font-semibold">
                      {u.email}
                      {u.is_admin && <span className="ml-2 rounded-full bg-violet-600 px-2 py-0.5 text-[11px] text-white">Admin</span>}
                      {u.disabled && <span className="ml-2 rounded-full border border-red-400/30 px-2 py-0.5 text-[11px] text-red-300">Disabled</span>}
                    </p>
                    <p className="text-xs text-white/50">Joined {joined(u.created_at)}</p>
                  </div>
                  <p className="mt-2 shrink-0 text-xs text-white/70 sm:mt-0 sm:text-right">
                    {u.is_admin ? "No limits" : `${planName(u.plan)} plan`}
                    <br />
                    Last 24 h: {u.videos_24h} video{u.videos_24h === 1 ? "" : "s"}, {u.chats_24h} AI message{u.chats_24h === 1 ? "" : "s"} · {u.videos_stored} video{u.videos_stored === 1 ? "" : "s"} stored
                  </p>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </Shell>
  );
}
