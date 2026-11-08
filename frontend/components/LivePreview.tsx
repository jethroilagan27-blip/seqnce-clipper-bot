"use client";

import { useCallback, useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import DraggableBlock from "@/components/overlay/DraggableBlock";
import OverlayLayer from "@/components/overlay/OverlayLayer";
import { HOOK_CSS, originalUrl, type Pos, type TimelineSpec } from "@/lib/api";
import type { TextOverlay } from "@/lib/overlays";
import { cutIndexAtOut, formatTime, outToSource, pageAt, sourceToOut } from "@/lib/timeline";

export type PreviewHandle = {
  /** Jump to a position of the ORIGINAL video (the preview moves to the nearest kept part). */
  seekSource: (src: number) => void;
  /** Jump to a position of the FINISHED short. */
  seekOutput: (seconds: number) => void;
  pause: () => void;
};

type Props = {
  jobId: string;
  spec: TimelineSpec;
  /** Called while playing / seeking: source time, output time, playing. */
  onTime?: (src: number, out: number, playing: boolean) => void;
  ref?: Ref<PreviewHandle>;
  /** Draft values that replace what the server's spec says (so dragging is instant). undefined = use the spec. */
  captionPos?: Pos | null;
  hookPos?: Pos | null;
  texts?: TextOverlay[];
  /** Dragging captions / title / texts is on only when these are given. */
  onMoveBlock?: (kind: "caption" | "hook", x: number, y: number) => void;
  selectedTextId?: string | null;
  onSelectText?: (id: string | null) => void;
  onMoveText?: (id: string, x: number, y: number) => void;
};

// Plays the ORIGINAL video in the browser and jumps between the planned cuts. The cut list, caption
// pages and hook come from the server, computed by the same code that renders the final file, so
// this shows what the render will contain (minus encoder differences such as exact fonts).
export default function LivePreview({
  jobId, spec, onTime, ref, captionPos, hookPos, texts, onMoveBlock, selectedTextId, onSelectText, onMoveText,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const specRef = useRef(spec);
  const cutRef = useRef(0);
  const outRef = useRef(0);
  const lastPaint = useRef(0);
  const onTimeRef = useRef(onTime);
  const [playing, setPlaying] = useState(false);
  const [out, setOut] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    onTimeRef.current = onTime;
  }, [onTime]);

  // The cut list changed (a draft edit): stay at the same output time on the new timeline.
  useEffect(() => {
    specRef.current = spec;
    const v = videoRef.current;
    if (!v || !spec.cuts.length) return;
    const t = Math.min(outRef.current, spec.total);
    cutRef.current = cutIndexAtOut(spec.cuts, t);
    v.currentTime = outToSource(spec.cuts, t);
  }, [spec]);

  const report = useCallback((t: number, isPlaying: boolean, force = false) => {
    outRef.current = t;
    const now = performance.now();
    if (force || now - lastPaint.current > 70) {
      lastPaint.current = now;
      setOut(t);
    }
    const v = videoRef.current;
    onTimeRef.current?.(v ? v.currentTime : 0, t, isPlaying);
  }, []);

  const seekOut = useCallback(
    (t: number, isPlaying: boolean) => {
      const s = specRef.current;
      const v = videoRef.current;
      if (!v || !s.cuts.length) return;
      const clamped = Math.max(0, Math.min(t, s.total));
      cutRef.current = cutIndexAtOut(s.cuts, clamped);
      v.currentTime = outToSource(s.cuts, clamped);
      report(clamped, isPlaying, true);
    },
    [report],
  );

  const pause = useCallback(() => {
    videoRef.current?.pause();
    setPlaying(false);
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      seekSource: (src: number) => seekOut(sourceToOut(specRef.current.cuts, src), !!videoRef.current && !videoRef.current.paused),
      seekOutput: (seconds: number) => seekOut(seconds, !!videoRef.current && !videoRef.current.paused),
      pause,
    }),
    [seekOut, pause],
  );

  // While playing: hop over the parts that were cut out, and report the playhead.
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const step = () => {
      const v = videoRef.current;
      const s = specRef.current;
      if (v && s.cuts.length) {
        let i = Math.min(cutRef.current, s.cuts.length - 1);
        let c = s.cuts[i];
        const src = v.currentTime;
        if (src >= c.end - 0.04) {
          const next = s.cuts[i + 1];
          if (next) {
            i += 1;
            cutRef.current = i;
            c = next;
            if (Math.abs(next.start - src) > 0.08) v.currentTime = next.start;
          } else {
            v.pause();
            setPlaying(false);
            report(s.total, false, true);
            return;
          }
        } else if (src < c.start - 0.3 || src > c.end + 0.3) {
          const j = s.cuts.findIndex((x) => src >= x.start - 0.05 && src < x.end);
          if (j >= 0) {
            cutRef.current = j;
            c = s.cuts[j];
          }
        }
        report(Math.min(s.total, c.out_start + Math.max(0, v.currentTime - c.start)), true);
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing, report]);

  function toggle() {
    const v = videoRef.current;
    if (!v || !spec.cuts.length) return;
    if (playing) {
      pause();
      return;
    }
    if (outRef.current >= spec.total - 0.05) seekOut(0, false);
    v.play()
      .then(() => setPlaying(true))
      .catch(() => setFailed(true));
  }

  const t = Math.min(out, spec.total);
  const page = spec.captions_enabled ? pageAt(spec.pages, t) : null;
  const hook = spec.hook;
  const hookOn = hook.enabled && hook.text.trim() !== "" && t < hook.duration_s;
  const hookOpacity = Math.max(0, Math.min(1, t / 0.18, (hook.duration_s - t) / 0.3));

  // Same crop as the render: a 9:16 window centred on the speaker.
  const { width: sw, height: sh } = spec.source;
  const k = (16 / 9) * (sw / sh); // video width as a multiple of the 9:16 window's width
  const left = k >= 1 ? -Math.min(Math.max(spec.reframe.focus_x * k - 0.5, 0), k - 1) * 100 : 0;
  const videoStyle: React.CSSProperties =
    k >= 1
      ? { position: "absolute", top: 0, height: "100%", width: `${k * 100}%`, left: `${left}%`, maxWidth: "none" }
      : { position: "absolute", left: 0, width: "100%", top: "50%", transform: "translateY(-50%)" };

  const stroke = (w: number): React.CSSProperties => ({
    WebkitTextStroke: `${w}cqw #000`,
    paintOrder: "stroke fill",
    fontFamily: "Arial, Helvetica, sans-serif",
    textAlign: "center",
  });

  // Dragged positions and free texts: the draft's values when given (instant), otherwise what the server computed.
  const cPos = captionPos !== undefined ? captionPos : spec.captions_pos;
  const hPos = hookPos !== undefined ? hookPos : spec.hook.pos;
  const extraTexts = texts ?? spec.texts;
  const dragging = !!onMoveBlock;
  // while editing, captions / title stay grabbable (faded) even when none is on screen at this moment
  const showHook = hook.enabled && hook.text.trim() !== "" && (hookOn || dragging);
  const showCaption = spec.captions_enabled && (!!page || dragging);

  return (
    <div className="space-y-2">
      <div
        data-frame
        className="relative mx-auto overflow-hidden rounded-2xl border border-white/10 bg-black"
        style={{ aspectRatio: "9 / 16", width: "min(100%, calc(70vh * 9 / 16))", containerType: "inline-size" }}
      >
        <video
          ref={videoRef}
          src={originalUrl(jobId)}
          preload="auto"
          playsInline
          onClick={toggle}
          onError={() => setFailed(true)}
          onLoadedMetadata={() => seekOut(outRef.current, false)}
          style={videoStyle}
          aria-label="Live preview of the edit"
        />
        <OverlayLayer
          texts={extraTexts}
          time={t}
          total={spec.total}
          selectedId={selectedTextId}
          onMove={onMoveText}
          onSelect={onSelectText}
        />
        {showHook && (
          <DraggableBlock
            pos={hPos}
            label="Title"
            onMove={onMoveBlock && ((x, y) => onMoveBlock("hook", x, y))}
            defaultStyle={{ top: "11.5%", left: "8%", right: "8%" }}
            style={{
              ...stroke(1.2),
              fontSize: "10.5cqw",
              fontWeight: 900,
              lineHeight: 1.12,
              textTransform: "uppercase",
              color: HOOK_CSS[hook.color] ?? "#ffe600",
              opacity: hookOn ? hookOpacity : 0.4,
            }}
          >
            {hook.text}
          </DraggableBlock>
        )}
        {showCaption && (
          <DraggableBlock
            pos={cPos}
            label="Captions"
            onMove={onMoveBlock && ((x, y) => onMoveBlock("caption", x, y))}
            defaultStyle={{ bottom: "22%", left: "8%", right: "8%" }}
            style={{ ...stroke(0.9), fontSize: "7cqw", fontWeight: 800, lineHeight: 1.12, color: "#fff", opacity: page ? 1 : 0.4 }}
          >
            {page ? page.text : "Your captions show here"}
          </DraggableBlock>
        )}
        {failed && (
          <p className="absolute inset-x-4 top-1/2 -translate-y-1/2 rounded-lg bg-black/80 p-3 text-center text-xs text-red-200">
            The original video can&apos;t be played in the browser preview.
          </p>
        )}
      </div>

      <div className="mx-auto flex items-center gap-2" style={{ width: "min(100%, calc(70vh * 9 / 16))" }}>
        <button
          onClick={toggle}
          disabled={!spec.cuts.length}
          aria-label={playing ? "Pause preview" : "Play preview"}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/10 text-sm hover:bg-white/20 disabled:opacity-40"
        >
          {playing ? "❚❚" : "▶"}
        </button>
        <input
          type="range"
          min={0}
          max={Math.max(spec.total, 0.1)}
          step={0.05}
          value={t}
          onChange={(e) => seekOut(Number(e.target.value), playing)}
          aria-label="Preview position"
          className="min-w-0 flex-1 accent-violet-500"
        />
        <span className="shrink-0 text-xs tabular-nums text-white/60">
          {formatTime(t)} / {formatTime(spec.total)}
        </span>
      </div>
    </div>
  );
}
