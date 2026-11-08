"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import type { AccountInfo } from "@/components/AuthGate";
import TextEditor from "@/components/overlay/TextEditor";
import Shell, { quotaBlock } from "@/components/Shell";
import { formatTime } from "@/lib/timeline";
import type { TextOverlay } from "@/lib/overlays";
import PhotoGrid from "./PhotoGrid";
import SlideshowPreview, { type SlideshowHandle } from "./SlideshowPreview";
import {
  DEFAULT_SETTINGS,
  PROJECT_STORAGE_KEY,
  SIZE_RATIO,
  createProject,
  deleteMusic,
  deleteProject,
  downloadUrl,
  getProject,
  makeBatches,
  musicUrl,
  naturalByName,
  perPhoto,
  saveSettings,
  setOrder,
  startRender,
  uploadMusic,
  uploadPhotoBatch,
  videoUrl,
  type PhotoSettings,
  type Project,
} from "./photosApi";

const IMAGE_NAME = /\.(jpe?g|png|webp|heic|heif|gif|bmp)$/i;

function remember(id: string | null) {
  try {
    if (id) localStorage.setItem(PROJECT_STORAGE_KEY, id);
    else localStorage.removeItem(PROJECT_STORAGE_KEY);
  } catch {
    /* storage unavailable */
  }
}

const message = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong.");

function Card({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="space-y-3 rounded-2xl border border-white/10 p-4">
      <div>
        <h2 className="font-medium">{title}</h2>
        {hint && <p className="text-xs text-white/50">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

const choice = (on: boolean) =>
  `rounded-lg px-3 py-1.5 text-sm ${on ? "bg-violet-600 font-semibold text-white" : "border border-white/15 text-white/70 hover:bg-white/5"}`;

export default function PhotoStudio({ account }: { account: AccountInfo }) {
  const idRef = useRef<string | null>(null);
  const dirty = useRef(false);
  const previewRef = useRef<SlideshowHandle>(null);
  const photoInput = useRef<HTMLInputElement>(null);
  const musicInput = useRef<HTMLInputElement>(null);

  const [loading, setLoading] = useState(true);
  const [project, setProject] = useState<Project | null>(null);
  const [settings, setSettings] = useState<PhotoSettings>(DEFAULT_SETTINGS);
  const [selectedTextId, setSelectedTextId] = useState<string | null>(null);
  const [upload, setUpload] = useState<{ done: number; total: number; size: number; fraction: number } | null>(null);
  const [rejected, setRejected] = useState<{ name: string; reason: string }[]>([]);
  const [musicProgress, setMusicProgress] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const status = project?.status ?? "draft";
  const locked = status === "queued" || status === "rendering";
  const photos = project?.photos ?? [];
  const n = photos.length;
  const musicDuration = project?.music?.duration ?? null;
  const per = perPhoto(settings, n, musicDuration);
  const total = per * n;

  function applyProject(p: Project) {
    idRef.current = p.id;
    setProject(p);
  }

  // Pick up where the user left off.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const saved = localStorage.getItem(PROJECT_STORAGE_KEY);
        if (saved && /^[0-9a-f]{32}$/.test(saved)) {
          const p = await getProject(saved);
          if (cancelled) return;
          idRef.current = p.id;
          setProject(p);
          setSettings(p.settings);
        }
      } catch {
        remember(null); // gone (deleted or expired): start fresh
      }
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // The project is created the first time there is something to keep (photos, music, ...).
  async function ensureProject(): Promise<string> {
    if (idRef.current) return idRef.current;
    const { id } = await createProject();
    idRef.current = id;
    remember(id);
    applyProject(await saveSettings(id, settings));
    dirty.current = false;
    return id;
  }

  async function flushSettings() {
    if (!dirty.current || !idRef.current) return;
    dirty.current = false;
    await saveSettings(idRef.current, settings);
  }

  function change(patch: Partial<PhotoSettings>) {
    dirty.current = true;
    setSettings((s) => ({ ...s, ...patch }));
  }

  // Save settings shortly after they stop changing.
  const settingsKey = JSON.stringify(settings);
  useEffect(() => {
    if (!dirty.current || !idRef.current) return;
    const timer = setTimeout(() => {
      dirty.current = false;
      saveSettings(idRef.current!, JSON.parse(settingsKey)).catch((e) => setError(message(e)));
    }, 700);
    return () => clearTimeout(timer);
  }, [settingsKey]);

  // Watch a render.
  const watching = project && (project.status === "queued" || project.status === "rendering") ? project.id : null;
  useEffect(() => {
    if (!watching) return;
    const timer = setInterval(() => {
      getProject(watching)
        .then(applyProject)
        .catch(() => {});
    }, 1200);
    return () => clearInterval(timer);
  }, [watching]);

  async function addPhotos(list: FileList | File[]) {
    const files = Array.from(list)
      .filter((f) => f.type.startsWith("image/") || IMAGE_NAME.test(f.name))
      .sort(naturalByName); // browsers hand files over in any order: use the file-name order
    if (!files.length) {
      setError("Those don't look like photos (use JPG, PNG, WebP or HEIC).");
      return;
    }
    setError(null);
    setRejected([]);
    try {
      const id = await ensureProject();
      const refused: { name: string; reason: string }[] = [];
      let doneSoFar = 0;
      for (const batch of makeBatches(files)) {
        const i = doneSoFar;
        doneSoFar += batch.length;
        setUpload({ done: i, total: files.length, size: batch.length, fraction: 0 });
        const { promise } = uploadPhotoBatch(id, batch, (f) => setUpload((u) => u && { ...u, fraction: f }));
        refused.push(...(await promise).rejected);
        applyProject(await getProject(id));
      }
      setRejected(refused);
    } catch (e) {
      setError(message(e));
    } finally {
      setUpload(null);
    }
  }

  async function reorder(ids: string[]) {
    if (!project) return;
    setProject({ ...project, photos: ids.map((id) => project.photos.find((p) => p.id === id)!).filter(Boolean) }); // instant
    try {
      applyProject(await setOrder(project.id, ids));
    } catch (e) {
      setError(message(e));
      getProject(project.id).then(applyProject).catch(() => {});
    }
  }

  async function addMusic(file: File) {
    setError(null);
    try {
      const id = await ensureProject();
      setMusicProgress(0);
      const { promise } = uploadMusic(id, file, setMusicProgress);
      applyProject(await promise);
    } catch (e) {
      setError(message(e));
    } finally {
      setMusicProgress(null);
    }
  }

  async function removeMusic() {
    if (!project) return;
    try {
      applyProject(await deleteMusic(project.id));
      if (settings.fit_music) change({ fit_music: false });
    } catch (e) {
      setError(message(e));
    }
  }

  async function makeVideo() {
    setError(null);
    try {
      const id = await ensureProject();
      await flushSettings();
      applyProject(await startRender(id));
      account.refresh(); // a photo video counts as one of the day's videos
    } catch (e) {
      setError(message(e));
      account.refresh();
    }
  }

  function startOver() {
    remember(null);
    idRef.current = null;
    dirty.current = false;
    setProject(null);
    setSettings(DEFAULT_SETTINGS);
    setSelectedTextId(null);
    setRejected([]);
    setError(null);
  }

  async function removeProject() {
    if (!project || !window.confirm("Delete this project and all its photos?")) return;
    try {
      await deleteProject(project.id);
      startOver();
    } catch (e) {
      setError(message(e));
    }
  }

  const moveText = (id: string, x: number, y: number) => {
    dirty.current = true;
    setSettings((s) => ({ ...s, texts: s.texts.map((t) => (t.id === id ? { ...t, x, y } : t)) }));
  };
  const selectText = (id: string | null) => {
    setSelectedTextId(id);
    const t = id ? settings.texts.find((x) => x.id === id) : null;
    if (t) previewRef.current?.seek(Math.min(t.start + 0.05, Math.max(total - 0.05, 0))); // jump to where it shows
  };

  const blocked = quotaBlock(account.user?.quota.videos, "video", "videos");
  const canMake = n > 0 && !locked && !upload && !blocked;
  const ratio = SIZE_RATIO[settings.size];

  return (
    <Shell user={account.user} onSignOut={account.user ? account.signOut : undefined} wide section="photos">
      {loading ? (
        <p className="text-center text-sm text-white/40">Loading…</p>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
          {/* left: preview and the "make it" button */}
          <div className="space-y-4 lg:sticky lg:top-4 lg:self-start">
            <SlideshowPreview
              ref={previewRef}
              projectId={project?.id ?? null}
              photos={photos}
              settings={settings}
              musicDuration={musicDuration}
              musicSrc={project?.music && project.id ? musicUrl(project.id) : null}
              texts={settings.texts}
              selectedTextId={selectedTextId}
              onSelectText={selectText}
              onMoveText={moveText}
            />

            <div className="space-y-3 rounded-2xl border border-white/10 p-4">
              {status === "completed" && project?.has_output ? (
                <>
                  <p className="text-sm font-medium">
                    Your video is ready{project.output ? ` · ${formatTime(project.output.duration).replace(/\.\d$/, "")}` : ""}
                  </p>
                  <video key={project.updated_at} src={videoUrl(project.id)} controls playsInline className="mx-auto max-h-[60vh] rounded-xl bg-black" style={{ aspectRatio: String(ratio) }} />
                  <a href={downloadUrl(project.id)} className="block rounded-xl bg-violet-600 px-5 py-3 text-center font-semibold hover:bg-violet-500">
                    Download MP4
                  </a>
                  <p className="text-xs text-white/40">Change anything on the right and press the button again to make a new version.</p>
                </>
              ) : (
                <p className="text-sm text-white/60">
                  {n ? `${n} photo${n === 1 ? "" : "s"} × ${per.toFixed(1)} s = ${formatTime(total).replace(/\.\d$/, "")}` : "Add photos to begin."}
                </p>
              )}

              {locked && (
                <div className="space-y-1.5" role="status">
                  <div className="h-2 overflow-hidden rounded-full bg-white/10">
                    <div className="h-full bg-violet-500 transition-[width] duration-500" style={{ width: `${status === "queued" ? 3 : project?.progress ?? 0}%` }} />
                  </div>
                  <p className="text-xs text-white/60">{status === "queued" ? "Waiting for its turn…" : `Making your video… ${project?.progress ?? 0}%`}</p>
                </div>
              )}
              {status === "failed" && project?.error && (
                <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                  {project.error}
                </p>
              )}
              {blocked && <p className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-sm text-amber-100">{blocked}</p>}
              {error && (
                <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                  {error}
                </p>
              )}

              <button
                disabled={!canMake}
                onClick={makeVideo}
                className="w-full rounded-xl bg-violet-600 px-5 py-3 font-semibold hover:bg-violet-500 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-white/30"
              >
                {locked ? "Making…" : status === "completed" ? "Make it again" : "Make video"}
              </button>
              {project && (
                <div className="flex justify-between text-xs text-white/40">
                  <button onClick={startOver} disabled={locked} className="underline hover:text-white disabled:opacity-40">
                    Start a new video
                  </button>
                  <button onClick={removeProject} disabled={locked} className="underline hover:text-red-300 disabled:opacity-40">
                    Delete this project
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* right: the steps */}
          <div className="space-y-5">
            <Card title="1 · Photos" hint={`In the order you want them. Up to ${project?.limits.max_photos ?? 400} photos, JPG / PNG / WebP / iPhone HEIC.`}>
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  if (!locked) setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                  if (!locked && e.dataTransfer.files.length) void addPhotos(e.dataTransfer.files);
                }}
                onClick={() => !locked && !upload && photoInput.current?.click()}
                role="button"
                tabIndex={0}
                aria-label="Add photos"
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && !locked && photoInput.current?.click()}
                className={`flex cursor-pointer flex-col items-center gap-1 rounded-xl border-2 border-dashed px-4 py-8 text-center transition ${
                  dragOver ? "border-violet-400 bg-violet-500/10" : "border-white/15 bg-white/[0.02] hover:border-white/40"
                } ${locked ? "cursor-default opacity-50" : ""}`}
              >
                <input
                  ref={photoInput}
                  type="file"
                  multiple
                  accept="image/*,.heic,.heif"
                  className="hidden"
                  onChange={(e) => {
                    if (e.target.files?.length) void addPhotos(e.target.files);
                    e.target.value = "";
                  }}
                />
                {upload ? (
                  <>
                    <p className="text-sm font-medium">
                      Uploading {Math.min(upload.done + Math.round(upload.fraction * upload.size), upload.total)} of {upload.total}…
                    </p>
                    <div className="h-1.5 w-48 overflow-hidden rounded-full bg-white/10">
                      <div className="h-full bg-violet-500 transition-[width]" style={{ width: `${((upload.done + upload.fraction * upload.size) / upload.total) * 100}%` }} />
                    </div>
                  </>
                ) : (
                  <>
                    <p className="text-sm font-medium">Drop your photos here, or click to choose</p>
                    <p className="text-xs text-white/40">Select as many as you like. New ones are added at the end, sorted by file name.</p>
                  </>
                )}
              </div>
              {rejected.length > 0 && (
                <ul className="space-y-0.5 rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
                  {rejected.slice(0, 6).map((r, i) => (
                    <li key={i}>
                      <span className="font-medium">{r.name}</span>: {r.reason}
                    </li>
                  ))}
                  {rejected.length > 6 && <li>…and {rejected.length - 6} more.</li>}
                </ul>
              )}
              {project && n > 0 && <PhotoGrid projectId={project.id} photos={photos} disabled={locked || !!upload} onReorder={reorder} />}
            </Card>

            <Card title="2 · Music & timing" hint="Only use music you have the right to use.">
              <div className="flex flex-wrap items-center gap-3">
                <input ref={musicInput} type="file" accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg,.flac" className="hidden" onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void addMusic(f);
                  e.target.value = "";
                }} />
                <button disabled={locked || musicProgress !== null} onClick={() => musicInput.current?.click()} className="rounded-lg border border-white/20 px-3 py-1.5 text-sm hover:bg-white/5 disabled:opacity-40">
                  {project?.music ? "Replace music" : "Add music"}
                </button>
                {musicProgress !== null && <span className="text-xs text-white/60">Uploading… {Math.round(musicProgress * 100)}%</span>}
                {project?.music && (
                  <span className="flex min-w-0 items-center gap-2 text-sm">
                    <span className="truncate" title={project.music.name ?? ""}>♪ {project.music.name}</span>
                    <span className="shrink-0 text-xs tabular-nums text-white/50">{formatTime(project.music.duration ?? 0).replace(/\.\d$/, "")}</span>
                    <button onClick={removeMusic} disabled={locked} className="shrink-0 text-xs text-red-300 underline">
                      remove
                    </button>
                  </span>
                )}
              </div>

              <label className="flex items-center gap-3 text-sm">
                <input type="checkbox" className="h-4 w-4 accent-violet-500" checked={settings.fit_music} disabled={locked || !project?.music} onChange={(e) => change({ fit_music: e.target.checked })} />
                <span className={project?.music ? "" : "text-white/40"}>Make the video as long as the music (photo time is worked out for you)</span>
              </label>
              <label className="flex items-center gap-3 text-sm text-white/70">
                Seconds per photo
                <input type="range" min={0.5} max={15} step={0.1} value={settings.fit_music && musicDuration ? per : settings.seconds_per_photo} disabled={locked || (settings.fit_music && !!musicDuration)}
                  onChange={(e) => change({ seconds_per_photo: Number(e.target.value) })} aria-label="Seconds per photo" className="flex-1 accent-violet-500" />
                <span className="w-12 text-right tabular-nums">{per.toFixed(1)}s</span>
              </label>
              {project?.music && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="flex items-center gap-3 text-sm text-white/70">
                    Music volume
                    <input type="range" min={0} max={1} step={0.05} value={settings.music_volume} disabled={locked} onChange={(e) => change({ music_volume: Number(e.target.value) })} aria-label="Music volume" className="flex-1 accent-violet-500" />
                    <span className="w-10 text-right tabular-nums">{Math.round(settings.music_volume * 100)}%</span>
                  </label>
                  <label className="flex items-center gap-3 text-sm text-white/70">
                    Fade out
                    <input type="range" min={0} max={10} step={0.5} value={settings.music_fade_out_s} disabled={locked} onChange={(e) => change({ music_fade_out_s: Number(e.target.value) })} aria-label="Music fade-out seconds" className="flex-1 accent-violet-500" />
                    <span className="w-10 text-right tabular-nums">{settings.music_fade_out_s}s</span>
                  </label>
                </div>
              )}
            </Card>

            <Card title="3 · Look">
              <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Video shape">
                {(
                  [
                    ["vertical", "Vertical 9:16 (TikTok, Reels)"],
                    ["landscape", "Landscape 16:9 (YouTube)"],
                    ["square", "Square 1:1"],
                  ] as const
                ).map(([key, label]) => (
                  <button key={key} role="radio" aria-checked={settings.size === key} disabled={locked} onClick={() => change({ size: key })} className={choice(settings.size === key)}>
                    {label}
                  </button>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
                <label className="flex items-center gap-2 text-white/70">
                  Photos that don&apos;t fit
                  <select value={settings.fill} disabled={locked} onChange={(e) => change({ fill: e.target.value as PhotoSettings["fill"] })} className="rounded-md border border-white/10 bg-[#15151c] px-2 py-1">
                    <option value="blur">Blurred background</option>
                    <option value="crop">Crop to fill</option>
                    <option value="black">Black bars</option>
                  </select>
                </label>
                <label className="flex items-center gap-2 text-white/70">
                  <input type="checkbox" className="accent-violet-500" checked={settings.zoom} disabled={locked} onChange={(e) => change({ zoom: e.target.checked })} /> Slow zoom
                </label>
                <label className="flex items-center gap-2 text-white/70">
                  <input type="checkbox" className="accent-violet-500" checked={settings.fade} disabled={locked} onChange={(e) => change({ fade: e.target.checked })} /> Quick fade between photos
                </label>
              </div>
            </Card>

            <Card title="4 · Text" hint="Add titles or captions, then drag them on the preview.">
              <TextEditor
                texts={settings.texts}
                selectedId={selectedTextId}
                total={Math.max(total, 1)}
                disabled={locked}
                onChange={(texts: TextOverlay[]) => change({ texts })}
                onSelect={selectText}
              />
            </Card>
          </div>
        </div>
      )}
    </Shell>
  );
}
