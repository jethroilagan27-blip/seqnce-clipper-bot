"use client";

import Link from "next/link";
import { useState } from "react";
import { ApiError, removeAiKey, saveAiKey } from "@/lib/api";
import AccountSummary from "./AccountSummary";
import type { AccountInfo } from "./AuthGate";
import InstallHint from "./InstallHint";
import Shell from "./Shell";
import ThemeSwitch from "./ThemeSwitch";

const input =
  "w-full rounded-lg border border-white/10 bg-field px-3 py-2.5 text-sm placeholder:text-white/30 focus:border-violet-400 focus:outline-none disabled:opacity-50";

// Settings of the signed-in account. For now: the account's own Gemini key. The key is typed here once and is never shown
// again (the server only reports its last 4 characters), so there is nothing on this page to copy or leak.
export default function SettingsView({ account }: { account: AccountInfo }) {
  const user = account.user;
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!key.trim() || busy) return;
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      await saveAiKey(key.trim());
      setKey(""); // gone from the page the moment it is saved
      setDone("Saved. The AI now runs on your key.");
      account.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the key.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (busy) return;
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      await removeAiKey();
      setDone("Your key was removed from Seqnce.");
      account.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't remove the key.");
    } finally {
      setBusy(false);
    }
  }

  const ai = user?.ai;
  return (
    <Shell user={user} onSignOut={user ? account.signOut : undefined}>
      <div className="space-y-6">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">Account settings</h2>
          <Link href="/" className="text-sm text-violet-300 underline">
            ← Back to editing
          </Link>
        </div>

        {user && (
          <section className="space-y-4 rounded-2xl border border-white/10 bg-white/[0.02] p-4 sm:p-5" aria-label="Your account">
            <AccountSummary user={user} />
            <button type="button" onClick={account.signOut} className="rounded-lg border border-white/15 px-4 py-2.5 text-sm text-white/80 hover:bg-white/5">
              Sign out
            </button>
          </section>
        )}

        <section className="space-y-3 rounded-2xl border border-white/10 bg-white/[0.02] p-4 sm:p-5" aria-labelledby="look-h">
          <h3 id="look-h" className="font-semibold">
            Appearance
          </h3>
          <ThemeSwitch />
        </section>

        <section className="space-y-4 rounded-2xl border border-white/10 bg-white/[0.02] p-4 sm:p-5" aria-labelledby="ai-key-h">
          <div>
            <h3 id="ai-key-h" className="font-semibold">
              Your Gemini API key
            </h3>
            <p className="mt-1 text-sm text-white/55">
              Seqnce&apos;s AI (the editing plan, the chat and Studio&apos;s assistant) runs on <strong className="text-white/80">your own</strong> free Google Gemini key, so
              what you use is on your own quota.
            </p>
          </div>

          {!user || ai?.mode === "server" ? (
            <p className="rounded-lg border border-white/10 px-3 py-2 text-sm text-white/60">
              {user ? "This account uses the server's AI key, so there is nothing to set up." : "This computer uses the key in the .env file, so there is nothing to set up here."}
            </p>
          ) : (
            <>
              <p className={`rounded-lg border px-3 py-2 text-sm ${ai?.has_key ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-100" : "border-amber-400/30 bg-amber-400/10 text-amber-100"}`}>
                {ai?.has_key ? <>A key is saved ({ai.hint}). The AI is on.</> : "No key yet, so the AI is off: videos get a basic cut and the chat can't answer."}
              </p>

              <form onSubmit={save} className="space-y-3" autoComplete="off">
                <div>
                  <label htmlFor="gemini-key" className="mb-1 block text-xs text-white/60">
                    {ai?.has_key ? "Replace it with a new key" : "Paste your key"}
                  </label>
                  <input
                    id="gemini-key"
                    type="password"
                    name="gemini-key"
                    autoComplete="off"
                    autoCorrect="off"
                    autoCapitalize="off"
                    spellCheck={false}
                    value={key}
                    onChange={(e) => setKey(e.target.value)}
                    placeholder="AIza…"
                    maxLength={300}
                    disabled={busy}
                    className={`${input} font-mono`}
                  />
                </div>
                {error && (
                  <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                    {error}
                  </p>
                )}
                {done && (
                  <p role="status" className="rounded-lg border border-emerald-400/30 bg-emerald-400/10 px-3 py-2 text-sm text-emerald-100">
                    {done}
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  <button type="submit" disabled={!key.trim() || busy} className="rounded-lg bg-violet-600 px-4 py-2.5 text-sm font-semibold hover:bg-violet-500 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-white/30">
                    {busy ? "Checking…" : "Save key"}
                  </button>
                  {ai?.has_key && (
                    <button type="button" onClick={remove} disabled={busy} className="rounded-lg border border-white/15 px-4 py-2.5 text-sm text-white/80 hover:bg-white/5 disabled:opacity-40">
                      Remove my key
                    </button>
                  )}
                </div>
              </form>

              <details className="text-sm text-white/55">
                <summary className="cursor-pointer text-white/70">How do I get a key?</summary>
                <ol className="mt-2 list-decimal space-y-1 pl-5">
                  <li>
                    Open{" "}
                    <a className="text-violet-300 underline" href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer">
                      Google AI Studio
                    </a>{" "}
                    and sign in with a Google account.
                  </li>
                  <li>Press “Create API key”, then copy it.</li>
                  <li>Paste it above. The free tier is enough for normal use.</li>
                </ol>
              </details>

              <p className="text-xs text-white/40">
                Your key is checked with Google, then kept encrypted on the server. It is never shown again (only its last 4 characters), never put in a log, and
                only used for your own videos. You can remove it any time.
              </p>
            </>
          )}
        </section>

        <InstallHint />
      </div>
    </Shell>
  );
}
