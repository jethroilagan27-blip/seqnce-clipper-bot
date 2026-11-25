"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { requestHome } from "@/lib/home";
import type { Section } from "./Shell";

const icon = (path: ReactNode) => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {path}
  </svg>
);

const TABS = [
  {
    href: "/",
    label: "Edit",
    on: (s?: Section) => s === "video" || s === "photos" || s === "studio",
    icon: icon(
      <>
        <circle cx="6" cy="7" r="2.6" />
        <circle cx="6" cy="17" r="2.6" />
        <path d="M8.3 8.4 20 17M8.3 15.6 20 7" />
      </>,
    ),
  },
  {
    href: "/library",
    label: "Library",
    on: (s?: Section) => s === "library",
    icon: icon(
      <>
        <rect x="3" y="4" width="18" height="16" rx="3" />
        <path d="m10 9 5 3-5 3z" />
      </>,
    ),
  },
  {
    href: "/me",
    label: "Me",
    on: (s?: Section) => s === "me" || s === "admin",
    icon: icon(
      <>
        <circle cx="12" cy="8" r="4" />
        <path d="M4.5 20c1.4-3.6 4.2-5.4 7.500-5.400s6.100 1.800 7.500 5.400" />
      </>,
    ),
  },
];

/** The phone's tab bar, fixed to the bottom of the screen: Edit · Library · Me. */
export default function BottomNav({ section }: { section?: Section }) {
  return (
    <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-40 border-t border-white/10 bg-panel pb-[env(safe-area-inset-bottom)] sm:hidden">
      <ul className="mx-auto grid max-w-xl grid-cols-3">
        {TABS.map((t) => {
          const on = t.on(section);
          return (
            <li key={t.href}>
              <Link
                href={t.href}
                aria-current={on ? "page" : undefined}
                onClick={t.href === "/" ? requestHome : undefined}
                className={`flex flex-col items-center gap-0.5 py-2.5 text-[11px] ${on ? "font-semibold text-violet-300" : "text-white/50"}`}
              >
                {t.icon}
                {t.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
