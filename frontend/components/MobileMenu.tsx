"use client";

import Link from "next/link";
import { useRef } from "react";
import type { AuthUser } from "@/lib/api";
import AccountSummary from "./AccountSummary";
import ThemeSwitch from "./ThemeSwitch";

// The phone's ☰ menu: a panel that slides over the page from the right. A native <dialog>, so the Escape / back key
// closes it and the keyboard stays inside it while it is open.
export default function MobileMenu({ user, onSignOut }: { user: AuthUser | null; onSignOut?: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const close = () => dialog.current?.close();
  const row = "flex items-center justify-between rounded-xl border border-white/10 px-4 py-3 text-sm hover:bg-white/5";

  return (
    <>
      <button type="button" aria-label="Open menu" aria-haspopup="dialog" onClick={() => dialog.current?.showModal()} className="-mr-2 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg hover:bg-white/5">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <path d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>
      <dialog ref={dialog} aria-label="Menu" onClick={(e) => e.target === e.currentTarget && close()} className="menu-sheet">
        <div className="flex min-h-full flex-col gap-6 p-5">
          <div className="flex items-center justify-between">
            <p className="text-lg font-semibold">Menu</p>
            <button type="button" aria-label="Close menu" onClick={close} className="-mr-2 flex h-11 w-11 items-center justify-center rounded-lg text-xl hover:bg-white/5">
              ✕
            </button>
          </div>

          {user ? <AccountSummary user={user} /> : <p className="text-sm text-white/55">Running on this computer: no account needed.</p>}

          <div>
            <p className="mb-2 text-xs uppercase tracking-wide text-white/40">Appearance</p>
            <ThemeSwitch />
          </div>

          <nav aria-label="Account" className="space-y-2">
            <Link href="/settings" onClick={close} className={row}>
              Account settings <span aria-hidden="true">›</span>
            </Link>
          </nav>

          {user && onSignOut && (
            <button
              type="button"
              onClick={() => {
                close();
                onSignOut();
              }}
              className="mt-auto rounded-xl border border-red-400/30 px-4 py-3 text-sm text-red-300 hover:bg-red-500/10"
            >
              Sign out
            </button>
          )}
        </div>
      </dialog>
    </>
  );
}
