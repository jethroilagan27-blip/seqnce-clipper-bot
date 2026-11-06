"use client";

import { useState } from "react";
import { type Changes, type Job, type Version } from "@/lib/api";

const SUGGESTIONS = [
  "Make it shorter",
  "Make the hook more exciting",
  "Cut the intro",
  "Keep only the best part",
];

const STAGE_LABEL: Record<string, string> = {
  revising: "Rethinking the edit",
  editing: "Applying the edit",
  rendering: "Rendering the new version",
};

export function ChangeChips({ changes }: { changes: Changes | null }) {
  if (!changes) return null;
  if (changes.unchanged) return <p className="text-xs text-white/40">No changes to the video.</p>;
  const c = changes.counts;
  const chips: { text: string; cls: string }[] = [];
  if (c.added) chips.push({ text: `${c.added} added`, cls: "bg-emerald-500/15 text-emerald-300" });
  if (c.removed) chips.push({ text: `${c.removed} removed`, cls: "bg-red-500/15 text-red-300" });
  if (c.trimmed) chips.push({ text: `${c.trimmed} trimmed`, cls: "bg-amber-400/15 text-amber-200" });
  for (const s of changes.settings) chips.push({ text: `${s.field}: ${s.after}`, cls: "bg-violet-500/15 text-violet-200" });
  const delta = changes.new_total - changes.old_total;
  if (Math.abs(delta) >= 0.5)
    chips.push({ text: `${delta > 0 ? "+" : ""}${delta.toFixed(0)}s`, cls: "bg-white/10 text-white/70" });
  return (
    <div className="flex flex-wrap gap-1.5">
      {chips.map((chip, i) => (
        <span key={i} className={`rounded-full px-2 py-0.5 text-xs ${chip.cls}`}>
          {chip.text}
        </span>
      ))}
    </div>
  );
}

function Bubble({ who, children }: { who: "you" | "ai" | "note" | "error"; children: React.ReactNode }) {
  if (who === "note")
    return <p className="text-center text-xs text-white/40">{children}</p>;
  const cls =
    who === "you"
      ? "ml-8 self-end bg-violet-600/80"
      : who === "error"
        ? "mr-8 border border-red-500/40 bg-red-500/10 text-red-200"
        : "mr-8 bg-white/[0.06]";
  return <div className={`space-y-2 rounded-2xl px-3.5 py-2.5 text-sm ${cls}`}>{children}</div>;
}

type Props = {
  versions: Version[];
  selected: number;
  job: Job;
  busy: boolean;
  onSend: (message: string) => Promise<string | null>; // resolves to an error message, or null
  onSelect: (version: number) => void;
};

export default function RevisionPanel({ versions, selected, job, busy, onSend, onSelect }: Props) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  // The message just sent, shown until its version exists (or next to the error if it failed).
  const [pending, setPending] = useState<{ message: string; after: number } | null>(null);
  const disabled = busy || sending;
  const showPending = pending !== null && pending.after === versions.length && (busy || !!job.error);

  async function send(message: string) {
    const m = message.trim();
    if (!m || disabled) return;
    setSending(true);
    setSendError(null);
    const err = await onSend(m);
    setSending(false);
    if (err) setSendError(err);
    else {
      setText("");
      setPending({ message: m, after: versions.length });
    }
  }

  const first = versions[0];
  return (
    <section className="flex min-h-0 flex-col rounded-2xl border border-white/10 bg-white/[0.02]">
      <header className="border-b border-white/10 px-4 py-3">
        <h2 className="font-medium">Edit with chat</h2>
        <p className="text-xs text-white/50">Ask for changes in plain words. Every change becomes a new version.</p>
      </header>

      <div className="flex max-h-[46vh] min-h-40 flex-col gap-3 overflow-y-auto px-4 py-4" aria-live="polite">
        {first && (
          <>
            {first.message && <Bubble who="you">{first.message}</Bubble>}
            <Bubble who="ai">
              <p>
                {first.plan.source === "ai"
                  ? "Here's your first edit."
                  : "Here's a basic cut (the AI wasn't available for this one)."}
                {first.plan.summary.main_message && (
                  <span className="text-white/60"> {first.plan.summary.main_message}</span>
                )}
              </p>
              <button className="text-xs text-violet-300 hover:underline" onClick={() => onSelect(first.version)}>
                View v{first.version}
              </button>
            </Bubble>
          </>
        )}

        {versions.slice(1).map((v) => (
          <div key={v.version} className="flex flex-col gap-2">
            {v.source === "chat" ? (
              <>
                <Bubble who="you">{v.message}</Bubble>
                <Bubble who="ai">
                  <p>{v.reply ?? "Done."}</p>
                  <ChangeChips changes={v.changes} />
                  <button
                    className={`text-xs hover:underline ${selected === v.version ? "text-white/40" : "text-violet-300"}`}
                    onClick={() => onSelect(v.version)}
                  >
                    {selected === v.version ? `Viewing v${v.version}` : `View v${v.version}`}
                  </button>
                </Bubble>
              </>
            ) : (
              <Bubble who="note">
                {v.source === "restore" ? "↩" : "✎"} {v.message}{" "}
                <button className="text-violet-300 hover:underline" onClick={() => onSelect(v.version)}>
                  v{v.version}
                </button>
              </Bubble>
            )}
          </div>
        ))}

        {showPending && <Bubble who="you">{pending.message}</Bubble>}

        {busy && (
          <Bubble who="ai">
            <p className="flex items-center gap-2">
              <span className="h-2 w-2 animate-pulse rounded-full bg-violet-400" />
              {STAGE_LABEL[job.stage] ?? "Working"}
              {job.status === "queued" && " (waiting in queue)"}…
            </p>
            <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
              <div className="h-full bg-violet-500 transition-[width] duration-500" style={{ width: `${job.progress}%` }} />
            </div>
          </Bubble>
        )}

        {!busy && job.error && (
          <Bubble who="error">
            <p>
              <span className="font-medium">That change didn&apos;t work.</span> {job.error}
            </p>
            <p className="text-xs text-red-200/70">Your current version is untouched.</p>
          </Bubble>
        )}
      </div>

      <div className="space-y-2 border-t border-white/10 px-4 py-3">
        {versions.length <= 1 && !busy && (
          <div className="flex flex-wrap gap-1.5">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                disabled={disabled}
                onClick={() => send(s)}
                className="rounded-full border border-white/15 px-3 py-1 text-xs text-white/70 hover:border-white/40 hover:text-white disabled:opacity-40"
              >
                {s}
              </button>
            ))}
          </div>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void send(text);
          }}
          className="flex items-end gap-2"
        >
          <textarea
            rows={2}
            maxLength={500}
            value={text}
            disabled={disabled}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send(text);
              }
            }}
            aria-label="Tell the editor what to change"
            placeholder={busy ? "Working on your last request…" : "e.g. Cut the part about pricing, and make the hook a question"}
            className="min-h-11 flex-1 resize-none rounded-lg border border-white/10 bg-[#15151c] px-3 py-2 text-sm placeholder:text-white/30 focus:border-violet-400 focus:outline-none disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={disabled || !text.trim()}
            className="h-11 rounded-lg bg-violet-600 px-4 text-sm font-semibold hover:bg-violet-500 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-white/30"
          >
            Send
          </button>
        </form>
        {sendError && (
          <p role="alert" className="text-xs text-red-300">
            {sendError}
          </p>
        )}
      </div>
    </section>
  );
}
