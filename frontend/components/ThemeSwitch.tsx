"use client";

import { useSyncExternalStore } from "react";
import { BAR_COLOR, DEFAULT_THEME, THEME_KEY, parseTheme, type Theme } from "@/lib/theme";

const listeners = new Set<() => void>();
const current = (): Theme => parseTheme(document.documentElement.getAttribute("data-theme"));

function show(theme: Theme) {
  document.documentElement.setAttribute("data-theme", theme);
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", BAR_COLOR[theme]);
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (e: StorageEvent) => e.key === THEME_KEY && show(parseTheme(e.newValue)); // changed in another tab
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

function choose(theme: Theme) {
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* private mode: the choice lasts until the page is closed */
  }
  show(theme);
}

/** "Light / Dark", remembered on this device. */
export default function ThemeSwitch() {
  const theme = useSyncExternalStore(subscribe, current, () => DEFAULT_THEME);
  return (
    <div role="group" aria-label="Theme" className="grid grid-cols-2 gap-1 rounded-xl bg-white/5 p-1">
      {(["light", "dark"] as const).map((t) => (
        <button
          key={t}
          type="button"
          aria-pressed={theme === t}
          onClick={() => choose(t)}
          className={`rounded-lg px-3 py-2.5 text-sm ${theme === t ? "bg-violet-600 font-semibold text-white" : "text-white/60 hover:text-white"}`}
        >
          {t === "light" ? "☀ Light" : "☾ Dark"}
        </button>
      ))}
    </div>
  );
}
