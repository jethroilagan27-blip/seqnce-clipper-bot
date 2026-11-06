"use client";

import { API_URL, formatBytes, formatDuration, type JobResult, type VideoInfo } from "@/lib/api";

function InfoCard({ title, info }: { title: string; info: VideoInfo | null }) {
  return (
    <div className="rounded-lg border border-white/10 p-4 text-sm">
      <p className="mb-2 font-medium">{title}</p>
      {info ? (
        <dl className="space-y-1 text-white/60">
          <div className="flex justify-between"><dt>Length</dt><dd>{formatDuration(info.duration)}</dd></div>
          <div className="flex justify-between"><dt>Resolution</dt><dd>{info.width}×{info.height}</dd></div>
          <div className="flex justify-between"><dt>Frame rate</dt><dd>{info.fps} fps</dd></div>
          <div className="flex justify-between"><dt>Size</dt><dd>{formatBytes(info.size_bytes)}</dd></div>
        </dl>
      ) : (
        <p className="text-white/40">Not available</p>
      )}
    </div>
  );
}

function PlanSummary({ plan }: { plan: NonNullable<JobResult["plan"]> }) {
  return (
    <div className="space-y-3 rounded-lg border border-white/10 p-4 text-sm">
      <div className="flex items-center justify-between gap-3">
        <p className="font-medium">What was kept</p>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs ${
            plan.source === "ai" ? "bg-violet-500/20 text-violet-200" : "bg-amber-400/20 text-amber-100"
          }`}
        >
          {plan.source === "ai" ? "Chosen by AI" : "Basic cut (AI unavailable)"}
        </span>
      </div>
      {plan.summary.main_message && <p className="text-white/70">{plan.summary.main_message}</p>}
      <ul className="space-y-1.5">
        {plan.clips.map((c) => (
          <li key={c.id} className="flex gap-3 text-white/60">
            <span className="w-24 shrink-0 tabular-nums text-violet-300">
              {formatDuration(c.start)}–{formatDuration(c.end)}
            </span>
            <span>
              <span className="text-white/80">{c.purpose.replace("_", " ")}</span>
              {c.reason && <> — {c.reason}</>}
            </span>
          </li>
        ))}
      </ul>
      {plan.source === "fallback" && plan.fallback_reason && (
        <p className="text-xs text-amber-100/80">Why: {plan.fallback_reason}</p>
      )}
      {plan.warnings.length > 0 && <p className="text-xs text-white/40">Notes: {plan.warnings.join(" · ")}</p>}
    </div>
  );
}

export default function ResultView({ result, onRestart }: { result: JobResult; onRestart: () => void }) {
  return (
    <div className="space-y-6">
      <div className="mx-auto aspect-[9/16] max-h-[70vh] overflow-hidden rounded-2xl border border-white/10 bg-black">
        <video
          src={`${API_URL}${result.preview_url}`}
          controls
          playsInline
          className="h-full w-full object-contain"
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <InfoCard title="Original" info={result.original} />
        <InfoCard title="Edited" info={result.rendered} />
      </div>
      {result.plan && <PlanSummary plan={result.plan} />}
      <div className="flex flex-col gap-3 sm:flex-row">
        <a
          href={`${API_URL}${result.download_url}`}
          className="flex-1 rounded-xl bg-violet-600 px-6 py-3.5 text-center font-semibold text-white hover:bg-violet-500"
        >
          Download MP4
        </a>
        <button
          onClick={onRestart}
          className="flex-1 rounded-xl border border-white/20 px-6 py-3.5 font-medium hover:bg-white/5"
        >
          Edit another video
        </button>
      </div>
    </div>
  );
}
