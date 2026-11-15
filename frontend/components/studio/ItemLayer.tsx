"use client";

import { useRef } from "react";
import { clamp01, snapCenter } from "@/lib/overlays";

export type Item = {
  id: string;
  /** Centre, as fractions of the frame. */
  x: number;
  y: number;
  /** Size as fractions of the frame's width / height. For a picture, height is left out (it follows the picture's shape). */
  w: number;
  h?: number;
  kind: "picture" | "rect" | "ellipse" | "pin";
  src?: string;
  color?: string;
  label: string;
};

type Props = {
  items: Item[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onMove: (id: string, x: number, y: number) => void;
};

/** Boxes laid over a frame that can be dragged (or moved with the arrow keys). The parent is `position: relative`. */
export default function ItemLayer({ items, selectedId, onSelect, onMove }: Props) {
  const layer = useRef<HTMLDivElement>(null);
  const drag = useRef<{ id: string; dx: number; dy: number } | null>(null);

  return (
    <div ref={layer} className="absolute inset-0" onPointerDown={(e) => e.target === e.currentTarget && onSelect(null)}>
      {items.map((it) => {
        const selected = it.id === selectedId;
        const outline = selected ? "2px dashed #fff" : `1.5px dashed ${it.color ?? "rgba(255,255,255,0.6)"}`;
        return (
          <div
            key={it.id}
            role="button"
            tabIndex={0}
            aria-label={`${it.label}. Drag to move, or use the arrow keys.`}
            title={it.label}
            className="absolute cursor-move touch-none outline-none focus-visible:ring-2 focus-visible:ring-white/70"
            style={{
              left: `${it.x * 100}%`,
              top: `${it.y * 100}%`,
              width: `${it.w * 100}%`,
              height: it.kind === "picture" ? undefined : `${(it.h ?? it.w) * 100}%`,
              aspectRatio: it.kind === "pin" ? "1" : undefined,
              transform: it.kind === "pin" ? "translate(-50%, -100%)" : "translate(-50%, -50%)", // a pin's point is its (x, y)
              outline,
              outlineOffset: 2,
              borderRadius: it.kind === "ellipse" || it.kind === "pin" ? "50%" : 2,
              background: it.kind === "picture" ? undefined : `${it.color ?? "#fff"}33`,
            }}
            onPointerDown={(e) => {
              e.stopPropagation();
              onSelect(it.id);
              e.currentTarget.setPointerCapture(e.pointerId);
              const r = layer.current!.getBoundingClientRect();
              drag.current = { id: it.id, dx: (e.clientX - r.left) / r.width - it.x, dy: (e.clientY - r.top) / r.height - it.y };
            }}
            onPointerMove={(e) => {
              const d = drag.current;
              if (!d || d.id !== it.id || !e.currentTarget.hasPointerCapture(e.pointerId)) return;
              const r = layer.current!.getBoundingClientRect();
              onMove(it.id, snapCenter(clamp01((e.clientX - r.left) / r.width - d.dx)), snapCenter(clamp01((e.clientY - r.top) / r.height - d.dy)));
            }}
            onPointerUp={(e) => {
              drag.current = null;
              e.currentTarget.releasePointerCapture(e.pointerId);
            }}
            onKeyDown={(e) => {
              const step = e.shiftKey ? 0.05 : 0.01;
              const dx = e.key === "ArrowRight" ? step : e.key === "ArrowLeft" ? -step : 0;
              const dy = e.key === "ArrowDown" ? step : e.key === "ArrowUp" ? -step : 0;
              if (!dx && !dy) return;
              e.preventDefault();
              onMove(it.id, clamp01(it.x + dx), clamp01(it.y + dy));
            }}
          >
            {it.kind === "picture" && it.src && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={it.src} alt="" draggable={false} className="pointer-events-none block w-full select-none" />
            )}
          </div>
        );
      })}
    </div>
  );
}
