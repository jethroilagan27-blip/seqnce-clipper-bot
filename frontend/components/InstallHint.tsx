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

/** "Install Seqnce on your phone": a button where the browser supports it, the Share-menu steps on iPhone. */
export default function InstallHint() {
  const env = useSyncExternalStore(subscribe, snapshot, () => "other" as Env);
  const [declined, setDeclined] = useState(false);
  if (env === "installed") return null;

  async function install() {
    if (!deferred) return;
    await deferred.prompt();
    const { outcome } = await deferred.userChoice;
    if (outcome === "dismissed") setDeclined(true);
    deferred = null;
    notify();
  }

  return (
    <section className="space-y-3 rounded-2xl border border-white/10 bg-white/[0.02] p-4 sm:p-5" aria-labelledby="install-h">
      <h3 id="install-h" className="font-semibold">
        Use Seqnce as a phone app
      </h3>
      <p className="text-sm text-white/55">Add it to your home screen: it opens full screen like an app, with its own icon. Nothing to download from a store.</p>
      {env === "prompt" && !declined && (
        <button onClick={install} className="rounded-lg bg-violet-600 px-4 py-2.5 text-sm font-semibold hover:bg-violet-500">
          Install the app
        </button>
      )}
      {env === "ios" && (
        <ol className="list-decimal space-y-1 pl-5 text-sm text-white/70">
          <li>Open this page in Safari.</li>
          <li>Tap the Share button (the square with an arrow).</li>
          <li>Choose “Add to Home Screen”, then “Add”.</li>
        </ol>
      )}
      {(env === "other" || declined) && (
        <p className="text-sm text-white/55">
          On Android (Chrome): open the ⋮ menu and choose “Install app” or “Add to Home screen”. On iPhone: use Safari&apos;s Share button, then “Add to Home Screen”.
        </p>
      )}
    </section>
  );
}
