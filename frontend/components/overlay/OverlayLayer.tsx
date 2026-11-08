"use client";

import { useRef, useState } from "react";
import { clamp01, snapCenter, visibleAt, wrapText, type TextOverlay } from "@/lib/overlays";

type Props = {
  texts: TextOverlay[];
  /** Position in the finished video (s), and its length: decides which texts are on screen. */
  time: number;
  total: number;
  selectedId?: string | null;
  /** Drag and keyboard-nudge are on only when this is given. */
  onMove?: (id: string, x: number, y: number) => void;
  onSelect?: (id: string | null) => void;
};

/** Draws the user's texts over a frame. The parent must be `position: relative` with `container-type: inline-size`
 *  (the font sizes are `cqw` units = % of the frame width, exactly what the renderer uses). */
export default function OverlayLayer({ texts, time, total, selectedId = null, onMove, onSelect }: Props) {
  const layer = useRef<HTMLDivElement>(null);
  const drag = useRef<{ id: string; dx: number; dy: number } | null>(null);
  const [guide, setGuide] = useState<{ x: boolean; y: boolean }>({ x: false, y: false });
  const editable = !!onMove;

  function frameRect() {
    return layer.current!.getBoundingClientRect();
  }

  return (
    <div
      ref={layer}
      className="absolute inset-0"
      onPointerDown={(e) => {
        if (e.target === e.currentTarget) onSelect?.(null);
      }}
      style={{ pointerEvents: editable ? "auto" : "none" }}
    >
      {guide.x && <div className="pointer-events-none absolute inset-y-0 left-1/2 w-px bg-fuchsia-400/80" />}
      {guide.y && <div className="pointer-events-none absolute inset-x-0 top-1/2 h-px bg-fuchsia-400/80" />}

      {texts.map((t) => {
        const on = visibleAt(t, time, total);
        const selected = t.id === selectedId;
        if (!on && !(editable && selected)) return null; // a selected text stays visible (faded) so it can be placed
        return (
          <div
            key={t.id}
            role={editable ? "button" : undefined}
            tabIndex={editable ? 0 : undefined}
            aria-label={editable ? `Text: ${t.text.slice(0, 40)}. Drag to move, or use the arrow keys.` : undefined}
            onPointerDown={(e) => {
              if (!editable) return;
              e.stopPropagation();
              onSelect?.(t.id);
              e.currentTarget.setPointerCapture(e.pointerId);
              const r = frameRect();
              drag.current = { id: t.id, dx: (e.clientX - r.left) / r.width - t.x, dy: (e.clientY - r.top) / r.height - t.y };
            }}
            onPointerMove={(e) => {
              const d = drag.current;
              if (!d || d.id !== t.id || !e.currentTarget.hasPointerCapture(e.pointerId)) return;
              const r = frameRect();
              const x = snapCenter(clamp01((e.clientX - r.left) / r.width - d.dx));
              const y = snapCenter(clamp01((e.clientY - r.top) / r.height - d.dy));
              setGuide({ x: x === 0.5, y: y === 0.5 });
              onMove?.(t.id, x, y);
            }}
            onPointerUp={(e) => {
              drag.current = null;
              setGuide({ x: false, y: false });
              e.currentTarget.releasePointerCapture(e.pointerId);
            }}
            onKeyDown={(e) => {
              const step = e.shiftKey ? 0.05 : 0.01;
              const dx = e.key === "ArrowRight" ? step : e.key === "ArrowLeft" ? -step : 0;
              const dy = e.key === "ArrowDown" ? step : e.key === "ArrowUp" ? -step : 0;
              if (!dx && !dy) return;
              e.preventDefault();
              onMove?.(t.id, clamp01(t.x + dx), clamp01(t.y + dy));
            }}
            className={editable ? "cursor-move touch-none outline-none focus-visible:ring-2 focus-visible:ring-white/70" : ""}
            style={{
              position: "absolute",
              left: `${t.x * 100}%`,
              top: `${t.y * 100}%`,
              transform: "translate(-50%, -50%)",
              fontSize: `${t.size}cqw`,
              lineHeight: 1.15,
              fontFamily: "Arial, Helvetica, sans-serif",
              fontWeight: t.bold ? 800 : 400,
              textAlign: "center",
              whiteSpace: "pre",
              color: t.color,
              opacity: on ? 1 : 0.35,
              ...(t.style === "box"
                ? { background: "rgba(0,0,0,0.6)", padding: "0.12em 0.28em", borderRadius: "0.12em" }
                : t.style === "outline"
                  ? { WebkitTextStroke: "0.09em rgba(0,0,0,0.95)", paintOrder: "stroke fill" as const, textShadow: "0 0.03em 0.04em rgba(0,0,0,0.5)" }
                  : {}),
              ...(selected && editable ? { outline: "2px dashed rgba(255,255,255,0.9)", outlineOffset: "0.15em" } : {}),
            }}
          >
            {wrapText(t.text, t.size)}
          </div>
        );
      })}
    </div>
  );
}
