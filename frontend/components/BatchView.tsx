"use client";

import { formatBytes } from "@/lib/api";
import { folderOf } from "@/lib/pickFiles";
import type { BatchRow, BatchStatus } from "@/lib/batch";

type Props = {
  rows: BatchRow[];
  running: boolean;
  onOpen: (jobId: string) => void;
  onCancel: () => void;
  onNew: () => void;
};

const LABEL: Record<BatchStatus, string> = {
  waiting: "Waiting",
  uploading: "Uploading",
  processing: "Editing",
  done: "Done",
  failed: "Failed",
  stopped: "Not edited",
};
const TONE: Record<BatchStatus, string> = {
  waiting: "text-white/50",
  uploading: "text-violet-300",
  processing: "text-violet-300",
  done: "text-emerald-300",
  failed: "text-red-300",
  stopped: "text-amber-300",
};

/** The list shown while many videos are edited one after another. Each finished video opens like a normal result. */
export default function BatchView({ rows, running, onOpen, onCancel, onNew }: Props) {
  const done = rows.filter((r) => r.status === "done").length;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">
          {running ? "Editing your videos one after another" : "Your videos"} <span className="text-sm font-normal text-white/50">· {done} of {rows.length} done</span>
        </h2>
        {running ? (
          <button onClick={onCancel} className="rounded-lg border border-white/15 px-3 py-1.5 text-sm text-white/70 hover:bg-white/5">
            Stop after this video
          </button>
        ) : (
          <button onClick={onNew} className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold hover:bg-violet-500">
            Send more videos
          </button>
        )}
      </div>
      {running && <p className="text-xs text-white/40">Keep this page open. Each video is sent when the one before it is finished, so they stay within your daily limit.</p>}

      <ul className="space-y-2">
        {rows.map((r) => {
          const folder = folderOf(r.path);
          const active = r.status === "uploading" || r.status === "processing";
          return (
            <li key={r.key} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
              <div className="flex items-center gap-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium" title={r.path}>
                    {folder && <span className="text-white/40">{folder}/</span>}
                    {r.name}
                  </p>
                  <p className="text-xs text-white/40">{formatBytes(r.size)}</p>
                </div>
                <span className={`shrink-0 text-xs font-semibold ${TONE[r.status]}`}>{LABEL[r.status]}</span>
                {r.jobId && (r.status === "done" || r.status === "processing") && (
                  <button onClick={() => onOpen(r.jobId!)} className="shrink-0 rounded-lg border border-white/15 px-3 py-1 text-xs hover:bg-white/5">
                    {r.status === "done" ? "Open" : "Watch"}
                  </button>
                )}
              </div>
              {active && (
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10">
                  <div className="h-full bg-violet-500 transition-[width]" style={{ width: `${Math.round(r.progress * 100)}%` }} />
                </div>
              )}
              {r.message && <p className={`mt-1.5 text-xs ${r.status === "failed" ? "text-red-200" : r.status === "stopped" ? "text-amber-200" : "text-white/50"}`}>{r.message}</p>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
