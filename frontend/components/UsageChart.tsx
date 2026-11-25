"use client";

import { useEffect, useRef, useState, type PointerEvent } from "react";
import { aiRequests, dayLabel, edits, labelledDays, niceTicks, type Counts } from "@/lib/usage";

export type Day = Counts & { date: string };

const SERIES = [
  { key: "edits", label: "Video edits", noun: "video edits", color: "var(--series-1)", value: edits },
  { key: "ai", label: "AI requests", noun: "AI requests", color: "var(--series-2)", value: aiRequests },
] as const;

const HEIGHT = 220;
const PAD = { top: 10, right: 12, bottom: 24, left: 34 };

/** Two lines over time (one scale): hover, touch or the arrow keys read a day; "Show as table" lists every number. */
export default function UsageChart({ days }: { days: Day[] }) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [at, setAt] = useState<number | null>(null);
  const [table, setTable] = useState(false);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => setWidth(el.clientWidth);
    measure();
    const watch = new ResizeObserver(measure);
    watch.observe(el);
    return () => watch.disconnect();
  }, []);

  const ticks = niceTicks(Math.max(0, ...days.flatMap((d) => SERIES.map((s) => s.value(d)))));
  const top = ticks[ticks.length - 1];
  const plotW = Math.max(width - PAD.left - PAD.right, 1);
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (days.length > 1 ? (i / (days.length - 1)) * plotW : plotW / 2);
  const y = (v: number) => PAD.top + plotH - (v / top) * plotH;
  const shown = at !== null && at < days.length ? at : null;

  function point(e: PointerEvent<SVGSVGElement>) {
    const px = e.clientX - e.currentTarget.getBoundingClientRect().left;
    setAt(Math.max(0, Math.min(days.length - 1, Math.round(((px - PAD.left) / plotW) * (days.length - 1)))));
  }

  const summary = days.length
    ? `Video edits and AI requests per day, ${dayLabel(days[0].date)} to ${dayLabel(days[days.length - 1].date)}. Use the left and right arrow keys to read each day.`
    : "No days to show.";

  return (
    <div className="viz space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <ul className="flex gap-4 text-xs text-white/70" aria-label="Legend">
          {SERIES.map((s) => (
            <li key={s.key} className="flex items-center gap-1.5">
              <span aria-hidden className="h-0.5 w-4 rounded" style={{ background: s.color }} />
              {s.label}
            </li>
          ))}
        </ul>
        <button type="button" onClick={() => setTable((v) => !v)} aria-pressed={table} className="text-xs text-violet-300 underline">
          {table ? "Show as graph" : "Show as table"}
        </button>
      </div>

      <div ref={box} className={`relative ${table ? "hidden" : ""}`}>
        {width > 0 && (
          <svg
            width={width}
            height={HEIGHT}
            role="img"
            aria-label={summary}
            tabIndex={0}
            className="block touch-pan-y rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400"
            onPointerMove={point}
            onPointerDown={point}
            onPointerLeave={() => setAt(null)}
            onBlur={() => setAt(null)}
            onKeyDown={(e) => {
              if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
              e.preventDefault();
              const step = e.key === "ArrowLeft" ? -1 : 1;
              setAt((v) => Math.max(0, Math.min(days.length - 1, v === null ? days.length - 1 : v + step)));
            }}
          >
            {ticks.map((t) => (
              <g key={t}>
                <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} stroke="currentColor" className={t === 0 ? "text-white/25" : "text-white/10"} />
                <text x={PAD.left - 8} y={y(t)} dy="0.32em" textAnchor="end" fill="currentColor" className="text-[11px] tabular-nums text-white/50">
                  {t}
                </text>
              </g>
            ))}
            {labelledDays(days.length, Math.floor(plotW / 70) + 1).map((i) => (
              <text
                key={i}
                x={x(i)}
                y={HEIGHT - 6}
                textAnchor={i === 0 ? "start" : i === days.length - 1 ? "end" : "middle"}
                fill="currentColor"
                className="text-[11px] text-white/50"
              >
                {dayLabel(days[i].date)}
              </text>
            ))}
            {shown !== null && <line x1={x(shown)} x2={x(shown)} y1={PAD.top} y2={PAD.top + plotH} stroke="currentColor" className="text-white/40" />}
            {SERIES.map((s) => (
              <g key={s.key}>
                <polyline
                  points={days.map((d, i) => `${x(i)},${y(s.value(d))}`).join(" ")}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
                {days.length > 0 && (
                  <circle
                    cx={x(shown ?? days.length - 1)}
                    cy={y(s.value(days[shown ?? days.length - 1]))}
                    r={4}
                    fill={s.color}
                    stroke="var(--background)"
                    strokeWidth={2}
                  />
                )}
              </g>
            ))}
          </svg>
        )}
        {shown !== null && (
          <div
            role="status"
            className="pointer-events-none absolute top-1 w-40 rounded-lg border border-white/15 bg-panel px-3 py-2 text-xs shadow-xl"
            style={{ left: x(shown) > width / 2 ? Math.max(0, x(shown) - 170) : Math.min(x(shown) + 10, width - 160) }}
          >
            <p className="text-white/55">{dayLabel(days[shown].date)}</p>
            {SERIES.map((s) => (
              <p key={s.key} className="mt-1 flex items-center gap-1.5">
                <span aria-hidden className="h-0.5 w-3 rounded" style={{ background: s.color }} />
                <span className="font-semibold tabular-nums">{s.value(days[shown])}</span>
                <span className="text-white/60">{s.noun}</span>
              </p>
            ))}
          </div>
        )}
      </div>

      {table && (
        <div className="max-h-64 overflow-y-auto rounded-lg border border-white/10">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-panel text-left text-white/55">
              <tr>
                <th className="px-3 py-2 font-medium">Day</th>
                {SERIES.map((s) => (
                  <th key={s.key} className="px-3 py-2 text-right font-medium">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {[...days].reverse().map((d) => (
                <tr key={d.date} className="border-t border-white/10">
                  <td className="px-3 py-1.5">{dayLabel(d.date)}</td>
                  {SERIES.map((s) => (
                    <td key={s.key} className="px-3 py-1.5 text-right">
                      {s.value(d)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
