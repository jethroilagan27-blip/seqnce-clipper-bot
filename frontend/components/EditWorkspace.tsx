"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  HOOK_CSS,
  getAnalysis,
  mediaUrl,
  postTimeline,
  type Analysis,
  type ManualEdit,
  type Plan,
  type TimelineSpec,
  type Version,
} from "@/lib/api";
import { clipsEqual, formatTime, toggleRange, type DraftClip, type Range } from "@/lib/timeline";
import { ChangeChips } from "./RevisionPanel";
import LivePreview, { type PreviewHandle } from "./LivePreview";
import Overview from "./Overview";
import PartsPanel from "./PartsPanel";
import TranscriptEditor from "./TranscriptEditor";

type Draft = {
  clips: DraftClip[];
  hookEnabled: boolean;
  hookText: string;
  hookColor: string;
  hookDuration: number;
  captions: boolean;
};

function draftFrom(plan: Plan): Draft {
  const hook = plan.hook ?? { enabled: false, text: "", color: "yellow", duration_s: 4 };
  return {
    clips: plan.clips.map((c) => ({ start: c.start, end: c.end, purpose: c.purpose, reason: c.reason })),
    hookEnabled: hook.enabled,
    hookText: hook.text,
    hookColor: hook.color,
    hookDuration: hook.duration_s,
    captions: plan.captions?.enabled ?? true,
  };
}

/** Only the fields the user actually changed (what the server's manual edit expects). */
function editFrom(plan: Plan, d: Draft): ManualEdit {
  const base = draftFrom(plan);
  const edit: ManualEdit = {};
  if (!clipsEqual(d.clips, base.clips)) edit.clips = d.clips;
  if (d.hookEnabled !== base.hookEnabled) edit.hook_enabled = d.hookEnabled;
  if (d.hookEnabled && d.hookText.trim() && d.hookText.trim() !== base.hookText) edit.hook_text = d.hookText.trim();
  if (d.hookColor !== base.hookColor) edit.hook_color = d.hookColor;
  if (Math.abs(d.hookDuration - base.hookDuration) > 0.01) edit.hook_duration_s = d.hookDuration;
  if (d.captions !== base.captions) edit.captions_enabled = d.captions;
  return edit;
}

type Props = {
  jobId: string;
  shown: Version;
  isCurrent: boolean;
  busy: boolean;
  tabs: ReactNode; // version tabs
  side: ReactNode; // chat panel
  onApply: (edit: ManualEdit) => Promise<string | null>; // resolves to an error message, or null
  onRestore: (version: number) => Promise<string | null>;
};

// Mount with key={version}-{current}: the draft starts from that version's plan.
export default function EditWorkspace({ jobId, shown, isCurrent, busy, tabs, side, onApply, onRestore }: Props) {
  const plan = shown.plan;
  const editable = isCurrent && !busy;
  const previewRef = useRef<PreviewHandle>(null);

  const [draft, setDraft] = useState<Draft>(() => draftFrom(plan));
  const [mode, setMode] = useState<"final" | "preview">("final");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [spec, setSpec] = useState<TimelineSpec | null>(null);
  const [specError, setSpecError] = useState<string | null>(null);
  const [playhead, setPlayhead] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [tab, setTab] = useState<"parts" | "transcript" | "title">("parts");
  const [selected, setSelected] = useState<number | null>(null);

  const edit = editFrom(plan, draft);
  const editKey = JSON.stringify(edit);
  const dirty = Object.keys(edit).length > 0;

  useEffect(() => {
    let cancelled = false;
    getAnalysis(jobId)
      .then((a) => !cancelled && setAnalysis(a))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  // Ask the server what this (draft) edit looks like. It uses the renderer's own cut/caption code.
  useEffect(() => {
    let cancelled = false;
    const parsed: ManualEdit = JSON.parse(editKey);
    const timer = setTimeout(() => {
      postTimeline(jobId, { version: shown.version, edit: Object.keys(parsed).length ? parsed : undefined })
        .then((s) => {
          if (cancelled) return;
          setSpec(s);
          setSpecError(null);
        })
        .catch((e) => !cancelled && setSpecError(e instanceof Error ? e.message : "Can't preview that."));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId, shown.version, editKey]);

  const segments = useMemo(() => analysis?.transcript.segments ?? [], [analysis]);
  const boundaries = useMemo(
    () => segments.flatMap((s) => (s.words ?? []).flatMap((w) => [w.start, w.end])),
    [segments],
  );
  const duration = spec?.source.duration ?? analysis?.transcript.duration ?? plan.clips.at(-1)?.end ?? 1;
  const aspect = spec ? spec.source.width / spec.source.height : 16 / 9;

  function change(patch: Partial<Draft>) {
    if (patch.clips && patch.clips.length !== draft.clips.length) setSelected(null); // part numbers shifted
    setDraft((d) => ({ ...d, ...patch }));
    setMode("preview");
    setError(null);
  }
  function seek(src: number) {
    setMode("preview");
    previewRef.current?.seekSource(src);
  }

  const changed = shown.changes?.clips ?? [];
  const removed: Range[] = changed.filter((c) => c.status === "removed");

  async function run(fn: () => Promise<string | null>) {
    setWorking(true);
    setError(null);
    const err = await fn();
    setWorking(false);
    if (err) setError(err);
  }

  const changedAreas = [
    edit.clips && "parts",
    (edit.hook_enabled !== undefined ||
      edit.hook_text !== undefined ||
      edit.hook_color !== undefined ||
      edit.hook_duration_s !== undefined) &&
      "title",
    edit.captions_enabled !== undefined && "captions",
  ].filter(Boolean) as string[];

  const locked = !editable || working;
  const hookInvalid = draft.hookEnabled && !draft.hookText.trim();
  const canApply = dirty && !locked && !specError && !hookInvalid;
  const finalSrc = shown.preview_url ? mediaUrl(shown.preview_url) : null;
  const kept = draft.clips.reduce((a, c) => a + (c.end - c.start), 0);

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <div className="space-y-4">
          {tabs}
          <div className="flex gap-1.5" role="tablist" aria-label="What to show">
            {(["final", "preview"] as const).map((m) => (
              <button
                key={m}
                role="tab"
                aria-selected={mode === m}
                onClick={() => setMode(m)}
                className={`rounded-full px-3 py-1 text-xs ${
                  mode === m ? "bg-white/15 font-semibold text-white" : "border border-white/15 text-white/60 hover:text-white"
                }`}
              >
                {m === "final" ? "Final video" : dirty ? "Live preview (your changes)" : "Live preview"}
              </button>
            ))}
          </div>

          <div className={mode === "final" ? "" : "hidden"}>
            <div
              className="relative mx-auto overflow-hidden rounded-2xl border border-white/10 bg-black"
              style={{ aspectRatio: "9 / 16", width: "min(100%, calc(70vh * 9 / 16))" }}
            >
              {finalSrc ? (
                <video
                  key={finalSrc}
                  src={finalSrc}
                  controls
                  playsInline
                  className={`h-full w-full object-contain transition ${busy ? "opacity-40" : ""}`}
                />
              ) : (
                <p className="p-6 text-center text-sm text-white/50">This version has no video file any more.</p>
              )}
              {busy && (
                <div className="pointer-events-none absolute inset-x-0 top-4 text-center text-xs font-medium text-white/80">
                  Making a new version…
                </div>
              )}
            </div>
          </div>

          <div className={mode === "preview" ? "" : "hidden"}>
            {spec ? (
              <LivePreview ref={previewRef} jobId={jobId} spec={spec} onTime={(src) => setPlayhead(src)} />
            ) : (
              <p className="py-16 text-center text-sm text-white/50">{specError ?? "Loading preview…"}</p>
            )}
            <p className="mt-2 text-center text-xs text-white/40">
              Instant preview of the cuts, captions and title. The final video is rendered from the same plan.
            </p>
          </div>

          {finalSrc && shown.download_url && (
            <a
              href={mediaUrl(shown.download_url)}
              className="block rounded-xl bg-violet-600 px-6 py-3.5 text-center font-semibold text-white hover:bg-violet-500"
            >
              Download v{shown.version}
            </a>
          )}
        </div>

        <div className="space-y-6">{side}</div>
      </div>

      <section className="space-y-4 rounded-2xl border border-white/10 p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-medium">
              Edit your short <span className="text-xs font-normal text-white/40">version {shown.version}</span>
            </h2>
            <p className="text-xs text-white/50">
              {draft.clips.length} part{draft.clips.length === 1 ? "" : "s"} · {formatTime(kept).replace(/\.\d$/, "")} taken from
              your {formatTime(duration).replace(/\.\d$/, "")} video
            </p>
            <ChangeChips changes={shown.changes} />
          </div>
          <span
            className={`rounded-full px-2.5 py-0.5 text-xs ${
              plan.source === "ai" ? "bg-violet-500/20 text-violet-200" : "bg-amber-400/20 text-amber-100"
            }`}
          >
            {plan.source === "ai" ? "Chosen by AI" : "Basic cut"}
          </span>
        </div>

        <Overview
          jobId={jobId}
          duration={duration}
          aspect={aspect}
          clips={draft.clips}
          ghosts={dirty ? [] : removed}
          selected={selected}
          playheadSrc={playhead}
          onSelect={(i) => {
            setTab("parts");
            setSelected(i);
          }}
          onSeek={seek}
        />
        <p className="-mt-2 text-xs text-white/40">
          Bright parts of your video are in the short; dimmed parts are cut out. Numbers match the list below.
        </p>

        {specError && (
          <p role="alert" className="text-xs text-red-300">
            {specError}
          </p>
        )}

        <div role="tablist" aria-label="Editing tools" className="flex gap-1 border-b border-white/10">
          {(
            [
              ["parts", "Parts"],
              ["transcript", "Transcript"],
              ["title", "Title & captions"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm ${
                tab === key ? "border-violet-400 font-medium text-white" : "border-transparent text-white/50 hover:text-white"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "parts" && (
          <PartsPanel
            jobId={jobId}
            aspect={aspect}
            duration={duration}
            clips={draft.clips}
            segments={segments}
            boundaries={boundaries}
            selected={selected}
            playheadSrc={playhead}
            editable={editable}
            onSelect={setSelected}
            onChange={(clips) => change({ clips })}
            onSeek={seek}
          />
        )}

        {tab === "transcript" && (
          <div className="space-y-2">
            <p className="text-sm text-white/60">
              Everything that was said.{" "}
              {editable ? "Click a sentence to cut it out of your short, or to add it back." : ""} Highlighted sentences are in
              your short.
            </p>
            <TranscriptEditor
              segments={segments}
              clips={draft.clips}
              playheadSrc={playhead}
              editable={editable}
              onToggle={(s) => change({ clips: toggleRange(draft.clips, s, duration) })}
              onSeek={seek}
            />
          </div>
        )}

        {tab === "title" && (
          <div className="space-y-4 text-sm">
            <div className="space-y-2">
              <label className="flex items-center justify-between gap-3">
                <span>
                  <span className="font-medium">Title at the top</span>
                  <span className="block text-xs text-white/50">A big headline that shows for the first few seconds</span>
                </span>
                <input
                  type="checkbox"
                  className="h-5 w-5 accent-violet-500"
                  checked={draft.hookEnabled}
                  disabled={locked}
                  onChange={(e) => change({ hookEnabled: e.target.checked })}
                />
              </label>
              {draft.hookEnabled && (
                <>
                  <input
                    type="text"
                    value={draft.hookText}
                    maxLength={60}
                    disabled={locked}
                    onChange={(e) => change({ hookText: e.target.value })}
                    aria-label="Hook title text"
                    placeholder="Type a title (max 8 words)"
                    className="w-full rounded-md border border-white/10 bg-[#15151c] px-3 py-2 text-sm font-semibold uppercase focus:border-violet-400 focus:outline-none"
                    style={{ color: HOOK_CSS[draft.hookColor] ?? "#ffe600" }}
                  />
                  <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Hook colour">
                    {Object.entries(HOOK_CSS).map(([name, css]) => (
                      <button
                        key={name}
                        role="radio"
                        aria-checked={draft.hookColor === name}
                        aria-label={name}
                        title={name}
                        disabled={locked}
                        onClick={() => change({ hookColor: name })}
                        className={`h-7 w-7 rounded-full border-2 ${draft.hookColor === name ? "border-white" : "border-transparent"}`}
                        style={{ backgroundColor: css }}
                      />
                    ))}
                  </div>
                  <label className="flex items-center gap-3 text-xs text-white/60">
                    Shows for
                    <input
                      type="range"
                      min={1}
                      max={10}
                      step={0.5}
                      value={draft.hookDuration}
                      disabled={locked}
                      onChange={(e) => change({ hookDuration: Number(e.target.value) })}
                      aria-label="How long the hook shows"
                      className="flex-1 accent-violet-500"
                    />
                    <span className="w-8 tabular-nums">{draft.hookDuration}s</span>
                  </label>
                </>
              )}
            </div>
            <label className="flex items-center justify-between gap-3">
              <span>
                <span className="font-medium">Captions</span>
                <span className="block text-xs text-white/50">Subtitles burned into the video</span>
              </span>
              <input
                type="checkbox"
                className="h-5 w-5 accent-violet-500"
                checked={draft.captions}
                disabled={locked}
                onChange={(e) => change({ captions: e.target.checked })}
              />
            </label>
          </div>
        )}

        {plan.warnings.length > 0 && <p className="text-xs text-white/40">Notes: {plan.warnings.join(" · ")}</p>}

        <div className="sticky bottom-3 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/15 bg-[#14141b]/95 px-4 py-3 shadow-xl backdrop-blur">
          {isCurrent ? (
            <>
              <p className="min-w-0 text-sm">
                {dirty ? (
                  <>
                    <span className="font-medium">Unsaved changes</span>
                    <span className="text-white/50"> · {changedAreas.join(", ")}</span>
                  </>
                ) : (
                  <span className="text-white/50">Make a change above, then apply it to get a new version.</span>
                )}
                {error && (
                  <span role="alert" className="block text-xs text-red-300">
                    {error}
                  </span>
                )}
              </p>
              <div className="flex gap-2">
                {dirty && (
                  <button
                    disabled={working}
                    onClick={() => {
                      setDraft(draftFrom(plan));
                      setSelected(null);
                      setError(null);
                    }}
                    className="rounded-lg border border-white/15 px-3 py-2 text-sm text-white/70 hover:bg-white/5"
                  >
                    Discard
                  </button>
                )}
                <button
                  disabled={!canApply}
                  onClick={() => run(() => onApply(edit))}
                  className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold hover:bg-violet-500 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-white/30"
                >
                  {working ? "Applying…" : "Apply & render"}
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="text-sm text-white/60">You&apos;re looking at an older version (v{shown.version}).</p>
              <button
                disabled={busy || working}
                onClick={() => run(() => onRestore(shown.version))}
                className="rounded-lg border border-white/20 px-4 py-2 text-sm font-medium hover:bg-white/5 disabled:opacity-40"
              >
                {working ? "Restoring…" : `Go back to version ${shown.version}`}
              </button>
              {error && (
                <span role="alert" className="w-full text-xs text-red-300">
                  {error}
                </span>
              )}
            </>
          )}
        </div>
      </section>
    </div>
  );
}
