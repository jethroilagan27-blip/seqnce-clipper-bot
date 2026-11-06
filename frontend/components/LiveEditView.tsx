"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { getAnalysis, postTimeline, type Analysis, type Job, type TimelineSpec } from "@/lib/api";
import LivePreview, { type PreviewHandle } from "./LivePreview";
import Timeline from "./Timeline";
import TranscriptEditor from "./TranscriptEditor";
import type { DraftClip } from "@/lib/timeline";

// Shown while a video is still being processed: the transcript appears as soon as it exists, and the
// AI's plan becomes a playable preview + timeline before the final file has finished rendering.
export default function LiveEditView({ job }: { job: Job }) {
  const previewRef = useRef<PreviewHandle>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [spec, setSpec] = useState<TimelineSpec | null>(null);
  const [playhead, setPlayhead] = useState<number | null>(null);
  const plan = analysis?.plan ?? null;
  const hasPlan = !!plan;

  // The transcript and plan are saved as the pipeline moves on; look again whenever the stage changes.
  useEffect(() => {
    let cancelled = false;
    getAnalysis(job.id)
      .then((a) => !cancelled && setAnalysis(a))
      .catch(() => {}); // 409 until the transcript exists
    return () => {
      cancelled = true;
    };
  }, [job.id, job.stage]);

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

  const segments = useMemo(() => analysis?.transcript.segments ?? [], [analysis]);
  const boundaries = useMemo(() => segments.flatMap((s) => (s.words ?? []).flatMap((w) => [w.start, w.end])), [segments]);
  const duration = analysis?.transcript.duration ?? job.original?.duration ?? 1;
  const clips: DraftClip[] = useMemo(
    () => (plan?.clips ?? []).map((c) => ({ start: c.start, end: c.end, purpose: c.purpose, reason: c.reason })),
    [plan],
  );
  // Before the plan exists nothing is cut yet: show the whole transcript as "kept".
  const shownClips = hasPlan ? clips : [{ start: 0, end: duration + 1, purpose: "main_content" as const, reason: "" }];

  if (!analysis) return null;

  return (
    <section className="space-y-4 rounded-2xl border border-white/10 p-4" aria-label="Live edit">
      <div>
        <h2 className="font-medium">Watch it being edited</h2>
        <p className="text-xs text-white/50">
          {hasPlan
            ? `The AI chose ${clips.length} clip${clips.length === 1 ? "" : "s"}. Play the preview now; the final video is still rendering.`
            : "The transcript is ready. The AI is choosing what to keep…"}
        </p>
      </div>

      {spec && <LivePreview ref={previewRef} jobId={job.id} spec={spec} onTime={(src) => setPlayhead(src)} />}

      {hasPlan && (
        <Timeline
          duration={duration}
          clips={clips}
          segments={segments}
          boundaries={boundaries}
          playheadSrc={playhead}
          editable={false}
          onChange={() => {}}
          onSeek={(src) => previewRef.current?.seekSource(src)}
        />
      )}

      <TranscriptEditor
        segments={segments}
        clips={shownClips}
        playheadSrc={playhead}
        editable={false}
        onToggle={() => {}}
        onSeek={(src) => previewRef.current?.seekSource(src)}
      />
    </section>
  );
}
