"use client";

import { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "@/lib/studio";
import { buttonCls, primaryCls } from "./ui";

type Props = {
  messages: ChatMessage[];
  canUndo: boolean;
  thinking: boolean;
  /** A video is being made right now: changes have to wait. */
  locked: boolean;
  error: string | null;
  onSend: (text: string) => void;
  onUndo: () => void;
};

const MAX = 30000;

/** Talk to the assistant: paste the script, or say what to change. It reads the file and folder names to build the scenes. */
export default function ChatPanel({ messages, canUndo, thinking, locked, error, onSend, onUndo }: Props) {
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);

  // keep the newest message in view
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest" });
  }, [messages.length, thinking]);

  const send = () => {
    const t = text.trim();
    if (!t || thinking || locked) return;
    setText("");
    onSend(t);
  };

  return (
    <section className="space-y-3 rounded-2xl border border-white/10 bg-white/[0.02] p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Ask the assistant</h2>
        <p className="text-xs text-white/40">Reads your file and folder names. Uses one of your daily AI messages each time.</p>
      </div>

      {messages.length > 0 && (
        <ul className="max-h-96 space-y-2 overflow-y-auto pr-1" aria-label="Chat with the assistant" aria-live="polite">
          {messages.map((m, i) => (
            <li key={i} className={`whitespace-pre-wrap rounded-xl px-3 py-2 text-sm ${m.role === "user" ? "ml-8 bg-violet-600/25" : "mr-8 bg-white/[0.06]"}`}>
              <span className="mb-0.5 block text-[11px] uppercase tracking-wide text-white/40">{m.role === "user" ? "You" : "Assistant"}</span>
              {m.text}
            </li>
          ))}
          {thinking && <li className="mr-8 rounded-xl bg-white/[0.06] px-3 py-2 text-sm text-white/60">Reading your files and writing the scenes… this can take up to a minute.</li>}
          <div ref={end} />
        </ul>
      )}
      {messages.length === 0 && thinking && <p className="text-sm text-white/60">Reading your files and writing the scenes… this can take up to a minute.</p>}

      {error && (
        <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200">
          {error}
        </p>
      )}

      <textarea
        value={text}
        rows={5}
        maxLength={MAX}
        disabled={thinking || locked}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            send();
          }
        }}
        aria-label="Message for the assistant"
        placeholder="Type your instructions here or tell the assistant what to change…"
        className="w-full rounded-lg border border-white/10 bg-[#15151c] px-3 py-2 text-sm placeholder:text-white/30 focus:border-violet-400 focus:outline-none disabled:opacity-50"
      />
      <div className="flex flex-wrap items-center gap-2">
        <button className={primaryCls} disabled={!text.trim() || thinking || locked} onClick={send}>
          {thinking ? "Working…" : "Send"}
        </button>
        <button className={buttonCls} disabled={!canUndo || thinking || locked} onClick={onUndo} title="Put the scenes back the way they were before the assistant's last change">
          Undo the assistant&apos;s last change
        </button>
        <span className="ml-auto text-xs tabular-nums text-white/30">{text.length}/{MAX} · Ctrl+Enter sends</span>
      </div>
    </section>
  );
}
