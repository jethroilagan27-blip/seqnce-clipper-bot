"use client";

import { useEffect, useState } from "react";
import { formatBytes, formatDuration, getAnalysis, type Analysis, type Job } from "@/lib/api";

function AnalysisPreview({ jobId }: { jobId: string }) {
  const [data, setData] = useState<Analysis | null>(null);
  useEffect(() => {
    let cancelled = false;
    getAnalysis(jobId)
      .then((a) => !cancelled && setData(a))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [jobId]);
  if (!data) return null;
  const v = data.visual;
  return (
    <div className="space-y-3 text-sm">
      {v && (
        <div className="rounded-lg border border-white/10 p-4 text-white/70">
          <p className="mb-1 font-medium text-white">
            Visual analysis{" "}
            <span className="text-xs font-normal text-white/40">
              ({v.analysis_source === "ai" ? "Gemini" : "AI unavailable – default centre crop"})
            </span>
          </p>
          <p>
            {v.main_subject} · {v.framing.replace("_", " ")} · speaker at {Math.round(v.speaker_focus_x * 100)}%
            · {v.suitable_for_vertical ? "good" : "poor"} for vertical
          </p>
          <p className="text-xs text-white/40">
            {v.frames_sampled} frames sampled · {v.frames_sent_to_ai} sent to AI · {v.scene_changes.length} scene
            changes
          </p>
        </div>
      )}
      <details className="rounded-lg border border-white/10 p-4" open>
        <summary className="cursor-pointer font-medium">
          Transcript ({data.transcript.language}, {data.transcript.segments.length} segments)
        </summary>
        <ul className="mt-3 max-h-64 space-y-1.5 overflow-y-auto text-white/70">
          {data.transcript.segments.map((s, i) => (
            <li key={i}>
              <span className="mr-2 tabular-nums text-xs text-violet-300">{formatDuration(s.start)}</span>
              {s.text}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

// Mirrors backend/app/stages.py
const STEPS: { key: string; label: string }[] = [
  { key: "uploaded", label: "Uploading video" },
  { key: "preparing", label: "Preparing footage" },
  { key: "transcribing", label: "Transcribing speech" },
  { key: "analyzing_visuals", label: "Analyzing visuals" },
  { key: "planning", label: "Generating editing plan" },
  { key: "editing", label: "Editing video" },
  { key: "rendering", label: "Rendering final output" },
  { key: "completed", label: "Completed" },
];

type Props = { job: Job; onRestart: () => void };

export default function ProcessingView({ job, onRestart }: Props) {
  const failed = job.status === "failed";
  const preparedOnly = job.status === "completed" && !job.has_output;
  const current = Math.max(0, STEPS.findIndex((s) => s.key === job.stage));

  function stateOf(i: number): "done" | "active" | "todo" {
    if (job.status === "completed" && job.has_output) return "done";
    if (preparedOnly && i <= current) return "done";
    if (i < current) return "done";
    if (i === current) return failed ? "todo" : "active";
    return "todo";
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-white/50">Editing</p>
        <p className="font-medium break-all">{job.original_filename}</p>
        {job.original && (
          <p className="text-xs text-white/40">
            {formatDuration(job.original.duration)} · {job.original.width}×{job.original.height} ·{" "}
            {job.original.fps} fps · {formatBytes(job.original.size_bytes)}
            {!job.original.has_audio && " · no audio track"}
          </p>
        )}
      </div>

      {!failed && (
        <div className="h-2 overflow-hidden rounded-full bg-white/10">
          <div
            className="h-full bg-violet-500 transition-[width] duration-500"
            style={{ width: `${job.progress}%` }}
          />
        </div>
      )}

      <ol className="space-y-2">
        {STEPS.map((s, i) => {
          const st = stateOf(i);
          return (
            <li key={s.key} className="flex items-center gap-3 text-sm">
              <span
                className={`flex h-6 w-6 items-center justify-center rounded-full text-xs ${
                  st === "done"
                    ? "bg-emerald-500/20 text-emerald-300"
                    : st === "active"
                      ? "animate-pulse bg-violet-500/30 text-violet-200"
                      : "bg-white/5 text-white/30"
                }`}
              >
                {st === "done" ? "✓" : i + 1}
              </span>
              <span className={st === "todo" ? "text-white/35" : st === "active" ? "font-medium" : "text-white/70"}>
                {s.label}
                {st === "active" && job.status === "queued" && " (waiting in queue)"}
              </span>
            </li>
          );
        })}
      </ol>

      {failed && (
        <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          <span className="font-medium">Processing failed.</span> {job.error ?? "Unknown error."}
        </p>
      )}

      {preparedOnly && (
        <>
          <p className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
            Transcript and visual analysis are ready. AI planning and rendering aren&apos;t built yet —
            this is the Day 3 milestone.
          </p>
          <AnalysisPreview jobId={job.id} />
        </>
      )}

      {(failed || preparedOnly) && (
        <button
          onClick={onRestart}
          className="w-full rounded-xl border border-white/20 px-6 py-3 font-medium hover:bg-white/5"
        >
          Edit another video
        </button>
      )}
    </div>
  );
}
