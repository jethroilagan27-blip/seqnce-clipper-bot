"use client";

import { useEffect, useEffectEvent, useRef, useState } from "react";
import AuthGate, { type AccountInfo } from "@/components/AuthGate";
import BatchView from "@/components/BatchView";
import HomeLauncher from "@/components/HomeLauncher";
import ProcessingView from "@/components/ProcessingView";
import ResultView from "@/components/ResultView";
import Shell, { hasStudio, quotaBlock } from "@/components/Shell";
import UploadCard from "@/components/UploadCard";
import {
  ApiError,
  JOB_STORAGE_KEY,
  getJob,
  getResult,
  getVersions,
  postRevision,
  uploadVideo,
  type EditSettings,
  type Job,
  type JobResult,
  type RevisionBody,
  type Versions,
} from "@/lib/api";
import { createBatch, type Batch, type BatchRow } from "@/lib/batch";
import { onHomeRequest, takeHomeRequest } from "@/lib/home";
import type { Picked } from "@/lib/pickFiles";

const POLL_MS = 1500;
const BATCH_KEY = "seqnce:batch";

function saveBatch(rows: BatchRow[] | null) {
  try {
    if (rows) localStorage.setItem(BATCH_KEY, JSON.stringify(rows));
    else localStorage.removeItem(BATCH_KEY);
  } catch {
    /* ignore */
  }
}

/** After a page reload the queue itself is gone (the files were in the page), but the videos already sent keep being edited. */
function restoreBatch(): BatchRow[] | null {
  try {
    const raw = localStorage.getItem(BATCH_KEY);
    const rows = raw ? (JSON.parse(raw) as BatchRow[]) : null;
    if (!Array.isArray(rows) || rows.length === 0) return null;
    return rows.map((r) =>
      r.status === "waiting" || r.status === "uploading"
        ? { ...r, status: "stopped", message: "The page was reloaded before this video was sent." }
        : r.status === "processing"
          ? { ...r, message: "Open it to see how far it is." }
          : r,
    );
  } catch {
    return null;
  }
}

function remember(id: string | null) {
  try {
    if (id) localStorage.setItem(JOB_STORAGE_KEY, id);
    else localStorage.removeItem(JOB_STORAGE_KEY);
  } catch {
    /* storage unavailable (private mode): resume simply won't work */
  }
}

export default function Page() {
  return <AuthGate>{(account) => <Studio account={account} />}</AuthGate>;
}

function Studio({ account }: { account: AccountInfo }) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [result, setResult] = useState<JobResult | null>(null);
  const [versions, setVersions] = useState<Versions | null>(null);
  const [pollNonce, setPollNonce] = useState(0); // bump to restart polling (e.g. after a revision is queued)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const loadedRef = useRef(false); // result + versions fetched for the current job
  const [batchRows, setBatchRows] = useState<BatchRow[] | null>(null); // many videos edited one after another
  const [batchRunning, setBatchRunning] = useState(false);
  const batchRef = useRef<Batch | null>(null);
  const [phonePick, setPhonePick] = useState<{ items: Picked[]; style: "talking" | "highlight"; key: number } | null>(null); // chosen on the start screen
  const busyRef = useRef(false); // something is being sent from this page: don't throw it away

  // Resume a job (or the list of a batch) after a page refresh.
  useEffect(() => {
    try {
      const saved = localStorage.getItem(JOB_STORAGE_KEY);
      // Deferred (not synchronous) so the first client render matches the server render.
      if (saved && /^[0-9a-f]{32}$/.test(saved)) queueMicrotask(() => setJobId(saved));
      const rows = restoreBatch();
      if (rows) queueMicrotask(() => setBatchRows(rows));
    } catch {
      /* ignore */
    }
  }, []);

  // Poll the backend until the job reaches a terminal state.
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      try {
        const j = await getJob(jobId);
        if (cancelled) return;
        setJob(j);
        if (j.has_output && (j.status === "completed" || j.revising)) {
          // Load the finished video once, and again whenever a revision finishes.
          if (!j.revising || !loadedRef.current) {
            const [r, v] = await Promise.all([getResult(jobId), getVersions(jobId)]);
            if (cancelled) return;
            setResult(r);
            setVersions(v);
            loadedRef.current = true;
          }
          if (!j.revising) return;
        } else if (j.status === "completed" || j.status === "failed") {
          return;
        }
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.message === "Job not found") {
          remember(null);
          setJobId(null);
          setError("That job no longer exists.");
          return;
        }
        // transient network error: keep polling
      }
      timer = setTimeout(tick, POLL_MS);
    };
    tick();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId, pollNonce]);

  async function handleStart(file: File, settings: EditSettings) {
    setError(null);
    setUploadProgress(0);
    const { promise, abort } = uploadVideo(file, settings, setUploadProgress);
    abortRef.current = abort;
    try {
      const id = await promise;
      remember(id);
      setJobId(id);
      setPhonePick(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      abortRef.current = null;
      setUploadProgress(null);
      account.refresh(); // the quota changed (or the server said why not)
    }
  }

  /** Many videos: each is sent after the one before it is finished (the server edits one at a time per person). */
  function handleStartBatch(items: Picked[], settings: EditSettings) {
    setError(null);
    const batch = createBatch(
      items,
      settings,
      {
        upload: (file, s, onProgress) => uploadVideo(file, s, onProgress),
        poll: async (id) => {
          const j = await getJob(id);
          return { status: j.status, progress: j.progress, stage: j.stage, error: j.error };
        },
        sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
      },
      (rows) => {
        setBatchRows(rows);
        saveBatch(rows);
        account.refresh(); // a video was sent: the daily count changed
      },
    );
    batchRef.current = batch;
    setPhonePick(null);
    setBatchRows(batch.rows());
    setBatchRunning(true);
    void batch.start().finally(() => {
      setBatchRunning(false);
      account.refresh();
    });
  }

  function openFromBatch(id: string) {
    remember(id);
    setJobId(id);
  }

  function newUpload() {
    batchRef.current = null;
    setBatchRows(null);
    saveBatch(null);
  }

  async function handleRevise(body: RevisionBody): Promise<string | null> {
    if (!jobId) return "No video is open.";
    try {
      await postRevision(jobId, body);
    } catch (e) {
      account.refresh();
      return e instanceof Error ? e.message : "Something went wrong.";
    }
    account.refresh(); // chat messages count against the daily limit
    // Show "working" immediately; polling takes over from here.
    setJob((prev) => (prev ? { ...prev, status: "queued", revising: true, error: null, progress: 50 } : prev));
    setPollNonce((n) => n + 1);
    return null;
  }

  function reset() {
    loadedRef.current = false;
    setVersions(null);
    remember(null);
    setJobId(null);
    setJob(null);
    setResult(null);
    setError(null);
    account.refresh();
  }

  // The "Edit" tab: back to the start screen. Videos already sent keep being edited (they are in the Library).
  const goHome = useEffectEvent(() => {
    if (!takeHomeRequest() || busyRef.current) return;
    newUpload();
    setPhonePick(null);
    reset();
  });
  useEffect(() => {
    goHome(); // asked for while another page was showing
    return onHomeRequest(() => goHome());
  }, []);
  useEffect(() => {
    busyRef.current = uploadProgress !== null || batchRunning;
  }, [uploadProgress, batchRunning]);

  const view = result ? "result" : jobId ? "processing" : batchRows ? "batch" : "upload";
  const blocked = quotaBlock(account.user?.quota.videos, "video", "videos");

  return (
    <Shell user={account.user} onSignOut={account.user ? account.signOut : undefined} wide={view === "result"} section="video">
      {view === "upload" && !phonePick && (
        <div className="sm:hidden">
          <HomeLauncher studio={hasStudio(account.user)} blockedReason={blocked} error={error} onPick={(items, style) => setPhonePick({ items, style, key: Date.now() })} />
        </div>
      )}

      {view === "upload" && (
        // Phones show this once videos are chosen; wider screens show it straight away.
        <div className={phonePick ? "space-y-4" : "hidden sm:block"}>
          {phonePick && uploadProgress === null && (
            <button type="button" onClick={() => setPhonePick(null)} className="text-sm text-violet-300 underline sm:hidden">
              ← Back
            </button>
          )}
          <UploadCard
            key={phonePick?.key ?? 0}
            initialItems={phonePick?.items}
            initialStyle={phonePick?.style}
            busy={uploadProgress !== null}
            uploadProgress={uploadProgress}
            error={error}
            blockedReason={blocked}
            onStart={handleStart}
            onStartBatch={handleStartBatch}
            onCancel={() => abortRef.current?.()}
          />
        </div>
      )}

      {view === "batch" && batchRows && (
        <BatchView rows={batchRows} running={batchRunning} onOpen={openFromBatch} onCancel={() => batchRef.current?.cancel()} onNew={newUpload} />
      )}

      {view === "processing" &&
        (job ? (
          <ProcessingView job={job} onRestart={reset} />
        ) : (
          <p className="text-white/50">Starting…</p>
        ))}

      {view === "result" && result && (
        <ResultView result={result} job={job} versions={versions} onRevise={handleRevise} onRestart={reset} />
      )}
    </Shell>
  );
}
