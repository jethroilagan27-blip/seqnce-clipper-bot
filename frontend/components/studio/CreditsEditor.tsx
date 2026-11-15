"use client";

import { useState } from "react";
import { TEXT_COLORS } from "@/lib/overlays";
import type { Credits, Limits, Scene } from "@/lib/studio";
import { NumberInput, Row, inputCls } from "./ui";

type Props = {
  credits: Credits;
  fonts: string[];
  limits: Limits;
  disabled: boolean;
  onChange: (p: Partial<Scene>) => void;
};

/** Rolling credits: one line per row; start a line with "# " for a heading. */
export default function CreditsEditor({ credits, fonts, limits, disabled, onChange }: Props) {
  const set = (p: Partial<Credits>) => onChange({ credits: { ...credits, ...p } });
  // the box keeps its own text while you type, so Enter and trailing spaces behave; it saves as you go
  const [text, setText] = useState(credits.lines.join("\n"));

  return (
    <div className="space-y-3">
      <textarea
        value={text}
        rows={8}
        spellCheck={false}
        disabled={disabled}
        aria-label="Credits, one line per row"
        className="w-full rounded-lg border border-white/10 bg-[#15151c] px-3 py-2 font-mono text-sm focus:border-violet-400 focus:outline-none disabled:opacity-50"
        placeholder={"# Directed by\nMichael Gracey\n\n# Cast\nHugh Jackman"}
        onChange={(e) => {
          setText(e.target.value);
          set({ lines: e.target.value.split("\n").slice(0, 300) });
        }}
      />
      <p className="text-xs text-white/40">One line per row. A line starting with “# ” is a heading. An empty row leaves a gap.</p>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Row label="Size">
          <input type="range" min={15} max={100} value={Math.round(credits.size * 10)} disabled={disabled} aria-label="Credits size" className="w-32 accent-violet-500" onChange={(e) => set({ size: Number(e.target.value) / 10 })} />
          <span className="w-10 tabular-nums">{credits.size.toFixed(1)}</span>
        </Row>
        <Row label="Colour">
          <div className="flex items-center gap-1.5" role="radiogroup" aria-label="Credits colour">
            {TEXT_COLORS.slice(0, 4).map((c) => (
              <button key={c} role="radio" aria-checked={credits.color === c} aria-label={c} disabled={disabled} onClick={() => set({ color: c })} className={`h-5 w-5 rounded-full border-2 ${credits.color === c ? "border-white" : "border-white/20"}`} style={{ background: c }} />
            ))}
          </div>
        </Row>
        <Row label="Rolls for">
          <NumberInput label="How long the credits roll (seconds; empty = a comfortable reading speed)" value={credits.seconds} nullable min={2} max={600} placeholder="auto" disabled={disabled} className="w-16" onChange={(n) => set({ seconds: n })} />
          <span>s (empty = automatic)</span>
        </Row>
        {limits.text_effects && (
          <Row label="Font">
            <select className={inputCls} value={credits.font} disabled={disabled} aria-label="Credits font" onChange={(e) => set({ font: e.target.value })}>
              <option value="">Default (Arial)</option>
              {fonts.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </Row>
        )}
      </div>
    </div>
  );
}
