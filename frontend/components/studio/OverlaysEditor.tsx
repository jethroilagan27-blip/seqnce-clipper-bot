"use client";

import { useState } from "react";
import { TEXT_COLORS } from "@/lib/overlays";
import { SHAPE_RATIO, newOverlay, newShape, thumbUrl, type DrawnShape, type Overlay, type Project, type Scene, type ShapeKind } from "@/lib/studio";
import ItemLayer, { type Item } from "./ItemLayer";
import { ConfirmButton, NumberInput, Row, buttonCls, inputCls } from "./ui";

type Props = {
  project: Project;
  scene: Scene;
  disabled: boolean;
  onChange: (p: Partial<Scene>) => void;
};

const KIND_LABEL: Record<ShapeKind, string> = { rect: "Box / highlighter", ellipse: "Circle", pin: "Map pin" };

/** Pictures and clips laid over the scene (posters, flags, maps), and drawn highlights (boxes, circles, pins). */
export default function OverlaysEditor({ project, scene, disabled, onChange }: Props) {
  const [selected, setSelected] = useState<string | null>(null);
  const assets = new Map(project.assets.map((a) => [a.id, a]));
  const pictures = project.assets.filter((a) => a.kind === "image" || a.kind === "video");
  const ratio = SHAPE_RATIO[project.doc.shape];
  const base = scene.visuals.map((v) => assets.get(v.asset_id)).find((a) => a && a.kind !== "audio");

  const patchOverlay = (id: string, p: Partial<Overlay>) => onChange({ overlays: scene.overlays.map((o) => (o.id === id ? { ...o, ...p } : o)) });
  const patchShape = (id: string, p: Partial<DrawnShape>) => onChange({ shapes: scene.shapes.map((s) => (s.id === id ? { ...s, ...p } : s)) });

  const items: Item[] = [
    ...scene.overlays.map((o): Item => {
      const a = assets.get(o.asset_id);
      return { id: o.id, kind: "picture", x: o.x, y: o.y, w: o.width, src: a ? thumbUrl(project.id, a.id) : undefined, label: `Picture: ${a?.name ?? "deleted file"}` };
    }),
    ...scene.shapes.map((s): Item => ({ id: s.id, kind: s.kind, x: s.x, y: s.y, w: s.w, h: s.h, color: s.color, label: KIND_LABEL[s.kind] })),
  ];

  const timing = (t: { start: number; end: number | null }, set: (p: { start?: number; end?: number | null }) => void) => (
    <Row label="Shows">
      from <NumberInput label="Show from (seconds into the scene)" value={t.start} max={600} disabled={disabled} className="w-16" onChange={(n) => set({ start: n ?? 0 })} />
      to <NumberInput label="Show until (seconds into the scene; empty = to the end)" value={t.end} nullable min={0.1} max={600} placeholder="end" disabled={disabled} className="w-16" onChange={(n) => set({ end: n })} /> s
    </Row>
  );

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="space-y-2">
        <div className="on-dark relative w-full overflow-hidden rounded-lg" style={{ aspectRatio: ratio, containerType: "inline-size", background: scene.background }}>
          {base && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={thumbUrl(project.id, base.id)} alt="" className="absolute inset-0 h-full w-full object-cover opacity-70" />
          )}
          <ItemLayer
            items={items}
            selectedId={selected}
            onSelect={setSelected}
            onMove={(id, x, y) => {
              if (scene.overlays.some((o) => o.id === id)) patchOverlay(id, { x, y });
              else patchShape(id, { x, y });
            }}
          />
        </div>
        <p className="text-xs text-white/40">Drag a picture or shape to place it. A map pin points at the bottom of its dashed circle.</p>
        <div className="flex flex-wrap gap-2">
          <select
            className={`${inputCls} max-w-[16rem]`}
            value=""
            disabled={disabled || pictures.length === 0 || scene.overlays.length >= 40}
            aria-label="Add a picture or clip over the scene"
            onChange={(e) => {
              const a = assets.get(e.target.value);
              if (!a) return;
              const o = newOverlay(a);
              onChange({ overlays: [...scene.overlays, o] });
              setSelected(o.id);
            }}
          >
            <option value="">{pictures.length === 0 ? "Upload a picture first" : "+ Picture over the scene…"}</option>
            {pictures.map((a) => (
              <option key={a.id} value={a.id}>
                {a.kind === "video" ? "Clip" : "Picture"}: {a.name}
              </option>
            ))}
          </select>
          {(["rect", "ellipse", "pin"] as ShapeKind[]).map((k) => (
            <button
              key={k}
              className={buttonCls}
              disabled={disabled || scene.shapes.length >= 40}
              onClick={() => {
                const s = newShape(k);
                onChange({ shapes: [...scene.shapes, s] });
                setSelected(s.id);
              }}
            >
              + {KIND_LABEL[k]}
            </button>
          ))}
        </div>
      </div>

      <ul className="space-y-2">
        {scene.overlays.length + scene.shapes.length === 0 && <li className="rounded-lg border border-dashed border-white/15 px-4 py-6 text-center text-sm text-white/40">Nothing over this scene yet.</li>}
        {scene.overlays.map((o) => {
          const a = assets.get(o.asset_id);
          const open = selected === o.id;
          return (
            <li key={o.id} className={`rounded-xl border ${open ? "border-violet-400/70" : "border-white/10"} bg-white/[0.02]`}>
              <div className="flex items-center gap-2 p-2">
                <button className="min-w-0 flex-1 truncate text-left text-sm" onClick={() => setSelected(open ? null : o.id)} aria-expanded={open}>
                  Picture: {a?.name ?? "(deleted file)"}
                </button>
                <ConfirmButton label="Delete" disabled={disabled} onConfirm={() => onChange({ overlays: scene.overlays.filter((x) => x.id !== o.id) })} />
              </div>
              {open && (
                <div className="space-y-2 border-t border-white/10 p-3">
                  <Row label="Size">
                    <input type="range" min={5} max={150} value={Math.round(o.width * 100)} disabled={disabled} aria-label="Picture size (percent of the frame width)" className="w-40 accent-violet-500" onChange={(e) => patchOverlay(o.id, { width: Number(e.target.value) / 100 })} />
                    <span className="w-10 tabular-nums">{Math.round(o.width * 100)}%</span>
                  </Row>
                  {timing(o, (p) => patchOverlay(o.id, p))}
                  <Row label="Movement">
                    <select className={inputCls} value={o.anim} disabled={disabled} aria-label="Picture movement" onChange={(e) => patchOverlay(o.id, { anim: e.target.value as Overlay["anim"] })}>
                      <option value="none">None</option>
                      <option value="pop">Pops in</option>
                      <option value="zoom_in">Slowly zooms in</option>
                    </select>
                    <label className="flex items-center gap-1.5">
                      <input type="checkbox" checked={o.fade} disabled={disabled} className="accent-violet-500" onChange={(e) => patchOverlay(o.id, { fade: e.target.checked })} /> Fade in/out
                    </label>
                  </Row>
                </div>
              )}
            </li>
          );
        })}
        {scene.shapes.map((s) => {
          const open = selected === s.id;
          return (
            <li key={s.id} className={`rounded-xl border ${open ? "border-violet-400/70" : "border-white/10"} bg-white/[0.02]`}>
              <div className="flex items-center gap-2 p-2">
                <span className="h-3 w-3 shrink-0 rounded-full ring-1 ring-white/30" style={{ background: s.color }} />
                <button className="min-w-0 flex-1 truncate text-left text-sm" onClick={() => setSelected(open ? null : s.id)} aria-expanded={open}>
                  {KIND_LABEL[s.kind]}
                </button>
                <ConfirmButton label="Delete" disabled={disabled} onConfirm={() => onChange({ shapes: scene.shapes.filter((x) => x.id !== s.id) })} />
              </div>
              {open && (
                <div className="space-y-2 border-t border-white/10 p-3">
                  <div className="flex flex-wrap items-center gap-2" role="radiogroup" aria-label="Colour">
                    {["#ffd400", "#ff3b30", ...TEXT_COLORS.slice(0, 6)].map((c) => (
                      <button key={c} role="radio" aria-checked={s.color === c} aria-label={c} disabled={disabled} onClick={() => patchShape(s.id, { color: c })} className={`h-6 w-6 rounded-full border-2 ${s.color === c ? "border-white" : "border-white/20"}`} style={{ background: c }} />
                    ))}
                  </div>
                  <Row label={s.kind === "pin" ? "Size" : "Width"}>
                    <input type="range" min={2} max={100} value={Math.round(s.w * 100)} disabled={disabled} aria-label="Width (percent of the frame width)" className="w-40 accent-violet-500" onChange={(e) => patchShape(s.id, { w: Number(e.target.value) / 100 })} />
                    <span className="w-10 tabular-nums">{Math.round(s.w * 100)}%</span>
                  </Row>
                  {s.kind !== "pin" && (
                    <>
                      <Row label="Height">
                        <input type="range" min={2} max={100} value={Math.round(s.h * 100)} disabled={disabled} aria-label="Height (percent of the frame height)" className="w-40 accent-violet-500" onChange={(e) => patchShape(s.id, { h: Number(e.target.value) / 100 })} />
                        <span className="w-10 tabular-nums">{Math.round(s.h * 100)}%</span>
                      </Row>
                      <Row label="Filled">
                        <input type="range" min={0} max={100} value={Math.round(s.fill * 100)} disabled={disabled} aria-label="How filled in (percent)" className="w-40 accent-violet-500" onChange={(e) => patchShape(s.id, { fill: Number(e.target.value) / 100 })} />
                        <span className="w-10 tabular-nums">{Math.round(s.fill * 100)}%</span>
                      </Row>
                      <Row label="Outline">
                        <input type="range" min={0} max={20} value={Math.round(s.thickness * 10)} disabled={disabled} aria-label="Outline thickness" className="w-40 accent-violet-500" onChange={(e) => patchShape(s.id, { thickness: Number(e.target.value) / 10 })} />
                        <span className="w-10 tabular-nums">{s.thickness.toFixed(1)}</span>
                      </Row>
                    </>
                  )}
                  {timing(s, (p) => patchShape(s.id, p))}
                  <Row label="Movement">
                    <select className={inputCls} value={s.anim} disabled={disabled} aria-label="Shape movement" onChange={(e) => patchShape(s.id, { anim: e.target.value as DrawnShape["anim"] })}>
                      <option value="none">None</option>
                      <option value="drop">Drops in from above</option>
                    </select>
                    <label className="flex items-center gap-1.5">
                      <input type="checkbox" checked={s.fade} disabled={disabled} className="accent-violet-500" onChange={(e) => patchShape(s.id, { fade: e.target.checked })} /> Fade in/out
                    </label>
                  </Row>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
