"use client";

import { useState } from "react";
import {
  formatBytes,
  formatDuration,
  type Job,
  type JobResult,
  type ManualEdit,
  type VideoInfo,
  type Versions,
} from "@/lib/api";
import EditWorkspace from "./EditWorkspace";
import RevisionPanel from "./RevisionPanel";

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

type Props = {
  result: JobResult;
  job: Job | null;
  versions: Versions | null;
  onRevise: (body: { message: string } | { edit: ManualEdit } | { restore_version: number }) => Promise<string | null>;
  onRestart: () => void;
};

export default function ResultView({ result, job, versions, onRevise, onRestart }: Props) {
  const current = versions?.current ?? result.version;
  // Which version is on screen. Remembered together with the current version it was picked under,
  // so a newly finished revision automatically takes over the screen.
  const [picked, setPicked] = useState<{ under: number; version: number } | null>(null);
  const selected = picked && picked.under === current ? picked.version : current;
  const select = (version: number) => setPicked({ under: current, version });

  const shown = versions?.versions.find((v) => v.version === selected) ?? null;
  const busy = !!job && (job.revising || job.status === "queued" || job.status === "running");

  const tabs =
    versions && versions.versions.length > 1 ? (
      <div className="flex flex-wrap items-center gap-1.5" role="tablist" aria-label="Versions">
        {versions.versions.map((v) => (
          <button
            key={v.version}
            role="tab"
            aria-selected={v.version === selected}
            onClick={() => select(v.version)}
            className={`rounded-full px-3 py-1 text-xs ${
              v.version === selected
                ? "bg-violet-600 font-semibold text-white"
                : "border border-white/15 text-white/60 hover:text-white"
            }`}
          >
            v{v.version}
            {v.version === current && " · latest"}
          </button>
        ))}
      </div>
    ) : null;

  return (
    <div className="space-y-6">
      {versions && job && shown ? (
        <EditWorkspace
          key={`${shown.version}-${current}`}
          jobId={result.job_id}
          shown={shown}
          isCurrent={shown.version === current}
          busy={busy}
          tabs={tabs}
          side={
            <RevisionPanel
              versions={versions.versions}
              selected={selected}
              job={job}
              busy={busy}
              onSend={(message) => onRevise({ message })}
              onSelect={select}
            />
          }
          onApply={(edit) => onRevise({ edit })}
          onRestore={(version) => onRevise({ restore_version: version })}
        />
      ) : (
        <p className="text-sm text-white/50">Loading your edit…</p>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <InfoCard title="Original" info={result.original} />
        <InfoCard title={`Edited${versions && versions.versions.length > 1 ? " (latest)" : ""}`} info={result.rendered} />
      </div>

      <button
        onClick={onRestart}
        className="w-full rounded-xl border border-white/20 px-6 py-3.5 font-medium hover:bg-white/5"
      >
        Edit another video
      </button>
    </div>
  );
}
