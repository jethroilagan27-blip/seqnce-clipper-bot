"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AccountInfo } from "@/components/AuthGate";
import Shell from "@/components/Shell";
import { ApiError } from "@/lib/api";
import {
  SHAPE_LABEL,
  STUDIO_STORAGE_KEY,
  createProject,
  deleteProject,
  creditsScene,
  downloadUrl,
  duplicateScene,
  emptyScene,
  formatSeconds,
  getInfo,
  gridScene,
  getProject,
  listProjects,
  moveItem,
  previewUrl,
  saveDoc,
  startRender,
  textCardScene,
  videoUrl,
  withoutAsset,
  type Project,
  type ProjectSummary,
  type Scene,
  type Shape,
  type StudioDoc,
  type StudioInfo,
} from "@/lib/studio";
import AssetPanel from "./AssetPanel";
import SceneEditor from "./SceneEditor";
import { ConfirmButton, NumberInput, buttonCls, inputCls, primaryCls } from "./ui";

type SaveState = "saved" | "dirty" | "saving" | "error";
const ACTIVE = ["queued", "rendering"];

function readStored(): string | null {
  try {
    return localStorage.getItem(STUDIO_STORAGE_KEY);
  } catch {
    return null;
  }
}
function writeStored(id: string | null) {
  try {
    if (id) localStorage.setItem(STUDIO_STORAGE_KEY, id);
    else localStorage.removeItem(STUDIO_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}
const messageOf = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

// Studio lives at /studio. To remove it: delete this folder, app/studio/ and the Studio tab in Shell.tsx.
export default function StudioApp({ account }: { account: AccountInfo }) {
  const [info, setInfo] = useState<StudioInfo | null>(null);
  const [locked, setLocked] = useState<string | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [doc, setDoc] = useState<StudioDoc | null>(null); // what is on screen; saved a moment after every change
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [error, setError] = useState<string | null>(null);
  const [openScene, setOpenScene] = useState<string | null>(null);

  // the saving machinery (only touched in event handlers, never while rendering)
  const latest = useRef<{ id: string; doc: StudioDoc } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saving = useRef(false);
  const again = useRef(false);

  const refreshList = useCallback(() => {
    listProjects().then((r) => setProjects(r.projects)).catch(() => {});
  }, []);

  // first load: the plan check, the projects, and the project open last time
  useEffect(() => {
    let cancelled = false;
    getInfo()
      .then(async (i) => {
        if (cancelled) return;
        setInfo(i);
        const list = (await listProjects()).projects;
        if (cancelled) return;
        setProjects(list);
        const stored = readStored();
        setProjectId(list.find((p) => p.id === stored)?.id ?? list[0]?.id ?? null);
      })
      .catch((e) => {
        if (!cancelled) setLocked(messageOf(e, "Can't reach the server."));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // open a project
  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    getProject(projectId)
      .then((p) => {
        if (cancelled) return;
        latest.current = { id: p.id, doc: p.doc };
        setProject(p);
        setDoc(p.doc);
        setSaveState("saved");
        setOpenScene(p.doc.scenes[0]?.id ?? null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(messageOf(e, "Could not open the project."));
        writeStored(null);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // while a video is being made, ask how far it is
  const active = !!project && ACTIVE.includes(project.status);
  useEffect(() => {
    if (!active || !projectId) return;
    const t = setInterval(() => {
      getProject(projectId)
        .then((p) => {
          setProject((old) => (old && old.id === p.id ? { ...p, doc: old.doc } : old));
          if (!ACTIVE.includes(p.status)) account.refresh();
        })
        .catch(() => {});
    }, 1000);
    return () => clearInterval(t);
  }, [active, projectId, account]);

  const flush = useCallback(async () => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (saving.current) {
      again.current = true; // saved again as soon as the one in progress is done
      return;
    }
    saving.current = true;
    try {
      do {
        again.current = false;
        const job = latest.current;
        if (!job) return;
        setSaveState("saving");
        try {
          const p = await saveDoc(job.id, job.doc);
          setProject((old) => (old && old.id === p.id ? { ...p, doc: old.doc } : old));
          setError(null);
          setSaveState(again.current || latest.current?.doc !== job.doc ? "dirty" : "saved");
        } catch (e) {
          setError(messageOf(e, "Could not save your changes."));
          setSaveState("error");
          return;
        }
      } while (again.current);
    } finally {
      saving.current = false;
    }
  }, []);

  const edit = useCallback(
    (next: StudioDoc) => {
      if (!latest.current) return;
      latest.current = { id: latest.current.id, doc: next };
      setDoc(next);
      setProject((old) => (old ? { ...old, doc: next } : old)); // the editor reads the shape and so on from the project
      setSaveState("dirty");
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void flush(), 700);
    },
    [flush],
  );

  async function chooseProject(id: string | null) {
    if (id !== projectId) await flush();
    setProject(null);
    setDoc(null);
    setError(null);
    writeStored(id);
    setProjectId(id);
  }

  async function newProject() {
    try {
      const { id } = await createProject("Untitled video");
      refreshList();
      await chooseProject(id);
    } catch (e) {
      setError(messageOf(e, "Could not create the project."));
    }
  }

  async function removeProject() {
    if (!projectId) return;
    try {
      await deleteProject(projectId);
      const rest = (await listProjects()).projects;
      setProjects(rest);
      await chooseProject(rest[0]?.id ?? null);
    } catch (e) {
      setError(messageOf(e, "Could not delete the project."));
    }
  }

  async function render(kind: "final" | "preview", sceneId: string | null) {
    if (!project) return;
    setError(null);
    await flush();
    try {
      const p = await startRender(project.id, kind, sceneId);
      setProject({ ...p, doc: project.doc });
    } catch (e) {
      setError(messageOf(e, "Could not start."));
    }
  }

  const header = { user: account.user, onSignOut: account.signOut, section: "studio" as const, wide: "xl" as const };

  if (locked)
    return (
      <Shell {...header}>
        <p role="alert" className="rounded-xl border border-amber-400/40 bg-amber-500/10 px-5 py-4 text-sm text-amber-100">
          {locked}
        </p>
      </Shell>
    );
  if (!info || projects === null)
    return (
      <Shell {...header}>
        <p className="text-sm text-white/40">Loading Studio…</p>
      </Shell>
    );

  const busy = active;
  const limits = project?.limits ?? info.limits;

  return (
    <Shell {...header}>
      <div className="mb-5 flex flex-wrap items-center gap-2">
        <select
          className={`${inputCls} max-w-xs`}
          value={projectId ?? ""}
          aria-label="Project"
          onChange={(e) => void chooseProject(e.target.value || null)}
        >
          {projects.length === 0 && <option value="">No projects yet</option>}
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.title} · {p.scene_count} scene{p.scene_count === 1 ? "" : "s"}
            </option>
          ))}
        </select>
        <button className={buttonCls} onClick={() => void newProject()} disabled={projects.length >= limits.max_projects}>
          + New project
        </button>
        {project && <ConfirmButton label="Delete project" disabled={busy} onConfirm={() => void removeProject()} />}
        <span className="ml-auto text-xs text-white/40" aria-live="polite">
          {saveState === "saving" ? "Saving…" : saveState === "dirty" ? "Unsaved changes…" : saveState === "error" ? "Not saved" : project ? "All changes saved" : ""}
        </span>
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </p>
      )}

      {!projectId && (
        <div className="rounded-2xl border border-dashed border-white/15 px-6 py-12 text-center">
          <p className="text-white/70">Studio makes longer, scripted videos: scenes with your clips, pictures, voice-over, music and text.</p>
          <button className={`${primaryCls} mt-4`} onClick={() => void newProject()}>
            Start a project
          </button>
        </div>
      )}

      {projectId && (!project || !doc) && !error && <p className="text-sm text-white/40">Opening…</p>}

      {project && doc && (
        <div className="grid gap-6 lg:grid-cols-[22rem_minmax(0,1fr)]">
          <aside>
            <AssetPanel
              project={project}
              accepts={[...info.accepts.video, ...info.accepts.audio, ...info.accepts.image, ...info.accepts.font]}
              disabled={busy}
              onProject={(p) => setProject((old) => (old ? { ...p, doc: old.doc } : p))}
              onDeleted={(assetId, p) => {
                // the server already removed the file from the saved document; do the same to the one on screen
                const next = withoutAsset(doc, assetId);
                latest.current = { id: p.id, doc: next };
                setDoc(next);
                setProject({ ...p, doc: next });
              }}
            />
          </aside>

          <div className="min-w-0 space-y-6">
            <ProjectSettings project={project} doc={doc} disabled={busy} onChange={edit} />
            <Scenes
              project={project}
              doc={doc}
              info={info}
              disabled={busy}
              openId={openScene}
              onOpen={setOpenScene}
              onChange={edit}
              onPreview={(id) => void render("preview", id)}
            />
            <RenderPanel project={project} busy={busy} onRender={(kind) => void render(kind, null)} />
          </div>
        </div>
      )}
    </Shell>
  );
}

// ---- project settings (title, shape, music under the whole video) ---------------------------------

function ProjectSettings({ project, doc, disabled, onChange }: { project: Project; doc: StudioDoc; disabled: boolean; onChange: (d: StudioDoc) => void }) {
  const audio = project.assets.filter((a) => a.kind === "audio");
  const bed = doc.bed_music;
  return (
    <section className="space-y-3 rounded-2xl border border-white/10 bg-white/[0.02] p-4">
      <div className="flex flex-wrap items-center gap-3">
        <input className={`${inputCls} min-w-0 flex-1 text-base font-semibold`} value={doc.title} maxLength={80} disabled={disabled} aria-label="Project name" onChange={(e) => onChange({ ...doc, title: e.target.value })} />
        <select className={inputCls} value={doc.shape} disabled={disabled} aria-label="Video shape" onChange={(e) => onChange({ ...doc, shape: e.target.value as Shape })}>
          {(Object.keys(SHAPE_LABEL) as Shape[]).map((s) => (
            <option key={s} value={s}>
              {SHAPE_LABEL[s]}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-white/60">
        <label className="flex items-center gap-2">
          Music under the whole video
          <select
            className={inputCls}
            value={bed?.asset_id ?? ""}
            disabled={disabled}
            aria-label="Music under the whole video"
            onChange={(e) => onChange({ ...doc, bed_music: e.target.value ? { asset_id: e.target.value, start: bed?.start ?? 0, volume: bed?.volume ?? 0.25, fade_out: bed?.fade_out ?? 3, duck: bed?.duck ?? true } : null })}
          >
            <option value="">None</option>
            {audio.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        {bed && (
          <>
            <label className="flex items-center gap-1.5">
              volume
              <input type="range" min={0} max={100} value={Math.round(bed.volume * 100)} disabled={disabled} aria-label="Music volume" className="w-24 accent-violet-500" onChange={(e) => onChange({ ...doc, bed_music: { ...bed, volume: Number(e.target.value) / 100 } })} />
              <span className="w-9 tabular-nums">{Math.round(bed.volume * 100)}%</span>
            </label>
            <label className="flex items-center gap-1.5">
              fades out over
              <NumberInput label="Music fade out at the end (seconds)" value={bed.fade_out} max={30} disabled={disabled} className="w-14" onChange={(n) => onChange({ ...doc, bed_music: { ...bed, fade_out: n ?? 0 } })} /> s
            </label>
            <label className={`flex items-center gap-1.5 ${project.limits.ducking ? "" : "opacity-50"}`} title={project.limits.ducking ? "" : "Not included in your plan."}>
              <input type="checkbox" checked={bed.duck && project.limits.ducking} disabled={disabled || !project.limits.ducking} className="accent-violet-500" onChange={(e) => onChange({ ...doc, bed_music: { ...bed, duck: e.target.checked } })} />
              Lower it while anyone speaks
            </label>
          </>
        )}
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={doc.normalize_loudness} disabled={disabled} className="accent-violet-500" onChange={(e) => onChange({ ...doc, normalize_loudness: e.target.checked })} />
          Even out the volume
        </label>
      </div>
    </section>
  );
}

// ---- the scenes ----------------------------------------------------------------------------------

function Scenes({ project, doc, info, disabled, openId, onOpen, onChange, onPreview }: {
  project: Project;
  doc: StudioDoc;
  info: StudioInfo;
  disabled: boolean;
  openId: string | null;
  onOpen: (id: string | null) => void;
  onChange: (d: StudioDoc) => void;
  onPreview: (sceneId: string) => void;
}) {
  const { limits } = project;
  const full = doc.scenes.length >= limits.max_scenes;
  const setScenes = (scenes: Scene[]) => onChange({ ...doc, scenes });
  const add = (scene: Scene) => {
    setScenes([...doc.scenes, scene]);
    onOpen(scene.id);
  };
  const previewing = ACTIVE.includes(project.status) && project.render.kind === "preview";

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-2 text-lg font-semibold">Scenes</h2>
        <button className={buttonCls} disabled={disabled || full} onClick={() => add(emptyScene(doc.scenes.length + 1))}>
          + Scene
        </button>
        <button className={buttonCls} disabled={disabled || full} onClick={() => add(textCardScene(doc.scenes.length + 1))} title="A scene on black with a big text: a title, a question">
          + Text card
        </button>
        <button className={buttonCls} disabled={disabled || full || !limits.grid} onClick={() => add(gridScene(doc.scenes.length + 1))} title={limits.grid ? "Several clips on screen at once" : "Not included in your plan"}>
          + Grid
        </button>
        <button className={buttonCls} disabled={disabled || full || !limits.credits} onClick={() => add(creditsScene(doc.scenes.length + 1))} title={limits.credits ? "Rolling credits" : "Not included in your plan"}>
          + Credits
        </button>
        <span className="ml-auto text-xs text-white/40">
          {doc.scenes.length} of {limits.max_scenes} · {formatSeconds(project.total_seconds)} in all (up to {limits.max_minutes} min)
        </span>
      </div>

      {doc.scenes.length === 0 && (
        <p className="rounded-xl border border-dashed border-white/15 px-4 py-8 text-center text-sm text-white/40">
          No scenes yet. Upload your files on the left, then add a scene (clips and pictures) or a text card (words on black).
        </p>
      )}

      <ol className="space-y-2">
        {doc.scenes.map((scene, i) => {
          const open = scene.id === openId;
          const s = project.scenes.find((x) => x.id === scene.id);
          const showPreview = project.preview?.scene === scene.id && project.status === "completed" && project.render.kind === "preview";
          return (
            <li key={scene.id} className={`rounded-2xl border ${open ? "border-violet-400/60" : "border-white/10"} bg-white/[0.02]`}>
              <div className="flex flex-wrap items-center gap-2 p-3">
                <button onClick={() => onOpen(open ? null : scene.id)} aria-expanded={open} className="flex min-w-0 flex-1 items-baseline gap-3 text-left">
                  <span className="w-6 shrink-0 text-sm tabular-nums text-white/40">{i + 1}</span>
                  <span className="min-w-0 truncate font-medium">{scene.name}</span>
                  <span className={`shrink-0 text-xs ${s?.problem ? "text-amber-300" : "text-white/40"}`}>
                    {s?.problem ? "needs attention" : s?.duration ? formatSeconds(s.duration) : ""}
                    {scene.transition_in === "crossfade" && i > 0 ? " · cross-fade" : ""}
                  </span>
                </button>
                <div className="flex shrink-0 gap-1">
                  <button className={`${buttonCls} px-2 py-0.5 text-xs`} disabled={disabled || i === 0} onClick={() => setScenes(moveItem(doc.scenes, i, i - 1))} aria-label="Move scene earlier">
                    ↑
                  </button>
                  <button className={`${buttonCls} px-2 py-0.5 text-xs`} disabled={disabled || i === doc.scenes.length - 1} onClick={() => setScenes(moveItem(doc.scenes, i, i + 1))} aria-label="Move scene later">
                    ↓
                  </button>
                  <button className={`${buttonCls} px-2 py-0.5 text-xs`} disabled={disabled || full} onClick={() => { const copy = duplicateScene(scene, doc.scenes.length + 1); setScenes([...doc.scenes.slice(0, i + 1), copy, ...doc.scenes.slice(i + 1)]); onOpen(copy.id); }}>
                    Duplicate
                  </button>
                  <ConfirmButton label="Delete" disabled={disabled} onConfirm={() => setScenes(doc.scenes.filter((x) => x.id !== scene.id))} />
                </div>
              </div>
              {open && (
                <SceneEditor
                  project={project}
                  scene={scene}
                  index={i}
                  fonts={info.fonts}
                  disabled={disabled}
                  onChange={(next) => setScenes(doc.scenes.map((x) => (x.id === scene.id ? next : x)))}
                  previewSrc={showPreview ? previewUrl(project.id, scene.id, project.updated_at) : null}
                  previewing={previewing && project.render.scene === scene.id}
                  onPreview={() => onPreview(scene.id)}
                />
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

// ---- making the whole video -------------------------------------------------------------------------

function RenderPanel({ project, busy, onRender }: { project: Project; busy: boolean; onRender: (kind: "final" | "preview") => void }) {
  const { limits } = project;
  const working = busy;
  const showWholePreview = project.preview?.scene === null && project.status === "completed" && project.render.kind === "preview";
  const empty = project.doc.scenes.length === 0;
  return (
    <section className="space-y-3 rounded-2xl border border-white/10 bg-white/[0.02] p-4">
      <h2 className="text-lg font-semibold">Make the video</h2>
      <p className="text-xs text-white/40">
        The finished video is {formatSeconds(project.total_seconds)} long, up to {limits.max_height}p. Your plan allows {limits.max_minutes} minute{limits.max_minutes === 1 ? "" : "s"}
        {limits.renders_per_day !== null ? ` and ${limits.renders_per_day} finished video${limits.renders_per_day === 1 ? "" : "s"} a day (previews are free)` : ""}.
      </p>
      <div className="flex flex-wrap gap-2">
        <button className={buttonCls} disabled={working || empty} onClick={() => onRender("preview")}>
          Quick preview of everything
        </button>
        <button className={primaryCls} disabled={working || empty} onClick={() => onRender("final")}>
          Make the finished video
        </button>
      </div>

      {working && (
        <div aria-live="polite" className="space-y-1">
          <div className="flex justify-between text-xs text-white/60">
            <span>{project.stage ?? "Working"}</span>
            <span className="tabular-nums">{project.progress}%</span>
          </div>
          <div className="h-2 rounded bg-white/10">
            <div className="h-2 rounded bg-violet-500 transition-all" style={{ width: `${project.progress}%` }} />
          </div>
        </div>
      )}
      {project.status === "failed" && project.error && (
        <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200">
          {project.error}
        </p>
      )}

      {showWholePreview && (
        <div>
          <p className="mb-1 text-xs text-white/50">Quick preview (small, rough)</p>
          <video key={project.updated_at} src={previewUrl(project.id, null, project.updated_at)} controls className="w-full max-w-2xl rounded-lg bg-black" />
        </div>
      )}
      {project.has_output && project.output && (
        <div>
          <p className="mb-1 text-xs text-white/50">
            Finished video · {formatSeconds(project.output.duration)} · {project.output.width}×{project.output.height}
          </p>
          <video key={`final-${project.output.size_bytes}`} src={videoUrl(project.id, String(project.output.size_bytes))} controls className="w-full max-w-2xl rounded-lg bg-black" />
          <a href={downloadUrl(project.id)} className="mt-2 inline-block rounded-lg border border-white/15 px-4 py-2 text-sm hover:bg-white/5">
            Download
          </a>
        </div>
      )}
    </section>
  );
}
