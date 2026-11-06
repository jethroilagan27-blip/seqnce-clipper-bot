"use client";

import { useEffect, useRef, useState } from "react";
import ProcessingView from "@/components/ProcessingView";
import ResultView from "@/components/ResultView";
import UploadCard from "@/components/UploadCard";
import {
  ApiError,
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
const STORAGE_KEY = "seqnce:jobId";

function remember(id: string | null) {
  try {
    if (id) localStorage.setItem(STORAGE_KEY, id);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable (private mode): resume simply won't work */
  }
}

export default function Home() {
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
      const saved = localStorage.getItem(STORAGE_KEY);
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
    }
  }

  async function handleRevise(body: RevisionBody): Promise<string | null> {
    if (!jobId) return "No video is open.";
    try {
      await postRevision(jobId, body);
    } catch (e) {
      return e instanceof Error ? e.message : "Something went wrong.";
    }
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
  }

  const view = result ? "result" : jobId ? "processing" : "upload";

  return (
    <main className={`mx-auto w-full flex-1 px-5 py-10 ${view === "result" ? "max-w-5xl" : "max-w-xl"}`}>
      <header className="mb-8 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-500 text-lg font-bold">
          S
        </div>
        <div>
          <h1 className="text-xl font-semibold leading-tight">Seqnce</h1>
          <p className="text-sm text-white/50">Turn raw footage into a ready-to-post short.</p>
        </div>
      </header>

      {view === "upload" && (
        <UploadCard
          busy={uploadProgress !== null}
          uploadProgress={uploadProgress}
          error={error}
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
    </main>
  );
}
