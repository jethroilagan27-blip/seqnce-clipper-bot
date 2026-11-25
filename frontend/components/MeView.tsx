"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { ApiError, removeAiKey, saveAiKey, type AiKeyState } from "@/lib/api";
import AccountSummary from "./AccountSummary";
import type { AccountInfo } from "./AuthGate";
import InstallHint from "./InstallHint";
import Shell from "./Shell";
import ThemeSwitch from "./ThemeSwitch";

const input =
  "w-full rounded-lg border border-white/10 bg-field px-3 py-2.5 text-sm placeholder:text-white/30 focus:border-violet-400 focus:outline-none disabled:opacity-50";
const card = "space-y-4 rounded-2xl border border-white/10 bg-white/[0.02] p-4 sm:p-5";
const row = "flex items-center justify-between rounded-xl border border-white/10 px-4 py-3 text-sm hover:bg-white/5";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={card} aria-label={title}>
      <h3 className="font-semibold">{title}</h3>
      {children}
    </section>
  );
}

// "Custom API": the account's own Gemini key. Optional when Seqnce's AI is available to the account. The key is typed
// here once and is never shown again (the server only reports its last 4 characters).
function CustomApi({ ai, onChange }: { ai: AiKeyState; onChange: () => void }) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const own = ai.mode === "own" && ai.has_key;

  async function run(action: () => Promise<unknown>, message: string, fallback: string) {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      await action();
      setKey(""); // gone from the page the moment it is saved
      setDone(message);
      onChange();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : fallback);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Custom API">
      <p className={`rounded-lg border px-3 py-2 text-sm ${ai.has_key ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-100" : "border-amber-400/30 bg-amber-400/10 text-amber-100"}`}>
        {own
          ? `Using your own key (${ai.hint}).`
          : ai.has_key
            ? "Using Seqnce's AI. Nothing to set up."
            : "No key yet, so the AI is off: videos get a basic cut and the chat can't answer."}
      </p>
      <p className="text-sm text-white/55">
        {ai.system ? "Prefer to use your own Google Gemini key instead of Seqnce's? Add it here and the AI runs on your quota." : "The AI runs on your own free Google Gemini key."}
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (key.trim() && !busy) void run(() => saveAiKey(key.trim()), "Saved. The AI now runs on your key.", "Couldn't save the key.");
        }}
        className="space-y-3"
        autoComplete="off"
      >
        <div>
          <label htmlFor="gemini-key" className="mb-1 block text-xs text-white/60">
            {own ? "Replace it with a new key" : "Your Gemini API key"}
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
          {own && (
            <button
              type="button"
              onClick={() => void run(removeAiKey, "Your key was removed from Seqnce.", "Couldn't remove the key.")}
              disabled={busy}
              className="rounded-lg border border-white/15 px-4 py-2.5 text-sm text-white/80 hover:bg-white/5 disabled:opacity-40"
            >
              {ai.system ? "Go back to Seqnce's AI" : "Remove my key"}
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
          <li>Paste it above.</li>
        </ol>
      </details>

      <p className="text-xs text-white/40">
        A saved key is checked with Google, kept encrypted, never shown again (only its last 4 characters) and used only for your own videos. Whichever key is used, what
        the AI works on (what is said in your video, a few frames, your file names and messages; for highlight videos, a small copy of the whole video with its sound)
        goes to Google&apos;s Gemini, which may use it to improve its products on free keys. Don&apos;t upload anything confidential.
      </p>
    </Section>
  );
}

// The "Me" page: everything about the person and the app.
export default function MeView({ account }: { account: AccountInfo }) {
  const user = account.user;
  return (
    <Shell user={user} onSignOut={user ? account.signOut : undefined} section="me">
      <div className="space-y-5">
        <h2 className="text-lg font-semibold">Me</h2>

        <section className={card} aria-label="Your account">
          {user ? (
            <div className="flex items-start gap-3">
              <span aria-hidden="true" className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-violet-600 text-lg font-semibold text-white">
                {user.email.charAt(0).toUpperCase()}
              </span>
              <div className="min-w-0 flex-1">
                <AccountSummary user={user} />
              </div>
            </div>
          ) : (
            <p className="text-sm text-white/60">Running on this computer: no account and no limits.</p>
          )}
        </section>

        <Section title="Personalization">
          <ThemeSwitch />
        </Section>

        {user ? (
          <CustomApi ai={user.ai} onChange={account.refresh} />
        ) : (
          <Section title="Custom API">
            <p className="text-sm text-white/60">This computer uses the key in the .env file, so there is nothing to set up here.</p>
          </Section>
        )}

        <Section title="Settings">
          <nav aria-label="Settings" className="space-y-2">
            <Link href="/library" className={row}>
              My videos <span aria-hidden="true">›</span>
            </Link>
            {user?.is_admin && (
              <Link href="/admin" className={row}>
                Admin: all accounts <span aria-hidden="true">›</span>
              </Link>
            )}
          </nav>
        </Section>

        <InstallHint />

        {user && (
          <button type="button" onClick={account.signOut} className="w-full rounded-xl border border-red-400/30 px-4 py-3 text-sm text-red-300 hover:bg-red-500/10">
            Sign out
          </button>
        )}
      </div>
    </Shell>
  );
}
