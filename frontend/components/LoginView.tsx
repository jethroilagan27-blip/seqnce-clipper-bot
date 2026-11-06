"use client";

import { useState } from "react";
import { ApiError, login, signup, type Session } from "@/lib/api";

type Props = { onSession: (s: Session) => void; notice?: string | null };

// Sign in, or create an account with an invite code. Sign-up is invite-only: the code comes from
// whoever runs the server (`python -m app.admin invite`).
export default function LoginView({ onSession, notice }: Props) {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      onSession(mode === "signin" ? await login(email, password) : await signup(code, email, password));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setBusy(false);
    }
  }

  const input =
    "w-full rounded-lg border border-white/10 bg-[#15151c] px-3 py-2.5 text-sm placeholder:text-white/30 focus:border-violet-400 focus:outline-none disabled:opacity-50";

  return (
    <div className="mx-auto w-full max-w-sm space-y-5">
      <div role="tablist" aria-label="Account" className="grid grid-cols-2 gap-1 rounded-xl bg-white/5 p-1 text-sm">
        {(["signin", "signup"] as const).map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            onClick={() => {
              setMode(m);
              setError(null);
            }}
            className={`rounded-lg px-3 py-2 ${mode === m ? "bg-violet-600 font-semibold text-white" : "text-white/60 hover:text-white"}`}
          >
            {m === "signin" ? "Sign in" : "Create account"}
          </button>
        ))}
      </div>

      {notice && <p className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">{notice}</p>}

      <form onSubmit={submit} className="space-y-3">
        {mode === "signup" && (
          <div>
            <label htmlFor="invite" className="mb-1 block text-xs text-white/60">
              Invite code
            </label>
            <input
              id="invite"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="SQ-XXXX-XXXX-XXXX"
              autoComplete="off"
              required
              disabled={busy}
              className={`${input} font-mono uppercase`}
            />
          </div>
        )}
        <div>
          <label htmlFor="email" className="mb-1 block text-xs text-white/60">
            Email
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            required
            disabled={busy}
            className={input}
          />
        </div>
        <div>
          <label htmlFor="password" className="mb-1 block text-xs text-white/60">
            Password{mode === "signup" && " (at least 10 characters)"}
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "signin" ? "current-password" : "new-password"}
            minLength={mode === "signup" ? 10 : undefined}
            required
            disabled={busy}
            className={input}
          />
        </div>

        {error && (
          <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-xl bg-violet-600 px-6 py-3 font-semibold text-white hover:bg-violet-500 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-white/30"
        >
          {busy ? "One moment…" : mode === "signin" ? "Sign in" : "Create account"}
        </button>
      </form>

      <p className="text-center text-xs text-white/40">
        {mode === "signin"
          ? "Seqnce is invite-only for now. Ask for an invite code, then choose “Create account”."
          : "Only the email, a password hash and your own videos are stored. Videos are deleted automatically after a few days."}
      </p>
    </div>
  );
}
