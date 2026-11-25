"use client";

import type { AuthUser, Quota } from "@/lib/api";

const left = (q: Quota | undefined) => (!q ? null : q.limit === null ? "Unlimited" : `${Math.max(0, q.limit - q.used)} of ${q.limit} left`);

/** Who is signed in, their plan and what they have left in the last 24 hours. */
export default function AccountSummary({ user }: { user: AuthUser }) {
  const rows: [string, string | null][] = [
    ["Plan", user.is_admin ? "Admin" : user.plan.charAt(0).toUpperCase() + user.plan.slice(1)],
    ["Videos today", left(user.quota.videos)],
    ["AI messages today", left(user.quota.chats)],
    ["Studio videos today", user.features?.studio ? left(user.quota.studio) : null],
    ["AI key", user.ai?.mode === "own" ? (user.ai.has_key ? `Saved (${user.ai.hint})` : "Not added yet") : null],
  ];
  return (
    <div className="space-y-3">
      <p className="break-all text-sm font-semibold">{user.email}</p>
      <dl className="space-y-1.5 text-sm">
        {rows.map(
          ([label, value]) =>
            value !== null && (
              <div key={label} className="flex justify-between gap-3">
                <dt className="text-white/55">{label}</dt>
                <dd className="text-right">{value}</dd>
              </div>
            ),
        )}
      </dl>
    </div>
  );
}
