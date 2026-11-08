"use client";

import { MAX_TEXTS, TEXT_COLORS, newText, type TextOverlay, type TextStyle } from "@/lib/overlays";

type Props = {
  texts: TextOverlay[];
  selectedId: string | null;
  /** Length of the finished video (s), for the "show from / to" boxes. */
  total: number;
  disabled?: boolean;
  onChange: (texts: TextOverlay[]) => void;
  onSelect: (id: string | null) => void;
};

const STYLES: { key: TextStyle; label: string }[] = [
  { key: "outline", label: "Outline" },
  { key: "box", label: "Box" },
  { key: "plain", label: "Plain" },
];

const num = "w-20 rounded-md border border-white/10 bg-[#15151c] px-2 py-1 text-sm tabular-nums disabled:opacity-50";

// Add your own text, then drag it on the preview. Everything about a text (words, colour, size, style, when it shows) is here.
export default function TextEditor({ texts, selectedId, total, disabled, onChange, onSelect }: Props) {
  const patch = (id: string, p: Partial<TextOverlay>) => onChange(texts.map((t) => (t.id === id ? { ...t, ...p } : t)));

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-white/50">Drag a text on the preview to place it. Texts snap to the middle.</p>
        <button
          disabled={disabled || texts.length >= MAX_TEXTS}
          onClick={() => {
            // each new text starts a bit lower than the last one so they don't pile up
            const t = newText({ y: Math.min(0.2 + texts.length * 0.1, 0.9) });
            onChange([...texts, t]);
            onSelect(t.id);
          }}
          className="shrink-0 rounded-lg bg-violet-600 px-3 py-1.5 text-sm font-semibold hover:bg-violet-500 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-white/30"
        >
          + Add text
        </button>
      </div>

      {texts.length === 0 && <p className="rounded-lg border border-dashed border-white/15 px-4 py-6 text-center text-sm text-white/40">No text yet.</p>}

      <ul className="space-y-2">
        {texts.map((t) => {
          const open = t.id === selectedId;
          return (
            <li key={t.id} className={`rounded-xl border ${open ? "border-violet-400/70 bg-violet-500/[0.06]" : "border-white/10 bg-white/[0.02]"}`}>
              <div className="flex items-start gap-2 p-2.5">
                <button
                  onClick={() => onSelect(open ? null : t.id)}
                  aria-expanded={open}
                  className="min-w-0 flex-1 truncate text-left text-sm"
                  title="Edit this text"
                >
                  <span className="mr-2 inline-block h-3 w-3 rounded-full align-middle ring-1 ring-white/30" style={{ background: t.color }} />
                  {t.text.split("\n")[0] || "(empty)"}
                </button>
                <button
                  disabled={disabled}
                  onClick={() => {
                    onChange(texts.filter((x) => x.id !== t.id));
                    if (open) onSelect(null);
                  }}
                  aria-label="Delete this text"
                  className="rounded-md border border-red-400/30 px-2 py-0.5 text-xs text-red-300 hover:bg-red-500/10 disabled:opacity-40"
                >
                  Delete
                </button>
              </div>

              {open && (
                <div className="space-y-3 border-t border-white/10 p-3 text-sm">
                  <textarea
                    value={t.text}
                    rows={2}
                    maxLength={200}
                    disabled={disabled}
                    onChange={(e) => patch(t.id, { text: e.target.value || " " })}
                    aria-label="Text"
                    className="w-full resize-none rounded-md border border-white/10 bg-[#15151c] px-3 py-2 focus:border-violet-400 focus:outline-none disabled:opacity-50"
                  />
                  <div className="flex flex-wrap items-center gap-2" role="radiogroup" aria-label="Colour">
                    {TEXT_COLORS.map((c) => (
                      <button
                        key={c}
                        role="radio"
                        aria-checked={t.color === c}
                        aria-label={c}
                        disabled={disabled}
                        onClick={() => patch(t.id, { color: c })}
                        className={`h-6 w-6 rounded-full border-2 ${t.color === c ? "border-white" : "border-white/20"}`}
                        style={{ background: c }}
                      />
                    ))}
                    <label className="ml-1 text-xs text-white/50">
                      custom{" "}
                      <input type="color" value={t.color} disabled={disabled} onChange={(e) => patch(t.id, { color: e.target.value })} className="h-6 w-8 cursor-pointer bg-transparent align-middle" />
                    </label>
                  </div>
                  <label className="flex items-center gap-3 text-xs text-white/60">
                    Size
                    <input
                      type="range"
                      min={3}
                      max={20}
                      step={0.5}
                      value={t.size}
                      disabled={disabled}
                      onChange={(e) => patch(t.id, { size: Number(e.target.value) })}
                      aria-label="Text size"
                      className="flex-1 accent-violet-500"
                    />
                    <span className="w-8 tabular-nums">{t.size}</span>
                  </label>
                  <div className="flex flex-wrap items-center gap-3">
                    <div className="flex gap-1" role="radiogroup" aria-label="Style">
                      {STYLES.map((s) => (
                        <button
                          key={s.key}
                          role="radio"
                          aria-checked={t.style === s.key}
                          disabled={disabled}
                          onClick={() => patch(t.id, { style: s.key })}
                          className={`rounded-md px-2.5 py-1 text-xs ${t.style === s.key ? "bg-violet-600 font-semibold" : "border border-white/15 text-white/70 hover:bg-white/5"}`}
                        >
                          {s.label}
                        </button>
                      ))}
                    </div>
                    <label className="flex items-center gap-1.5 text-xs text-white/70">
                      <input type="checkbox" checked={t.bold} disabled={disabled} onChange={(e) => patch(t.id, { bold: e.target.checked })} className="accent-violet-500" /> Bold
                    </label>
                    <label className="flex items-center gap-1.5 text-xs text-white/70">
                      <input type="checkbox" checked={t.fade} disabled={disabled} onChange={(e) => patch(t.id, { fade: e.target.checked })} className="accent-violet-500" /> Fade in/out
                    </label>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-white/60">
                    <label className="flex items-center gap-1.5">
                      <input
                        type="checkbox"
                        checked={t.start === 0 && t.end === null}
                        disabled={disabled}
                        onChange={(e) => patch(t.id, e.target.checked ? { start: 0, end: null } : { start: 0, end: Math.max(1, Math.min(total, 3)) })}
                        className="accent-violet-500"
                      />
                      Show the whole video
                    </label>
                    {!(t.start === 0 && t.end === null) && (
                      <>
                        from
                        <input type="number" min={0} step={0.5} value={t.start} disabled={disabled} className={num} aria-label="Show from (seconds)"
                          onChange={(e) => patch(t.id, { start: Math.max(0, Number(e.target.value) || 0) })} />
                        to
                        <input type="number" min={0.5} step={0.5} value={t.end ?? total} disabled={disabled} className={num} aria-label="Show until (seconds)"
                          onChange={(e) => patch(t.id, { end: Math.max(t.start + 0.5, Number(e.target.value) || 0.5) })} />
                        s
                      </>
                    )}
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
