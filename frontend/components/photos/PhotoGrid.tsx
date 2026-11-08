"use client";

import { useState } from "react";
import { naturalByName, photoUrl, type PhotoItem } from "./photosApi";

type Props = {
  projectId: string;
  photos: PhotoItem[];
  disabled?: boolean;
  /** The new order of ALL photos that should stay (photos left out are deleted). */
  onReorder: (ids: string[]) => void;
};

function move<T>(list: T[], from: number, to: number): T[] {
  const next = list.slice();
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

// The photos in the order they'll appear. Drag to reorder, or use the arrows; the × removes one.
export default function PhotoGrid({ projectId, photos, disabled, onReorder }: Props) {
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const ids = photos.map((p) => p.id);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-white/60">
        <span>
          {photos.length} photo{photos.length === 1 ? "" : "s"}. Drag to reorder.
        </span>
        <span className="ml-auto flex gap-1.5">
          <button
            disabled={disabled || photos.length < 2}
            onClick={() => onReorder([...photos].sort(naturalByName).map((p) => p.id))}
            className="rounded-md border border-white/15 px-2 py-1 hover:bg-white/5 disabled:opacity-40"
          >
            Sort by name
          </button>
          <button
            disabled={disabled || photos.length < 2}
            onClick={() => onReorder([...photos].sort((a, b) => (a.taken_at ?? "￿").localeCompare(b.taken_at ?? "￿") || naturalByName(a, b)).map((p) => p.id))}
            className="rounded-md border border-white/15 px-2 py-1 hover:bg-white/5 disabled:opacity-40"
            title="Uses the date stored in the photo (when it was taken)"
          >
            Sort by date taken
          </button>
          <button
            disabled={disabled || photos.length < 2}
            onClick={() => onReorder(ids.slice().reverse())}
            className="rounded-md border border-white/15 px-2 py-1 hover:bg-white/5 disabled:opacity-40"
          >
            Reverse
          </button>
        </span>
      </div>

      <ol className="grid max-h-[28rem] grid-cols-3 gap-2 overflow-y-auto pr-1 sm:grid-cols-4">
        {photos.map((p, i) => (
          <li
            key={p.id}
            draggable={!disabled}
            onDragStart={(e) => {
              setDragging(p.id);
              e.dataTransfer.effectAllowed = "move";
              e.dataTransfer.setData("text/plain", p.id);
            }}
            onDragOver={(e) => {
              if (dragging && dragging !== p.id) {
                e.preventDefault();
                setOver(p.id);
              }
            }}
            onDragLeave={() => setOver((o) => (o === p.id ? null : o))}
            onDrop={(e) => {
              e.preventDefault();
              const from = ids.indexOf(dragging ?? "");
              if (from >= 0 && dragging !== p.id) onReorder(move(ids, from, i));
              setDragging(null);
              setOver(null);
            }}
            onDragEnd={() => {
              setDragging(null);
              setOver(null);
            }}
            className={`group relative aspect-square overflow-hidden rounded-lg border bg-[#15151c] ${
              over === p.id ? "border-violet-400" : "border-white/10"
            } ${dragging === p.id ? "opacity-40" : ""}`}
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- small server-made thumbnail */}
            <img src={photoUrl(projectId, p.id, "thumb")} alt={p.name ?? `Photo ${i + 1}`} loading="lazy" draggable={false} className="h-full w-full object-cover" />
            <span className="absolute left-1 top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-black/70 px-1 text-[10px] font-bold">{i + 1}</span>
            {!disabled && (
              <div className="absolute inset-x-0 bottom-0 flex items-center justify-between bg-black/70 px-1 py-0.5 opacity-0 transition group-focus-within:opacity-100 group-hover:opacity-100">
                <button aria-label={`Move photo ${i + 1} earlier`} disabled={i === 0} onClick={() => onReorder(move(ids, i, i - 1))} className="px-1.5 text-sm disabled:opacity-30">
                  ←
                </button>
                <button aria-label={`Remove photo ${i + 1}`} onClick={() => onReorder(ids.filter((x) => x !== p.id))} className="px-1.5 text-sm text-red-300">
                  ×
                </button>
                <button aria-label={`Move photo ${i + 1} later`} disabled={i === photos.length - 1} onClick={() => onReorder(move(ids, i, i + 1))} className="px-1.5 text-sm disabled:opacity-30">
                  →
                </button>
              </div>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
