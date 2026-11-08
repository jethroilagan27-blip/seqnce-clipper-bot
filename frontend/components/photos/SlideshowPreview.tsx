"use client";

import { useCallback, useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import OverlayLayer from "@/components/overlay/OverlayLayer";
import { formatTime } from "@/lib/timeline";
import type { TextOverlay } from "@/lib/overlays";
import { SIZE_RATIO, perPhoto, photoUrl, type PhotoItem, type PhotoSettings } from "./photosApi";

export type SlideshowHandle = { seek: (seconds: number) => void; pause: () => void };

type Props = {
  projectId: string | null;
  photos: PhotoItem[];
  settings: PhotoSettings;
  musicDuration: number | null;
  musicSrc: string | null;
  texts: TextOverlay[];
  selectedTextId: string | null;
  onSelectText: (id: string | null) => void;
  onMoveText: (id: string, x: number, y: number) => void;
  ref?: Ref<SlideshowHandle>;
};

const ZOOM = 0.08;
const FADE = 0.15;

// Plays the photos in the browser: photo order, time per photo, zoom, fades, your music and your texts.
// It is a close preview, not the render (the final video is made by FFmpeg with the same numbers).
export default function SlideshowPreview({ projectId, photos, settings, musicDuration, musicSrc, texts, selectedTextId, onSelectText, onMoveText, ref }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const tRef = useRef(0);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);

  const n = photos.length;
  const per = perPhoto(settings, n, musicDuration);
  const total = per * n;
  const shownT = Math.min(t, total);
  const index = n ? Math.min(Math.floor(shownT / per), n - 1) : 0;
  const local = shownT - index * per;
  const progress = per ? local / per : 0;
  const ratio = SIZE_RATIO[settings.size];

  const syncAudio = useCallback(
    (seconds: number) => {
      const a = audioRef.current;
      if (!a || !a.duration || !isFinite(a.duration)) return;
      a.currentTime = seconds % a.duration;
    },
    [],
  );

  const seek = useCallback(
    (seconds: number) => {
      const clamped = Math.max(0, Math.min(seconds, total));
      tRef.current = clamped;
      setT(clamped);
      syncAudio(clamped);
    },
    [total, syncAudio],
  );

  const pause = useCallback(() => {
    audioRef.current?.pause();
    setPlaying(false);
  }, []);

  useImperativeHandle(ref, () => ({ seek, pause }), [seek, pause]);

  useEffect(() => {
    const a = audioRef.current;
    if (a) a.volume = settings.music_volume;
  }, [settings.music_volume, musicSrc]);

  // advance the clock while playing
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    const step = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      tRef.current += dt;
      if (tRef.current >= total) {
        tRef.current = total;
        setT(total);
        pause();
        return;
      }
      setT(tRef.current);
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing, total, pause]);

  function toggle() {
    if (playing) return pause();
    if (!n) return;
    if (tRef.current >= total - 0.05) seek(0);
    const a = audioRef.current;
    if (a && musicSrc) {
      syncAudio(tRef.current);
      a.play().catch(() => {}); // the picture still plays if the browser refuses audio
    }
    setPlaying(true);
  }

  // dip to black at both ends of each photo, like the render
  const edge = settings.fade && per >= 0.7 ? Math.min(local / FADE, (per - local) / FADE, 1) : 1;
  const scale = settings.zoom ? 1 + ZOOM * (index % 2 === 0 ? progress : 1 - progress) : 1;
  const cur = n && projectId ? photoUrl(projectId, photos[index].id, "preview") : null;
  const next = n && projectId && index + 1 < n ? photoUrl(projectId, photos[index + 1].id, "preview") : null;

  return (
    <div className="space-y-2">
      <div
        className="relative mx-auto overflow-hidden rounded-2xl border border-white/10 bg-black"
        style={{ aspectRatio: String(ratio), width: `min(100%, calc(70vh * ${ratio}))`, containerType: "inline-size" }}
      >
        {cur ? (
          <div className="absolute inset-0" style={{ opacity: Math.max(edge, 0), transform: `scale(${scale})` }}>
            {settings.fill === "blur" && (
              // eslint-disable-next-line @next/next/no-img-element -- server-made preview image
              <img src={cur} alt="" className="absolute inset-0 h-full w-full object-cover" style={{ filter: "blur(26px) brightness(0.55)", transform: "scale(1.2)" }} />
            )}
            {/* eslint-disable-next-line @next/next/no-img-element -- server-made preview image */}
            <img src={cur} alt={`Photo ${index + 1} of ${n}`} className={`absolute inset-0 h-full w-full ${settings.fill === "crop" ? "object-cover" : "object-contain"}`} />
          </div>
        ) : (
          <p className="absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-white/40">Add photos and they will play here.</p>
        )}
        {/* eslint-disable-next-line @next/next/no-img-element -- warms the browser cache for the next photo */}
        {next && <img src={next} alt="" className="hidden" />}

        <OverlayLayer texts={texts} time={shownT} total={total} selectedId={selectedTextId} onMove={onMoveText} onSelect={onSelectText} />
      </div>

      {musicSrc && <audio ref={audioRef} src={musicSrc} loop preload="auto" />}

      <div className="mx-auto flex items-center gap-2" style={{ width: `min(100%, calc(70vh * ${ratio}))` }}>
        <button
          onClick={toggle}
          disabled={!n}
          aria-label={playing ? "Pause preview" : "Play preview"}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/10 text-sm hover:bg-white/20 disabled:opacity-40"
        >
          {playing ? "❚❚" : "▶"}
        </button>
        <input
          type="range"
          min={0}
          max={Math.max(total, 0.1)}
          step={0.05}
          value={shownT}
          onChange={(e) => seek(Number(e.target.value))}
          aria-label="Preview position"
          className="min-w-0 flex-1 accent-violet-500"
        />
        <span className="shrink-0 text-xs tabular-nums text-white/60">
          {formatTime(shownT)} / {formatTime(total)}
        </span>
      </div>
      {n > 0 && (
        <p className="text-center text-xs text-white/40">
          Photo {index + 1} of {n} · {per.toFixed(1)} s each{musicSrc ? " · music on" : ""}
        </p>
      )}
    </div>
  );
}
