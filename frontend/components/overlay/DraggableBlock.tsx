"use client";

import type { CSSProperties, ReactNode } from "react";
import { clamp01, snapCenter } from "@/lib/overlays";

type Props = {
  /** Where the user dragged it (centre, fractions of the frame); null = the usual spot. */
  pos: { x: number; y: number } | null;
  /** Dragging is on only when this is given. */
  onMove?: (x: number, y: number) => void;
  /** Placement when it hasn't been dragged (e.g. captions: left/right 8 %, bottom 22 %). */
  defaultStyle: CSSProperties;
  style?: CSSProperties;
  label: string;
  children: ReactNode;
};

// Captions and the title keep their usual place until you drag them. Must sit inside an element that has
// `data-frame` (the video frame) and `container-type: inline-size`.
export default function DraggableBlock({ pos, onMove, defaultStyle, style, label, children }: Props) {
  const editable = !!onMove;
  const frameOf = (el: HTMLElement) => el.closest("[data-frame]")!.getBoundingClientRect();

  return (
    <div
      role={editable ? "button" : undefined}
      aria-label={editable ? `${label}. Drag to move.` : undefined}
      title={editable ? `Drag to move the ${label.toLowerCase()}` : undefined}
      onPointerDown={(e) => {
        if (!onMove) return;
        e.stopPropagation();
        const f = frameOf(e.currentTarget);
        const r = e.currentTarget.getBoundingClientRect();
        // remember where inside the block the pointer grabbed it, so it doesn't jump to the pointer
        e.currentTarget.dataset.dx = String((e.clientX - f.left) / f.width - (r.left + r.width / 2 - f.left) / f.width);
        e.currentTarget.dataset.dy = String((e.clientY - f.top) / f.height - (r.top + r.height / 2 - f.top) / f.height);
        e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => {
        if (!onMove || !e.currentTarget.hasPointerCapture(e.pointerId)) return;
        const f = frameOf(e.currentTarget);
        onMove(
          snapCenter(clamp01((e.clientX - f.left) / f.width - Number(e.currentTarget.dataset.dx ?? 0))),
          snapCenter(clamp01((e.clientY - f.top) / f.height - Number(e.currentTarget.dataset.dy ?? 0))),
        );
      }}
      onPointerUp={(e) => e.currentTarget.releasePointerCapture(e.pointerId)}
      style={{
        position: "absolute",
        pointerEvents: editable ? "auto" : "none",
        cursor: editable ? "move" : undefined,
        touchAction: "none",
        ...(pos
          ? { left: `${pos.x * 100}%`, top: `${pos.y * 100}%`, transform: "translate(-50%, -50%)", width: "max-content", maxWidth: "84%" }
          : defaultStyle),
        ...style,
      }}
    >
      {children}
    </div>
  );
}
