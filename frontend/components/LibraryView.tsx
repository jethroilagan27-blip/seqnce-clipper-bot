"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ApiError, JOB_STORAGE_KEY, formatDuration, getLibrary, mediaUrl, type Library, type LibraryItem } from "@/lib/api";
import { STUDIO_STORAGE_KEY } from "@/lib/studio";
import type { AccountInfo } from "./AuthGate";
import { PROJECT_STORAGE_KEY } from "./photos/photosApi";
import Shell, { BetaBadge, hasStudio } from "./Shell";

const KIND = { video: "Video", photos: "Photos", studio: "Studio" } as const;
const EDITOR = { video: { key: JOB_STORAGE_KEY, page: "/" }, photos: { key: PROJECT_STORAGE_KEY, page: "/photos" }, studio: { key: STUDIO_STORAGE_KEY, page: "/studio" } };
const POLL_MS = 5000; // while something is still being made

const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });

/** Open the item in the editor it came from (each editor reopens the id it finds saved). A full load: nothing stale stays behind. */
function openInEditor(item: LibraryItem) {
  const target = EDITOR[item.kind];
  try {
    localStorage.setItem(target.key, item.id);
  } catch {
    /* storage unavailable: the editor opens on its latest */
  }
  window.location.assign(target.page);
}

function Player({ item, canEdit, onClose }: { item: LibraryItem; canEdit: boolean; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = dialog.current;
    if (d && !d.open) d.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      aria-label={item.title}
      onClose={onClose}
      onClick={(e) => e.target === e.currentTarget && dialog.current?.close()}
      className="m-auto w-[min(26rem,94vw)] rounded-2xl border border-white/15 bg-panel p-0 text-foreground backdrop:bg-black/75"
    >
      <div className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <p className="min-w-0 break-words text-sm font-semibold">{item.title}</p>
          <button type="button" aria-label="Close" onClick={() => dialog.current?.close()} className="-mr-1 -mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg hover:bg-white/5">
            ✕
          </button>
        </div>
        {item.video ? (
          <video src={mediaUrl(item.video)} controls playsInline autoPlay className="mx-auto max-h-[60vh] w-full rounded-xl bg-black" />
        ) : (
          <p className="rounded-lg border border-white/10 px-3 py-6 text-center text-sm text-white/60">Still being made. It will appear here when it&apos;s ready.</p>
        )}
        <div className="grid grid-cols-2 gap-2">
          {item.download && (
            <a href={mediaUrl(item.download)} download className="rounded-xl bg-violet-600 px-4 py-3 text-center text-sm font-semibold text-white hover:bg-violet-500">
              Download
            </a>
          )}
          {canEdit && (
            <button type="button" onClick={() => openInEditor(item)} className="rounded-xl border border-white/15 px-4 py-3 text-sm hover:bg-white/5">
              {item.video ? "Edit" : "See progress"}
            </button>
          )}
        </div>
      </div>
    </dialog>
  );
}

// Every video this account has made, from all three modes.
export default function LibraryView({ account }: { account: AccountInfo }) {
  const [data, setData] = useState<Library | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const working = !!data?.items.some((i) => i.status === "working");

  useEffect(() => {
    let cancelled = false;
    getLibrary()
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Couldn't load your videos.");
      });
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  useEffect(() => {
    if (!working) return;
    const t = setInterval(() => setNonce((n) => n + 1), POLL_MS);
    return () => clearInterval(t);
  }, [working]);

  const open = data?.items.find((i) => i.id === openId) ?? null;
  const keep = data?.keep_days.video;

  return (
    <Shell user={account.user} onSignOut={account.user ? account.signOut : undefined} wide section="library">
      <div className="space-y-4">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-lg font-semibold">Library</h2>
          <button type="button" onClick={() => setNonce((n) => n + 1)} className="text-sm text-violet-300 underline">
            Refresh
          </button>
        </div>
        {keep && (
          <p className="text-xs text-white/50">
            Videos are removed {keep} days after their last change (Studio projects after {data!.keep_days.studio}). Download the ones you want to keep.
          </p>
        )}
        {error && (
          <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200">
            {error}
          </p>
        )}
        {!data && !error && <p className="text-sm text-white/50">Loading…</p>}
        {data && data.items.length === 0 && (
          <div className="space-y-4 rounded-2xl border border-dashed border-white/15 px-6 py-12 text-center">
            <p className="text-sm text-white/60">No videos yet. The ones you edit will show up here.</p>
            <Link href="/" className="inline-block rounded-xl bg-violet-600 px-5 py-3 text-sm font-semibold text-white hover:bg-violet-500">
              + New video
            </Link>
          </div>
        )}
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4" aria-label="Your videos">
          {data?.items.map((item) => (
            <li key={`${item.kind}-${item.id}`}>
              <button type="button" onClick={() => setOpenId(item.id)} className="block w-full text-left">
                <span className="on-dark relative block aspect-[3/4] overflow-hidden rounded-xl bg-black">
                  {item.thumb && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={mediaUrl(item.thumb)} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover" onError={(e) => (e.currentTarget.style.display = "none")} />
                  )}
                  <span className="absolute left-1.5 top-1.5 rounded-full bg-black/70 px-2 py-0.5 text-[10px] font-semibold">{KIND[item.kind]}</span>
                  {item.status === "working" ? (
                    <span className="absolute inset-x-0 bottom-0 bg-black/70 py-1.5 text-center text-xs">Being made…</span>
                  ) : (
                    item.duration !== null && <span className="absolute bottom-1.5 right-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[11px] tabular-nums">{formatDuration(item.duration)}</span>
                  )}
                </span>
                <span className="mt-1.5 block truncate text-sm" title={item.title}>
                  {item.title}
                </span>
                <span className="flex items-center gap-1.5 text-xs text-white/45">
                  {day(item.updated_at)}
                  {item.kind === "studio" && <BetaBadge />}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      {open && <Player key={open.id} item={open} canEdit={open.kind !== "studio" || hasStudio(account.user)} onClose={() => setOpenId(null)} />}
    </Shell>
  );
}
