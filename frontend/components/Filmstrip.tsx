"use client";

import { useEffect, useRef, useState } from "react";
import { thumbUrl } from "@/lib/api";

type Props = {
  jobId: string;
  /** Range of the ORIGINAL video to show, in seconds. */
  start: number;
  end: number;
  /** width / height of the source video, so the tiles have the right shape. */
  aspect: number;
  /** Display height in px. */
  height: number;
  className?: string;
};

// A row of real video frames (like a video editor's timeline), cut on demand by the server.
export default function Filmstrip({ jobId, start, end, aspect, height, className = "" }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [count, setCount] = useState(6);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() =>
      setCount(Math.min(40, Math.max(1, Math.ceil(el.clientWidth / (height * Math.max(aspect, 0.3)))))),
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, [height, aspect]);

  const tile = (end - start) / count;
  return (
    <div
      ref={ref}
      aria-hidden
      className={`grid overflow-hidden bg-[#15151c] ${className}`}
      style={{ gridTemplateColumns: `repeat(${count}, minmax(0, 1fr))`, height }}
    >
      {Array.from({ length: count }, (_, i) => (
        // eslint-disable-next-line @next/next/no-img-element -- tiny server-cut frames, no optimisation wanted
        <img
          key={i}
          src={thumbUrl(jobId, start + (i + 0.5) * tile, height)}
          alt=""
          draggable={false}
          className="h-full w-full object-cover"
          onError={(e) => {
            e.currentTarget.style.visibility = "hidden";
          }}
        />
      ))}
    </div>
  );
}
