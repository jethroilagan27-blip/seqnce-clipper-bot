"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { getAnalysis, originalUrl, postTimeline, type Analysis, type Job, type TimelineSpec } from "@/lib/api";
import { formatTime, type DraftClip } from "@/lib/timeline";
import LivePreview, { type PreviewHandle } from "./LivePreview";
import Overview from "./Overview";
import PartsPanel from "./PartsPanel";

const REVEAL_MS = 500; // one AI-chosen part appears on the map every half second

function LiveTranscript({ segments }: { segments: { start: number; text: string }[] }) {
  const box = useRef<HTMLUListElement>(null);
  useEffect(() => {
    const el = box.current;
    if (el) el.scrollTop = el.scrollHeight; // follow the newest line
  }, [segments.length]);
  return (
    <ul ref={box} className="max-h-56 space-y-1 overflow-y-auto pr-1 text-sm" aria-label="Transcript so far" aria-live="off">
      {segments.map((s, i) => (
        <li key={i} className="seqnce-in flex gap-2">
          <span className="w-10 shrink-0 text-xs tabular-nums text-violet-300">{formatTime(s.start).replace(/\.\d$/, "")}</span>
          <span className="text-white/80">{s.text.trim()}</span>
        </li>
      ))}
    </ul>
  );
}

// Shown while a video is still being processed, so you can see the work happen instead of waiting on a
// bar: the transcript grows while Whisper listens, the AI's chosen parts pop onto a map of your video
// one by one, and the preview is playable before the final file has finished rendering.
export default function LiveEditView({ job }: { job: Job }) {
  const previewRef = useRef<PreviewHandle>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [spec, setSpec] = useState<TimelineSpec | null>(null);
  const [playhead, setPlayhead] = useState<number | null>(null);
  const [revealed, setRevealed] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);

  const plan = analysis?.plan ?? null;
  const hasPlan = !!plan;
  const transcribing = job.stage === "transcribing";

  // The transcript is saved as Whisper goes (every ~1.5 s) and the plan when the AI is done:
  // keep looking while transcribing, and look again whenever the stage changes.
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      getAnalysis(job.id)
        .then((a) => !cancelled && setAnalysis(a))
        .catch(() => {}); // 409 until the first words exist
    load();
    const timer = transcribing ? setInterval(load, 2000) : undefined;
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [job.id, job.stage, transcribing]);

  useEffect(() => {
    if (!hasPlan) return;
    let cancelled = false;
    postTimeline(job.id)
      .then((s) => !cancelled && setSpec(s))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [job.id, hasPlan]);

  const clips: DraftClip[] = useMemo(
    () => (plan?.clips ?? []).map((c) => ({ start: c.start, end: c.end, purpose: c.purpose, reason: c.reason })),
    [plan],
  );
  const segments = useMemo(() => analysis?.transcript.segments ?? [], [analysis]);
  const boundaries = useMemo(() => segments.flatMap((s) => (s.words ?? []).flatMap((w) => [w.start, w.end])), [segments]);

  // Reveal the chosen parts one at a time.
  useEffect(() => {
    if (!hasPlan || revealed >= clips.length) return;
    const t = setTimeout(() => setRevealed((r) => r + 1), REVEAL_MS);
    return () => clearTimeout(t);
  }, [hasPlan, revealed, clips.length]);

  if (!analysis) {
    return (
      <p className="text-center text-sm text-white/40">Getting ready… the first words will show up here as they are recognised.</p>
    );
  }

  const duration = analysis.transcript.duration || job.original?.duration || 1;
  const aspect = job.original ? job.original.width / job.original.height : 16 / 9;
  const heard = segments.length ? segments[segments.length - 1].end : 0;
  const donePct = Math.min(100, Math.round((heard / duration) * 100));
  const revealing = hasPlan && revealed < clips.length;

  let title = "Looking at your video…";
  let sub = "Picking sample frames to understand who is speaking and how they are framed.";
  if (transcribing) {
    title = "Listening to your video…";
    sub = "The transcript appears as it is recognised. You can watch your video while you wait.";
  } else if (job.stage === "planning" && !hasPlan) {
    title = "The AI is choosing the best moments…";
    sub = "It reads the transcript and decides which parts make a strong short.";
  } else if (hasPlan) {
    title = revealing ? `The AI is picking parts… ${revealed} of ${clips.length}` : `The AI picked ${clips.length} part${clips.length === 1 ? "" : "s"}`;
    sub = `Play the preview now. The final video is still being rendered (${job.progress}%).`;
  }

  return (
    <section className="space-y-4 rounded-2xl border border-white/10 p-4" aria-label="Live edit">
      <div>
        <h2 className="font-medium">{title}</h2>
        <p className="text-xs text-white/50">{sub}</p>
      </div>

      {transcribing && (
        <div className="space-y-1">
          <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
            <div className="h-full bg-violet-400 transition-[width] duration-700" style={{ width: `${donePct}%` }} />
          </div>
          <p className="text-xs tabular-nums text-white/50">
            Understood {formatTime(heard).replace(/\.\d$/, "")} of {formatTime(duration).replace(/\.\d$/, "")} ({donePct}%)
          </p>
          <video
            src={originalUrl(job.id)}
            controls
            preload="metadata"
            playsInline
            className="mx-auto mt-3 max-h-64 rounded-lg bg-black"
            aria-label="Your uploaded video"
          />
        </div>
      )}

      {!transcribing && (
        <Overview
          jobId={job.id}
          duration={duration}
          aspect={aspect}
          clips={hasPlan ? clips.slice(0, revealed) : []}
          selected={selected}
          playheadSrc={playhead}
          pending={!hasPlan}
          onSelect={setSelected}
          onSeek={(src) => previewRef.current?.seekSource(src)}
        />
      )}

      {spec && hasPlan && <LivePreview ref={previewRef} jobId={job.id} spec={spec} onTime={(src) => setPlayhead(src)} />}

      {hasPlan && !revealing && (
        <PartsPanel
          jobId={job.id}
          aspect={aspect}
          duration={duration}
          clips={clips}
          segments={segments}
          boundaries={boundaries}
          selected={selected}
          playheadSrc={playhead}
          editable={false}
          onSelect={setSelected}
          onChange={() => {}}
          onSeek={(src) => previewRef.current?.seekSource(src)}
        />
      )}

      {!hasPlan && segments.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs text-white/50">
            {transcribing ? "What was said so far" : `Transcript (${segments.length} sentences)`}
          </p>
          <LiveTranscript segments={segments} />
        </div>
      )}
    </section>
  );
}
