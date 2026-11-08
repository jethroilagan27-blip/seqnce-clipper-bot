"use client";

import { useEffect, useRef, useState } from "react";
import AuthGate, { type AccountInfo } from "@/components/AuthGate";
import ProcessingView from "@/components/ProcessingView";
import ResultView from "@/components/ResultView";
import Shell, { quotaBlock } from "@/components/Shell";
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

const POLL_MS = 1500;

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

  // Resume a job after a page refresh.
  useEffect(() => {
    try {
      const saved = localStorage.getItem(JOB_STORAGE_KEY);
      // Deferred (not synchronous) so the first client render matches the server render.
      if (saved && /^[0-9a-f]{32}$/.test(saved)) queueMicrotask(() => setJobId(saved));
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
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      abortRef.current = null;
      setUploadProgress(null);
      account.refresh(); // the quota changed (or the server said why not)
    }
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

  const view = result ? "result" : jobId ? "processing" : "upload";

  return (
    <Shell user={account.user} onSignOut={account.user ? account.signOut : undefined} wide={view === "result"} section="video">
      {view === "upload" && (
        <UploadCard
          busy={uploadProgress !== null}
          uploadProgress={uploadProgress}
          error={error}
          blockedReason={quotaBlock(account.user?.quota.videos, "video", "videos")}
          onStart={handleStart}
          onCancel={() => abortRef.current?.()}
        />
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
