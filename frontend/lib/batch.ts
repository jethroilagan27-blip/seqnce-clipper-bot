// Sending many videos from "Edit with video": one after another. The server edits one video per person at a time
// (and counts each against the daily limit), so the queue uploads a video, waits until it is finished, then sends
// the next. No React and no `@/` imports (the server calls are passed in), so `npm test` can run it.

import type { Picked } from "./pickFiles.ts";

export type BatchStatus = "waiting" | "uploading" | "processing" | "done" | "failed" | "stopped";

export type BatchRow = {
  key: number;
  path: string;
  name: string;
  size: number;
  status: BatchStatus;
  /** Upload progress while uploading, the server's progress while processing (0..1). */
  progress: number;
  jobId: string | null;
  /** Why it failed or stopped, or what the server is doing. */
  message: string | null;
};

export type JobPoll = { status: string; progress: number; stage?: string | null; error?: string | null };

export type BatchDeps<S> = {
  upload: (file: File, settings: S, onProgress: (fraction: number) => void) => { promise: Promise<string>; abort: () => void };
  poll: (jobId: string) => Promise<JobPoll>;
  sleep: (ms: number) => Promise<void>;
};

export type Batch = {
  start: () => Promise<void>;
  cancel: () => void;
  rows: () => BatchRow[];
};

const POLL_MS = 1500;
const BUSY_RETRIES = 120; // "you already have a video being made" from an earlier visit: wait for it (up to ~10 minutes)

export const isLimitMessage = (m: string) => /last 24 hours|daily limit|too many/i.test(m);
export const isBusyMessage = (m: string) => /already have a video/i.test(m);

export function makeRows(items: Picked[]): BatchRow[] {
  return items.map((it, i) => ({
    key: i,
    path: it.path,
    name: it.path.slice(it.path.lastIndexOf("/") + 1),
    size: it.file.size,
    status: "waiting",
    progress: 0,
    jobId: null,
    message: null,
  }));
}

export function createBatch<S>(items: Picked[], settings: S, deps: BatchDeps<S>, onChange: (rows: BatchRow[]) => void): Batch {
  let rows = makeRows(items);
  let cancelled = false;
  let abortCurrent: (() => void) | null = null;

  const patch = (key: number, p: Partial<BatchRow>) => {
    rows = rows.map((r) => (r.key === key ? { ...r, ...p } : r));
    onChange(rows);
  };
  const stopRest = (from: number, message: string) => {
    rows = rows.map((r) => (r.key >= from && r.status === "waiting" ? { ...r, status: "stopped", message } : r));
    onChange(rows);
  };

  async function uploadOne(i: number): Promise<{ ok: true; jobId: string } | { ok: false; message: string }> {
    for (let attempt = 0; attempt <= BUSY_RETRIES; attempt++) {
      if (cancelled) return { ok: false, message: "Cancelled." };
      patch(i, { status: "uploading", progress: 0, message: attempt > 0 ? "Waiting for your other video to finish…" : null });
      const up = deps.upload(items[i].file, settings, (f) => patch(i, { progress: f }));
      abortCurrent = up.abort;
      try {
        return { ok: true, jobId: await up.promise };
      } catch (e) {
        const message = e instanceof Error ? e.message : "Upload failed.";
        if (isBusyMessage(message) && !cancelled) {
          await deps.sleep(5000);
          continue;
        }
        return { ok: false, message: cancelled ? "Cancelled." : message };
      } finally {
        abortCurrent = null;
      }
    }
    return { ok: false, message: "Your other video didn't finish in time." };
  }

  async function start() {
    for (let i = 0; i < items.length; i++) {
      if (cancelled) {
        stopRest(i, "Cancelled.");
        return;
      }
      const sent = await uploadOne(i);
      if (!sent.ok) {
        patch(i, { status: cancelled ? "stopped" : "failed", message: sent.message });
        if (cancelled) {
          stopRest(i + 1, "Cancelled.");
          return;
        }
        if (isLimitMessage(sent.message)) {
          stopRest(i + 1, "Not sent: " + sent.message); // today's videos are used up: sending more only repeats the refusal
          return;
        }
        continue; // a problem with this one file: carry on with the next
      }
      patch(i, { status: "processing", progress: 0, jobId: sent.jobId, message: null });
      for (;;) {
        if (cancelled) {
          stopRest(i + 1, "Cancelled.");
          return; // this video keeps being edited by the server; it can still be opened from its row
        }
        let job: JobPoll | null = null;
        try {
          job = await deps.poll(sent.jobId);
        } catch {
          /* a network hiccup: ask again */
        }
        if (job) {
          if (job.status === "completed") {
            patch(i, { status: "done", progress: 1, message: null });
            break;
          }
          if (job.status === "failed") {
            patch(i, { status: "failed", message: job.error || "The edit failed." });
            break;
          }
          patch(i, { progress: Math.min(Math.max((job.progress ?? 0) / 100, 0), 1), message: job.stage ?? null });
        }
        await deps.sleep(POLL_MS);
      }
    }
  }

  return {
    start,
    cancel: () => {
      cancelled = true;
      abortCurrent?.();
    },
    rows: () => rows,
  };
}
