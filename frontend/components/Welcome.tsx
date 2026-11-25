"use client";

import { useState } from "react";
import type { Session } from "@/lib/api";
import InstallHint from "./InstallHint";
import LoginView from "./LoginView";
import { BetaBadge } from "./Shell";

const FEATURES = [
  { icon: "✂", title: "Edits your clip for you", text: "Picks the best parts, trims the pauses, crops it vertical and adds captions." },
  { icon: "⭐", title: "Highlight videos", text: "No talking needed: picks the best moments from games, workouts, events or trips." },
  { icon: "💬", title: "Change it by chatting",text: "Say “make it 20 seconds” or “cut the intro”. Every version is kept." },
  { icon: "🖼", title: "Photos into video", text: "Put your photos in order, add your music, done." },
  { icon: "🎬", title: "Studio", text: "Longer, scripted videos with scenes, voice-overs and titles. For selected accounts.", beta: true },
];

// What a visitor sees before signing in: what Seqnce is, then sign up / sign in, and getting the app. On a phone the
// introduction comes first and the form opens from its buttons; on wider screens they sit side by side.
export default function Welcome({ onSession, notice, openSignup }: { onSession: (s: Session) => void; notice: string | null; openSignup: boolean }) {
  const [chosen, setChosen] = useState<"signin" | "signup" | null>(null);
  const showForm = chosen !== null || notice !== null; // an ended session goes straight back to the form
  const [introAgain, setIntroAgain] = useState(false);
  const form = showForm && !introAgain;
  const choose = (mode: "signin" | "signup") => {
    setChosen(mode);
    setIntroAgain(false);
  };

  return (
    <div className="sm:grid sm:grid-cols-[1.1fr_1fr] sm:items-start sm:gap-12">
      <section className={`space-y-6 ${form ? "hidden sm:block" : ""}`} aria-label="About Seqnce">
        <div className="space-y-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-violet-300">AI short-form video editor</p>
          <h2 className="text-3xl font-bold leading-tight">
            Raw clips in. <span className="text-violet-300">Ready-to-post videos out.</span>
          </h2>
          <p className="text-sm text-white/60">Upload what you filmed and Seqnce does the editing. You check it, change what you like, and download it.</p>
        </div>

        <ul className="space-y-3">
          {FEATURES.map((f) => (
            <li key={f.title} className="flex gap-3">
              <span aria-hidden="true" className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-violet-500/15 text-lg">
                {f.icon}
              </span>
              <span>
                <span className="flex items-center gap-2 text-sm font-semibold">
                  {f.title} {f.beta && <BetaBadge />}
                </span>
                <span className="block text-sm text-white/55">{f.text}</span>
              </span>
            </li>
          ))}
        </ul>

        <div className="space-y-2 sm:hidden">
          <button type="button" onClick={() => choose("signup")} className="w-full rounded-xl bg-violet-600 px-4 py-3.5 font-semibold text-white hover:bg-violet-500">
            Get started
          </button>
          <button type="button" onClick={() => choose("signin")} className="w-full rounded-xl border border-white/20 px-4 py-3 text-sm hover:bg-white/5">
            I already have an account
          </button>
        </div>

        <InstallHint />
      </section>

      <section className={`space-y-4 ${form ? "" : "hidden sm:block"}`} aria-label="Sign in or sign up">
        <button type="button" onClick={() => setIntroAgain(true)} className="text-sm text-violet-300 underline sm:hidden">
          ← Back
        </button>
        <LoginView key={chosen ?? "start"} initialMode={chosen ?? "signin"} onSession={onSession} notice={notice} openSignup={openSignup} />
      </section>
    </div>
  );
}
