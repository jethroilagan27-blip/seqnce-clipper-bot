"use client";

import { useEffect, useRef, useState } from "react";
import { MAX_INSTRUCTIONS, formatBytes, getMusic, getUploadConfig, type EditSettings } from "@/lib/api";
import { VIDEO_EXTENSIONS, baseName, folderOf, fromFileList, mergePicked, safeFromDataTransfer, splitByExtension, type Picked } from "@/lib/pickFiles";

type Props = {
  busy: boolean;
  uploadProgress: number | null; // 0..1 while uploading
  error: string | null;
  /** Set when the user's daily limit is used up; the upload button is disabled and this is shown. */
  blockedReason?: string | null;
  /** One video: the normal flow. */
  onStart: (file: File, settings: EditSettings) => void;
  /** Several videos (or a folder): they are edited one after another with the same settings. */
  onStartBatch: (items: Picked[], settings: EditSettings) => void;
  onCancel: () => void;
  /** Files already chosen on the start screen (phone: "+ New video"). Read once, when the card appears. */
  initialItems?: Picked[];
};

const MAX_BATCH = 100;

/** Add what was chosen to the list. Other kinds of file are named, not silently lost. */
function screen(already: Picked[], items: Picked[]): { picked: Picked[]; problem: string | null } {
  const { accepted, skipped } = splitByExtension(items, VIDEO_EXTENSIONS);
  const usable: Picked[] = [];
  const notes: string[] = [];
  for (const it of accepted) {
    const why = problemWith(it);
    if (why) notes.push(`${baseName(it.path)} (${why})`);
    else usable.push(it);
  }
  skipped.forEach((s) => notes.push(`${baseName(s.path)} (not a video)`));
  const merged = mergePicked(already, usable);
  const over = merged.length > MAX_BATCH;
  const parts: string[] = [];
  if (over) parts.push(`Only the first ${MAX_BATCH} videos are kept.`);
  if (notes.length) parts.push(`Left out: ${notes.slice(0, 4).join(", ")}${notes.length > 4 ? ` and ${notes.length - 4} more` : ""}. Use MP4, MOV, M4V, MKV or WebM files.`);
  if (!usable.length && !notes.length) parts.push("No videos found there.");
  return { picked: over ? merged.slice(0, MAX_BATCH) : merged, problem: parts.length ? parts.join(" ") : null };
}

/** Why a file can't be used, or null. */
function problemWith(item: Picked): string | null {
  if (item.file.size === 0) return "it is empty";
  const maxMb = getUploadConfig().maxMb;
  if (item.file.size > maxMb * 1024 * 1024) return `it is over ${maxMb} MB`;
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

export default function UploadCard({ busy, uploadProgress, error, blockedReason, onStart, onStartBatch, onCancel, initialItems }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const folderRef = useRef<HTMLInputElement>(null);
  const [first] = useState(() => (initialItems ? screen([], initialItems) : null));
  const [picked, setPicked] = useState<Picked[]>(first?.picked ?? []);
  const [fileError, setFileError] = useState<string | null>(first?.problem ?? null);
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

  /** Add what was chosen (files, or a folder with everything inside it). */
  function add(items: Picked[]) {
    const next = screen(picked, items);
    setPicked(next.picked);
    setFileError(next.problem);
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
          if (!busy) void safeFromDataTransfer(e.dataTransfer, MAX_BATCH * 4).then(add);
        }}
        className={`flex flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-6 py-5 text-center transition sm:py-12 ${
          dragging ? "border-violet-400 bg-violet-500/10" : "border-white/15 bg-white/[0.03]"
        } ${busy ? "cursor-default" : "cursor-pointer hover:border-white/40"}`}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept="video/*,.mov,.mkv,.m4v,.webm,.mp4"
          className="hidden"
          onChange={(e) => {
            add(fromFileList(e.target.files ?? []));
            e.target.value = "";
          }}
        />
        <input
          ref={folderRef}
          type="file"
          className="hidden"
          {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
          onChange={(e) => {
            add(fromFileList(e.target.files ?? []));
            e.target.value = "";
          }}
        />
        <p className="text-lg font-medium">
          <span className="sm:hidden">Add videos</span>
          <span className="hidden sm:inline">Drag &amp; drop your videos or a whole folder here</span>
        </p>
        <div className="mt-1 flex flex-wrap justify-center gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={(e) => {
              e.stopPropagation();
              inputRef.current?.click();
            }}
            className="rounded-lg border border-white/20 px-4 py-1.5 text-sm hover:bg-white/5 disabled:opacity-40"
          >
            Choose videos
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={(e) => {
              e.stopPropagation();
              folderRef.current?.click();
            }}
            className="rounded-lg border border-white/20 px-4 py-1.5 text-sm hover:bg-white/5 disabled:opacity-40"
          >
            Choose a folder
          </button>
        </div>
        <p className="mt-2 text-xs text-white/40">
          MP4, MOV, M4V, MKV or WebM · up to {getUploadConfig().maxMb} MB each · many at once are edited one after another
        </p>
      </div>

      {picked.length > 0 && (
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <div className="mb-2 flex items-baseline justify-between gap-2">
            <p className="text-sm font-medium">
              {picked.length} video{picked.length === 1 ? "" : "s"} ready
              <span className="ml-2 text-xs font-normal text-white/40">{formatBytes(picked.reduce((n, p) => n + p.file.size, 0))}</span>
            </p>
            {!busy && (
              <button onClick={() => setPicked([])} className="text-xs text-white/50 underline hover:text-white">
                Clear
              </button>
            )}
          </div>
          <ul className="max-h-48 space-y-1 overflow-y-auto text-sm" aria-label="Videos to edit">
            {picked.map((p) => {
              const folder = folderOf(p.path);
              return (
                <li key={`${p.path}:${p.file.size}`} className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate" title={p.path}>
                    {folder && <span className="text-white/40">{folder}/</span>}
                    {baseName(p.path)}
                  </span>
                  <span className="shrink-0 text-xs text-white/40">{formatBytes(p.file.size)}</span>
                  {!busy && (
                    <button onClick={() => setPicked(picked.filter((x) => x !== p))} aria-label={`Remove ${baseName(p.path)}`} className="shrink-0 text-xs text-white/40 hover:text-white">
                      ✕
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

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
            className="mt-2 w-full resize-none rounded-md border border-white/10 bg-field px-3 py-2 text-sm placeholder:text-white/30 focus:border-violet-400 focus:outline-none"
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
              className="w-full rounded-lg border border-white/10 bg-field px-4 py-3 text-sm"
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

      {blockedReason && (
        <p role="status" className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
          {blockedReason}
        </p>
      )}

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
          disabled={picked.length === 0 || busy || !!blockedReason}
          onClick={() => (picked.length === 1 ? onStart(picked[0].file, settings) : onStartBatch(picked, settings))}
          className="w-full rounded-xl bg-violet-600 px-6 py-3.5 font-semibold text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-white/30"
        >
          {picked.length > 1 ? `Edit these ${picked.length} videos, one after another` : "Start editing"}
        </button>
      )}
    </div>
  );
}
