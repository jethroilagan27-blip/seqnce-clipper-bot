"use client";

import { formatSeconds, moveItem, newCell, thumbUrl, type Grid, type Project, type Scene, type Visual } from "@/lib/studio";
import { NumberInput, Row, buttonCls, inputCls } from "./ui";

type Props = {
  project: Project;
  scene: Scene;
  grid: Grid;
  disabled: boolean;
  onChange: (p: Partial<Scene>) => void;
};

/** Several clips side by side, all starting together (for example six members in a 3 x 2 grid). */
export default function GridEditor({ project, scene, grid, disabled, onChange }: Props) {
  const assets = new Map(project.assets.map((a) => [a.id, a]));
  const choices = project.assets.filter((a) => a.kind === "video" || a.kind === "image");
  const capacity = grid.cols * grid.rows;
  const set = (p: Partial<Grid>) => onChange({ grid: { ...grid, ...p } });
  const patchCell = (id: string, p: Partial<Visual>) => set({ cells: grid.cells.map((c) => (c.id === id ? { ...c, ...p } : c)) });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Row label="Across">
          <NumberInput label="Columns" value={grid.cols} min={1} max={6} disabled={disabled} className="w-14" onChange={(n) => set({ cols: Math.round(n ?? 1) })} />
        </Row>
        <Row label="Down">
          <NumberInput label="Rows" value={grid.rows} min={1} max={6} disabled={disabled} className="w-14" onChange={(n) => set({ rows: Math.round(n ?? 1) })} />
        </Row>
        <Row label="Gap">
          <NumberInput label="Gap between the cells (pixels on a 1920-wide frame)" value={grid.gap} min={0} max={60} disabled={disabled} className="w-14" onChange={(n) => set({ gap: Math.round(n ?? 0) })} />
          <span>px</span>
        </Row>
        <Row label="Appear after">
          <NumberInput label="Seconds of dark before the cells appear together" value={grid.delay} min={0} max={120} disabled={disabled} className="w-16" onChange={(n) => set({ delay: n ?? 0 })} />
          <span>s (a voice-over can already be playing)</span>
        </Row>
        <span className="text-xs text-white/40">
          {grid.cells.length} of {capacity} cells filled · left to right, top to bottom
        </span>
      </div>

      <ul className="space-y-2">
        {grid.cells.map((c, i) => {
          const a = assets.get(c.asset_id);
          return (
            <li key={c.id} className={`rounded-lg border p-2 ${i >= capacity ? "border-amber-400/40 bg-amber-500/10" : "border-white/10 bg-white/[0.02]"}`}>
              <div className="flex items-start gap-2">
                <span className="w-5 pt-1 text-xs tabular-nums text-white/40">{i + 1}</span>
                {a ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={thumbUrl(project.id, a.id)} alt="" className="h-10 w-16 shrink-0 rounded object-cover" />
                ) : null}
                <div className="min-w-0 flex-1 space-y-1">
                  <p className="truncate text-sm" title={a?.name ?? ""}>
                    {a ? `${a.kind === "video" ? "Clip" : "Picture"}: ${a.name}` : "This file was deleted."}
                    {a?.kind === "video" && a.duration ? <span className="text-white/40"> ({formatSeconds(a.duration)})</span> : null}
                    {i >= capacity && <span className="text-amber-200"> · not shown: the grid is full</span>}
                  </p>
                  {a?.kind === "video" && (
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-white/60">
                      <span className="flex items-center gap-1">
                        start at <NumberInput label="Start at (seconds into the clip)" value={c.start} max={36000} disabled={disabled} className="w-16" onChange={(n) => patchCell(c.id, { start: n ?? 0 })} /> s
                      </span>
                      <span className="flex items-center gap-1">
                        use <NumberInput label="Seconds of the clip to use" value={c.length} nullable min={0.1} max={3600} placeholder="all" disabled={disabled} className="w-16" onChange={(n) => patchCell(c.id, { length: n })} /> s
                      </span>
                      {a.has_audio && (
                        <label className="flex items-center gap-1.5">
                          <input type="checkbox" checked={c.volume > 0} disabled={disabled} className="accent-violet-500" onChange={(e) => patchCell(c.id, { volume: e.target.checked ? 1 : 0 })} /> play its sound
                        </label>
                      )}
                    </div>
                  )}
                </div>
                <div className="flex shrink-0 flex-col gap-1">
                  <button className={`${buttonCls} px-2 py-0.5 text-xs`} disabled={disabled || i === 0} onClick={() => set({ cells: moveItem(grid.cells, i, i - 1) })} aria-label="Move earlier">
                    ↑
                  </button>
                  <button className={`${buttonCls} px-2 py-0.5 text-xs`} disabled={disabled || i === grid.cells.length - 1} onClick={() => set({ cells: moveItem(grid.cells, i, i + 1) })} aria-label="Move later">
                    ↓
                  </button>
                  <button className="rounded-lg border border-red-400/30 px-2 py-0.5 text-xs text-red-300 hover:bg-red-500/10 disabled:opacity-40" disabled={disabled} onClick={() => set({ cells: grid.cells.filter((x) => x.id !== c.id) })} aria-label="Remove from the grid">
                    ✕
                  </button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      <select
        className={`${inputCls} w-full max-w-xs`}
        value=""
        disabled={disabled || choices.length === 0 || grid.cells.length >= 36}
        aria-label="Add a clip to the grid"
        onChange={(e) => {
          const a = assets.get(e.target.value);
          if (a) set({ cells: [...grid.cells, newCell(a)] });
        }}
      >
        <option value="">{choices.length === 0 ? "Upload a clip first" : "+ Add a clip to the grid…"}</option>
        {choices.map((a) => (
          <option key={a.id} value={a.id}>
            {a.kind === "video" ? "Clip" : "Picture"}: {a.name}
          </option>
        ))}
      </select>
      {scene.visuals.length > 0 && <p className="text-xs text-amber-200">This scene also has clips in order; while it is a grid those are not used.</p>}
    </div>
  );
}
