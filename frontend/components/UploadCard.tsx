"use client";

import { useEffect, useRef, useState } from "react";
import { MAX_INSTRUCTIONS, MAX_UPLOAD_MB, formatBytes, getMusic, type EditSettings } from "@/lib/api";

type Props = {
  busy: boolean;
  uploadProgress: number | null; // 0..1 while uploading
  error: string | null;
  onStart: (file: File, settings: EditSettings) => void;
  onCancel: () => void;
};

function validate(file: File): string | null {
  if (!file.name.toLowerCase().endsWith(".mp4")) return "Only .mp4 files are supported right now.";
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `That file is over ${MAX_UPLOAD_MB} MB.`;
  if (file.size === 0) return "That file is empty.";
  return null;
}

function Toggle(props: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label
      className={`flex items-center justify-between gap-4 rounded-lg border border-white/10 px-4 py-3 ${
        props.disabled ? "opacity-50" : "cursor-pointer hover:border-white/25"
      }`}
    >
      <span>
        <span className="block text-sm font-medium">{props.label}</span>
        <span className="block text-xs text-white/50">{props.hint}</span>
      </span>
      <input
        type="checkbox"
        className="h-5 w-5 accent-violet-500"
        checked={props.checked}
        disabled={props.disabled}
        onChange={(e) => props.onChange(e.target.checked)}
      />
    </label>
  );
}

export default function UploadCard({ busy, uploadProgress, error, onStart, onCancel }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [tracks, setTracks] = useState<string[] | null>(null);
  const [settings, setSettings] = useState<EditSettings>({
    target_duration: 45,
    captions: true,
    remove_silence: true,
    background_music: false,
    hook: true,
    instructions: "",
  });

  const wantsMusic = settings.background_music;
  useEffect(() => {
    if (!wantsMusic) return;
    let cancelled = false;
    getMusic()
      .then((m) => {
        if (cancelled) return;
        setTracks(m.tracks);
        setSettings((s) => ({ ...s, music_track: s.music_track ?? m.tracks[0] ?? null }));
      })
      .catch(() => !cancelled && setTracks([]));
    return () => {
      cancelled = true;
    };
  }, [wantsMusic]);

  function pick(f: File | undefined) {
    if (!f) return;
    const problem = validate(f);
    setFileError(problem);
    setFile(problem ? null : f);
  }

  const shownError = fileError ?? error;

  return (
    <div className="space-y-6">
      <div
        role="button"
        tabIndex={0}
        aria-label="Choose a video to upload"
        onClick={() => !busy && inputRef.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && !busy) inputRef.current?.click();
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (!busy) pick(e.dataTransfer.files[0]);
        }}
        className={`flex flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-6 py-14 text-center transition ${
          dragging ? "border-violet-400 bg-violet-500/10" : "border-white/15 bg-white/[0.03]"
        } ${busy ? "cursor-default" : "cursor-pointer hover:border-white/40"}`}
      >
        <input
          ref={inputRef}
          type="file"
          accept="video/mp4,.mp4"
          className="hidden"
          onChange={(e) => pick(e.target.files?.[0])}
        />
        {file ? (
          <>
            <p className="text-lg font-medium break-all">{file.name}</p>
            <p className="text-sm text-white/50">{formatBytes(file.size)}</p>
            {!busy && <p className="text-xs text-white/40">Click or drop to replace</p>}
          </>
        ) : (
          <>
            <p className="text-lg font-medium">Drag &amp; drop your video here</p>
            <p className="text-sm text-white/50">or click to browse</p>
            <p className="mt-2 text-xs text-white/40">
              MP4 only · up to {MAX_UPLOAD_MB} MB · best with talking-head footage
            </p>
          </>
        )}
      </div>

      <div className="space-y-3">
        <div className="rounded-lg border border-white/10 px-4 py-3">
          <div className="flex items-baseline justify-between">
            <span className="text-sm font-medium">Target length</span>
            <span className="text-sm tabular-nums text-violet-300">{settings.target_duration}s</span>
          </div>
          <input
            type="range"
            min={15}
            max={90}
            step={5}
            disabled={busy}
            value={settings.target_duration}
            onChange={(e) => setSettings({ ...settings, target_duration: Number(e.target.value) })}
            className="mt-2 w-full accent-violet-500"
            aria-label="Target length in seconds"
          />
          <div className="flex justify-between text-xs text-white/40">
            <span>15s</span>
            <span>90s</span>
          </div>
        </div>
        <div className="rounded-lg border border-white/10 px-4 py-3">
          <label htmlFor="instructions" className="flex items-baseline justify-between">
            <span className="text-sm font-medium">Tell the editor what you want (optional)</span>
            <span className="text-xs tabular-nums text-white/40">
              {settings.instructions.length}/{MAX_INSTRUCTIONS}
            </span>
          </label>
          <textarea
            id="instructions"
            rows={3}
            maxLength={MAX_INSTRUCTIONS}
            disabled={busy}
            value={settings.instructions}
            onChange={(e) => setSettings({ ...settings, instructions: e.target.value })}
            placeholder="e.g. Focus on the pricing tips, skip the intro story, make the hook a question."
            className="mt-2 w-full resize-none rounded-md border border-white/10 bg-[#15151c] px-3 py-2 text-sm placeholder:text-white/30 focus:border-violet-400 focus:outline-none"
          />
        </div>
        <Toggle
          label="Hook title"
          hint="Big coloured headline at the top for the first seconds"
          checked={settings.hook}
          disabled={busy}
          onChange={(v) => setSettings({ ...settings, hook: v })}
        />
        <Toggle
          label="Captions"
          hint="Burn readable subtitles into the video"
          checked={settings.captions}
          disabled={busy}
          onChange={(v) => setSettings({ ...settings, captions: v })}
        />
        <Toggle
          label="Trim long pauses"
          hint="Shorten dead air but keep natural pacing"
          checked={settings.remove_silence}
          disabled={busy}
          onChange={(v) => setSettings({ ...settings, remove_silence: v })}
        />
        <Toggle
          label="Background music"
          hint="Mixed quietly under your voice"
          checked={settings.background_music}
          disabled={busy}
          onChange={(v) => setSettings({ ...settings, background_music: v })}
        />
        {wantsMusic &&
          (tracks && tracks.length > 0 ? (
            <select
              value={settings.music_track ?? ""}
              disabled={busy}
              onChange={(e) => setSettings({ ...settings, music_track: e.target.value })}
              className="w-full rounded-lg border border-white/10 bg-[#15151c] px-4 py-3 text-sm"
              aria-label="Music track"
            >
              {tracks.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          ) : (
            tracks && (
              <p className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-xs text-amber-100">
                No music found. Put .mp3 / .wav files you have the rights to use in the project&apos;s{" "}
                <code>storage/music</code> folder, then re-toggle this option.
              </p>
            )
          ))}
      </div>

      {shownError && (
        <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {shownError}
        </p>
      )}

      {uploadProgress !== null ? (
        <div className="space-y-2">
          <div className="h-2 overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full bg-violet-500 transition-[width]"
              style={{ width: `${Math.round(uploadProgress * 100)}%` }}
            />
          </div>
          <div className="flex items-center justify-between text-sm text-white/60">
            <span>Uploading… {Math.round(uploadProgress * 100)}%</span>
            <button onClick={onCancel} className="text-white/60 underline hover:text-white">
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          disabled={!file || busy}
          onClick={() => file && onStart(file, settings)}
          className="w-full rounded-xl bg-violet-600 px-6 py-3.5 font-semibold text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-white/30"
        >
          Start editing
        </button>
      )}
    </div>
  );
}
