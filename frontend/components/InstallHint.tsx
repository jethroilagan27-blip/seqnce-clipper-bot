"use client";

import { useState, useSyncExternalStore } from "react";

type InstallEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: "accepted" | "dismissed" }> };

// Chrome/Edge/Android tell the page when it can be installed; the event is kept here so a button can use it later.
let deferred: InstallEvent | null = null;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const onPrompt = (e: Event) => {
    e.preventDefault(); // keep the browser's own mini-bar away; our button offers it instead
    deferred = e as InstallEvent;
    notify();
  };
  const onInstalled = () => {
    deferred = null;
    notify();
  };
  window.addEventListener("beforeinstallprompt", onPrompt);
  window.addEventListener("appinstalled", onInstalled);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("beforeinstallprompt", onPrompt);
    window.removeEventListener("appinstalled", onInstalled);
  };
}

type Env = "installed" | "prompt" | "ios" | "other";
function snapshot(): Env {
  const standalone = window.matchMedia("(display-mode: standalone)").matches || (navigator as { standalone?: boolean }).standalone === true;
  if (standalone) return "installed";
  if (deferred) return "prompt";
  return /iphone|ipad|ipod/i.test(navigator.userAgent) ? "ios" : "other";
}

// "Get the app": the browser's own install window where it offers one, otherwise the steps for the phone in hand.
// It installs the website as an app (home screen icon, full screen); videos are still edited on Seqnce's server.
export default function InstallHint() {
  const env = useSyncExternalStore(subscribe, snapshot, () => "other" as Env);
  const [steps, setSteps] = useState(false);
  if (env === "installed") return null;

  async function get() {
    if (!deferred) return setSteps(true);
    await deferred.prompt();
    const { outcome } = await deferred.userChoice;
    if (outcome === "dismissed") setSteps(true);
    deferred = null;
    notify();
  }

  return (
    <section className="space-y-3 rounded-2xl border border-white/10 bg-white/[0.02] p-4 sm:p-5" aria-labelledby="install-h">
      <h3 id="install-h" className="font-semibold">
        Get the app for the full experience
      </h3>
      <p className="text-sm text-white/55">Seqnce on your home screen: one tap to open, full screen, no browser bars. Nothing to download from a store.</p>
      <button type="button" onClick={get} className="w-full rounded-xl bg-violet-600 px-4 py-3 text-sm font-semibold text-white hover:bg-violet-500">
        Get the Seqnce app
      </button>
      {steps &&
        (env === "ios" ? (
          <ol className="list-decimal space-y-1 pl-5 text-sm text-white/70">
            <li>Open this page in Safari.</li>
            <li>Tap the Share button (the square with an arrow).</li>
            <li>Choose “Add to Home Screen”, then “Add”.</li>
          </ol>
        ) : (
          <ol className="list-decimal space-y-1 pl-5 text-sm text-white/70">
            <li>Open your browser&apos;s ⋮ menu.</li>
            <li>Choose “Install app” or “Add to Home screen”.</li>
            <li>On iPhone instead: Safari&apos;s Share button, then “Add to Home Screen”.</li>
          </ol>
        ))}
    </section>
  );
}
