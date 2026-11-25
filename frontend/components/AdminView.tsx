"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ApiError,
  changeAccount,
  getAdminStats,
  getAdminUsers,
  type AccountChange,
  type AdminAccount,
  type AdminOverview,
  type AdminStats,
} from "@/lib/api";
import { NO_USE, aiRequests, edits, parseLimit, type Counts } from "@/lib/usage";
import type { AccountInfo } from "./AuthGate";
import Shell from "./Shell";
import UsageChart from "./UsageChart";

const joined = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
const planName = (plan: string) => plan.charAt(0).toUpperCase() + plan.slice(1);
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const message = (e: unknown, otherwise: string) => (e instanceof ApiError ? e.message : otherwise);

const RANGES = [7, 30, 90] as const;
const field = "w-full rounded-lg border border-white/10 bg-field px-3 py-2 text-sm placeholder:text-white/30 focus:border-violet-400 focus:outline-none";
const choice = (on: boolean) =>
  `rounded-lg border px-3 py-1.5 text-xs ${on ? "border-violet-400 bg-violet-500/15 font-semibold" : "border-white/15 text-white/70 hover:bg-white/5"}`;

// The admin page: usage over time, everyone who has an account, and what each of them may do. The server only answers
// admins; this page just shows it and sends the changes.
export default function AdminView({ account }: { account: AccountInfo }) {
  const isAdmin = !!account.user?.is_admin;
  const [data, setData] = useState<AdminOverview | null>(null);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [days, setDays] = useState<(typeof RANGES)[number]>(30);
  const [only, setOnly] = useState<number | null>(null); // graph one account; null = everyone
  const [editing, setEditing] = useState<number | null>(null);
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
      .catch((e) => !cancelled && setError(message(e, "Couldn't load the accounts.")));
    return () => {
      cancelled = true;
    };
  }, [isAdmin, attempt]);

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    getAdminStats(days, only)
      .then((s) => {
        if (cancelled) return;
        setStats(s);
        setStatsError(null);
      })
      .catch((e) => !cancelled && setStatsError(message(e, "Couldn't load the usage figures.")));
    return () => {
      cancelled = true;
    };
  }, [isAdmin, days, only, attempt]);

  const wanted = search.trim().toLowerCase();
  const shown = data?.users.filter((u) => u.email.toLowerCase().includes(wanted)) ?? [];
  const usageFor = (id: number): Counts => stats?.per_user.find((u) => u.user_id === id) ?? NO_USE;

  return (
    <Shell user={account.user} onSignOut={account.user ? account.signOut : undefined} wide section="admin">
      <div className="space-y-6">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">Admin</h2>
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
            <section aria-labelledby="usage-title" className="space-y-3">
              <h3 id="usage-title" className="font-medium">
                Usage
              </h3>
              <div className="flex flex-wrap items-center gap-2">
                <div role="group" aria-label="Time range" className="flex gap-1">
                  {RANGES.map((r) => (
                    <button key={r} type="button" aria-pressed={days === r} onClick={() => setDays(r)} className={choice(days === r)}>
                      {r} days
                    </button>
                  ))}
                </div>
                <select
                  value={only ?? ""}
                  onChange={(e) => setOnly(e.target.value ? Number(e.target.value) : null)}
                  aria-label="Whose usage"
                  className="min-w-0 flex-1 rounded-lg border border-white/10 bg-field px-3 py-1.5 text-xs"
                >
                  <option value="">Everyone</option>
                  {data?.users.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.email}
                    </option>
                  ))}
                </select>
              </div>
              {statsError && (
                <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                  {statsError}
                </p>
              )}
              {stats && (
                <div className="space-y-3 rounded-xl border border-white/10 p-3">
                  <dl className="grid grid-cols-2 gap-3">
                    <div className="flex flex-col-reverse">
                      <dt className="text-xs text-white/55">
                        Video edits ({stats.totals.videos} new, {plural(stats.totals.changes, "change")})
                      </dt>
                      <dd className="text-2xl font-semibold">{edits(stats.totals)}</dd>
                    </div>
                    <div className="flex flex-col-reverse">
                      <dt className="text-xs text-white/55">
                        AI requests ({stats.totals.ai} on your key, {stats.totals.ai_own} on their own)
                      </dt>
                      <dd className="text-2xl font-semibold">{aiRequests(stats.totals)}</dd>
                    </div>
                  </dl>
                  <UsageChart days={stats.days} />
                  <p className="text-xs text-white/40">
                    One video usually takes 1 or 2 AI requests, and retries count too. AI requests are counted since this page gained
                    graphs.
                  </p>
                </div>
              )}
            </section>

            <section aria-labelledby="accounts-title" className="space-y-3">
              <h3 id="accounts-title" className="font-medium">
                Accounts
              </h3>
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
              {data && (
                <p className="text-xs text-white/50">
                  {(["standard", "pro"] as const)
                    .map((p) => `${planName(p)}: ${data.plans[p].videos} videos and ${data.plans[p].chats} AI chats a day${data.plans[p].studio ? ", with Studio" : ""}`)
                    .join(" · ")}
                </p>
              )}

              <div className="flex gap-2">
                <input
                  type="search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search by email"
                  aria-label="Search by email"
                  className={`min-w-0 flex-1 ${field}`}
                />
                <button type="button" onClick={() => setAttempt((n) => n + 1)} className="rounded-lg border border-white/15 px-4 py-2 text-sm text-white/80 hover:bg-white/5">
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
                {data &&
                  shown.map((u) => {
                    const used = usageFor(u.id);
                    return (
                      <li key={u.id} className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
                        <div className="sm:flex sm:items-center sm:justify-between sm:gap-4">
                          <div className="min-w-0">
                            <p className="break-all text-sm font-semibold">
                              {u.email}
                              {u.is_admin && <span className="ml-2 rounded-full bg-violet-600 px-2 py-0.5 text-[11px] text-white">Admin</span>}
                              {!u.is_admin && u.plan !== "standard" && (
                                <span className="ml-2 rounded-full border border-violet-400/50 px-2 py-0.5 text-[11px] text-violet-300">{planName(u.plan)}</span>
                              )}
                              {u.disabled && <span className="ml-2 rounded-full border border-red-400/30 px-2 py-0.5 text-[11px] text-red-300">Disabled</span>}
                            </p>
                            <p className="text-xs text-white/50">Joined {joined(u.created_at)}</p>
                          </div>
                          <p className="mt-2 shrink-0 text-xs text-white/70 sm:mt-0 sm:text-right">
                            {u.is_admin
                              ? "No limits"
                              : `${planName(u.plan)}: ${u.limits.videos} videos, ${u.limits.chats} chats a day${u.studio ? " · Studio on" : ""}`}
                            <br />
                            Last {days} days: {plural(edits(used), "video edit")}, {plural(aiRequests(used), "AI request")}
                            <br />
                            Last 24 h: {plural(u.videos_24h, "video")}, {plural(u.chats_24h, "AI message")} · {plural(u.videos_stored, "video")} stored
                          </p>
                        </div>
                        <div className="mt-2 flex gap-3 text-xs">
                          {!u.is_admin && (
                            <button type="button" aria-expanded={editing === u.id} onClick={() => setEditing(editing === u.id ? null : u.id)} className="text-violet-300 underline">
                              {editing === u.id ? "Close" : "Plan and limits"}
                            </button>
                          )}
                          <button type="button" onClick={() => setOnly(only === u.id ? null : u.id)} className="text-violet-300 underline">
                            {only === u.id ? "Graph everyone" : "Graph this account"}
                          </button>
                        </div>
                        {editing === u.id && !u.is_admin && (
                          <AccountEditor
                            key={u.id}
                            user={u}
                            plans={data.plans}
                            onSaved={(saved) => {
                              setData((d) => d && { ...d, users: d.users.map((x) => (x.id === saved.id ? saved : x)) });
                              setEditing(null);
                            }}
                          />
                        )}
                      </li>
                    );
                  })}
              </ul>
            </section>
          </>
        )}
      </div>
    </Shell>
  );
}

function AccountEditor({ user, plans, onSaved }: { user: AdminAccount; plans: AdminOverview["plans"]; onSaved: (u: AdminAccount) => void }) {
  const [plan, setPlan] = useState(user.plan);
  const [videos, setVideos] = useState(user.video_limit?.toString() ?? "");
  const [chats, setChats] = useState(user.chat_limit?.toString() ?? "");
  const [studio, setStudio] = useState(user.studio);
  const [studioAi, setStudioAi] = useState(user.studio_ai_chat);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const videoLimit = parseLimit(videos);
  const chatLimit = parseLimit(chats);
  const usable = videoLimit !== undefined && chatLimit !== undefined;
  const offered = ["standard", "pro", ...(user.plan === "max" ? ["max"] : [])] as AdminAccount["plan"][];

  /** Choosing another plan starts from what that plan includes. */
  function pick(next: AdminAccount["plan"]) {
    setPlan(next);
    setStudio(next === user.plan ? user.studio : plans[next].studio);
    setStudioAi(next === user.plan ? user.studio_ai_chat : plans[next].studio_ai_chat);
  }

  async function save() {
    if (!usable) return;
    setSaving(true);
    setError(null);
    const change: AccountChange = { plan, video_limit: videoLimit, chat_limit: chatLimit, studio, studio_ai_chat: studioAi };
    try {
      onSaved(await changeAccount(user.id, change));
    } catch (e) {
      setError(message(e, "Couldn't save that."));
      setSaving(false);
    }
  }

  return (
    <form
      className="mt-3 space-y-3 border-t border-white/10 pt-3 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <div>
        <p className="mb-1 text-xs text-white/55">Plan</p>
        <div role="radiogroup" aria-label="Plan" className="flex gap-2">
          {offered.map((p) => (
            <button key={p} type="button" role="radio" aria-checked={plan === p} disabled={saving} onClick={() => pick(p)} className={choice(plan === p)}>
              {planName(p)}
            </button>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {(
          [
            ["Videos a day", videos, setVideos, plans[plan].videos],
            ["AI chats a day", chats, setChats, plans[plan].chats],
          ] as const
        ).map(([label, value, set, fromPlan]) => (
          <label key={label} className="block">
            <span className="mb-1 block text-xs text-white/55">{label}</span>
            <input inputMode="numeric" value={value} disabled={saving} onChange={(e) => set(e.target.value)} placeholder={`Plan: ${fromPlan}`} className={field} />
          </label>
        ))}
      </div>
      <p className="text-xs text-white/40">Leave a box empty to use the plan&apos;s number.</p>
      <label className="flex items-center justify-between gap-3">
        <span>
          Studio <span className="text-xs text-white/50">(Beta)</span>
          <span className="block text-xs text-white/50">
            {plans[plan].studio ? "Pro includes the full set of Studio tools." : "On a Standard plan this is the basic Studio."}
          </span>
        </span>
        <input type="checkbox" className="h-5 w-5 accent-violet-500" checked={studio} disabled={saving} onChange={(e) => setStudio(e.target.checked)} />
      </label>
      <label className={`flex items-center justify-between gap-3 ${studio ? "" : "opacity-40"}`}>
        <span>Studio AI assistant</span>
        <input type="checkbox" className="h-5 w-5 accent-violet-500" checked={studio && studioAi} disabled={saving || !studio} onChange={(e) => setStudioAi(e.target.checked)} />
      </label>
      {!usable && <p className="text-xs text-red-300">Limits are whole numbers from 0 to 10000.</p>}
      {error && (
        <p role="alert" className="text-xs text-red-300">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={saving || !usable}
        className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold hover:bg-violet-500 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-white/30"
      >
        {saving ? "Saving…" : "Save changes"}
      </button>
    </form>
  );
}
