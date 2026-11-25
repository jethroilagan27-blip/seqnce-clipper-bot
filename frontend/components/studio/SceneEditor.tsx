"use client";

import { useState } from "react";
import OverlayLayer from "@/components/overlay/OverlayLayer";
import TextEditor from "@/components/overlay/TextEditor";
import {
  SHAPE_RATIO,
  formatSeconds,
  moveItem,
  newVisual,
  thumbUrl,
  type Asset,
  type Limits,
  type Project,
  type Scene,
  type Visual,
} from "@/lib/studio";
import CreditsEditor from "./CreditsEditor";
import GridEditor from "./GridEditor";
import OverlaysEditor from "./OverlaysEditor";
import { NumberInput, Row, Section, buttonCls, inputCls } from "./ui";

const LOCKED = "Not included in your plan.";

type Props = {
  project: Project;
  scene: Scene;
  index: number;
  fonts: string[];
  disabled: boolean;
  onChange: (scene: Scene) => void;
  /** The finished preview video for this scene, when there is one. */
  previewSrc: string | null;
  previewing: boolean;
  onPreview: () => void;
};

const limitsNote = (limits: Limits) => (limits.crossfade ? null : "Cross-fade isn't included in your plan. Fading through black is.");

export default function SceneEditor({ project, scene, index, fonts, disabled, onChange, previewSrc, previewing, onPreview }: Props) {
  const { limits } = project;
  const assets = new Map(project.assets.map((a) => [a.id, a]));
  const info = project.scenes.find((s) => s.id === scene.id);
  const duration = info?.duration ?? scene.min_duration ?? 5;
  const patch = (p: Partial<Scene>) => onChange({ ...scene, ...p });
  const audio = project.assets.filter((a) => a.kind === "audio");
  const visualAssets = project.assets.filter((a) => a.kind === "video" || a.kind === "image");
  // the fonts shipped with Studio, then the ones this project uploaded
  const allFonts = [...fonts, ...project.assets.filter((a) => a.kind === "font" && a.family && !fonts.includes(a.family)).map((a) => a.family as string)];

  const patchVisual = (id: string, p: Partial<Visual>) => patch({ visuals: scene.visuals.map((v) => (v.id === id ? { ...v, ...p } : v)) });

  return (
    <div className="space-y-4 border-t border-white/10 p-4">
      {info?.problem && (
        <p role="alert" className="rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
          {info.problem}
        </p>
      )}

      <Section title="Scene">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Row label="Name">
            <input className={`${inputCls} w-56`} value={scene.name} maxLength={80} disabled={disabled} onChange={(e) => patch({ name: e.target.value })} aria-label="Scene name" />
          </Row>
          <Row label="At least">
            <NumberInput label="Minimum length (seconds)" value={scene.min_duration} nullable min={0.1} max={600} disabled={disabled} placeholder="auto" onChange={(n) => patch({ min_duration: n })} />
            <span>s long (a text card needs this)</span>
          </Row>
          <Row label="Background">
            <input type="color" value={scene.background} disabled={disabled} onChange={(e) => patch({ background: e.target.value })} aria-label="Background colour" className="h-6 w-8 cursor-pointer bg-transparent" />
            <span className="text-white/40">(when there are no clips)</span>
          </Row>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Row label="Fade in from black">
            <NumberInput label="Fade in (seconds)" value={scene.fade_in} max={10} disabled={disabled} onChange={(n) => patch({ fade_in: n ?? 0 })} />
            <span>s</span>
          </Row>
          <Row label="Fade out to black">
            <NumberInput label="Fade out (seconds)" value={scene.fade_out} max={10} disabled={disabled} onChange={(n) => patch({ fade_out: n ?? 0 })} />
            <span>s</span>
          </Row>
          {index > 0 && (
            <Row label="From the scene before">
              <select
                className={inputCls}
                value={scene.transition_in}
                disabled={disabled}
                aria-label="Transition from the previous scene"
                onChange={(e) => patch({ transition_in: e.target.value as Scene["transition_in"] })}
              >
                <option value="cut">Straight cut</option>
                <option value="crossfade" disabled={!limits.crossfade}>
                  Cross-fade{limits.crossfade ? "" : " (not in your plan)"}
                </option>
              </select>
              {scene.transition_in === "crossfade" && (
                <>
                  <NumberInput label="Cross-fade length (seconds)" value={scene.crossfade_s} min={0.1} max={5} disabled={disabled} onChange={(n) => patch({ crossfade_s: n ?? 0.8 })} />
                  <span>s</span>
                </>
              )}
              {limitsNote(limits) && <span className="text-white/30">{limitsNote(limits)}</span>}
            </Row>
          )}
        </div>
      </Section>

      <Section title="Layout">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm" role="radiogroup" aria-label="How the clips are shown">
          <label className="flex items-center gap-1.5">
            <input type="radio" name={`layout-${scene.id}`} checked={!scene.grid} disabled={disabled} className="accent-violet-500" onChange={() => patch({ grid: null })} />
            One after another
          </label>
          <label className={`flex items-center gap-1.5 ${limits.grid ? "" : "opacity-50"}`}>
            <input
              type="radio"
              name={`layout-${scene.id}`}
              checked={!!scene.grid}
              disabled={disabled || !limits.grid}
              className="accent-violet-500"
              onChange={() => patch({ grid: scene.grid ?? { cols: 3, rows: 2, gap: 8, delay: 0, cells: [] } })}
            />
            Side by side, all at once (grid)
            {!limits.grid && <span className="text-xs text-white/40">{LOCKED}</span>}
          </label>
        </div>
      </Section>

      {scene.grid ? (
        <Section title="Grid" hint="Every cell starts together. The scene lasts as long as the longest clip (or the voice-over).">
          <GridEditor project={project} scene={scene} grid={scene.grid} disabled={disabled} onChange={patch} />
        </Section>
      ) : (
      <Section title="Clips and pictures" hint="Shown one after another. Mute a clip's own sound when a voice-over plays over it.">
        {scene.visuals.length === 0 && <p className="text-xs text-white/40">None: this scene is the background colour (and any text).</p>}
        <ul className="space-y-2">
          {scene.visuals.map((v, i) => {
            const a = assets.get(v.asset_id);
            return (
              <VisualRow
                key={v.id}
                visual={v}
                asset={a}
                projectId={project.id}
                disabled={disabled}
                canUp={i > 0}
                canDown={i < scene.visuals.length - 1}
                onChange={(p) => patchVisual(v.id, p)}
                onMove={(d) => patch({ visuals: moveItem(scene.visuals, i, i + d) })}
                onRemove={() => patch({ visuals: scene.visuals.filter((x) => x.id !== v.id) })}
              />
            );
          })}
        </ul>
        <select
          className={`${inputCls} w-full max-w-xs`}
          value=""
          disabled={disabled || visualAssets.length === 0 || scene.visuals.length >= limits.max_visuals_per_scene}
          aria-label="Add a clip or picture"
          onChange={(e) => {
            const a = assets.get(e.target.value);
            if (a) patch({ visuals: [...scene.visuals, newVisual(a)] });
          }}
        >
          <option value="">{visualAssets.length === 0 ? "Upload a clip or picture first" : "+ Add a clip or picture…"}</option>
          {visualAssets.map((a) => (
            <option key={a.id} value={a.id}>
              {a.kind === "video" ? "Clip" : "Picture"}: {a.name}
            </option>
          ))}
        </select>
        <label className={`flex items-center gap-1.5 text-xs text-white/60 ${limits.auto_montage ? "" : "opacity-50"}`}>
          <input type="checkbox" checked={scene.fit_to_voiceover} disabled={disabled || !limits.auto_montage} className="accent-violet-500" onChange={(e) => patch({ fit_to_voiceover: e.target.checked })} />
          Give every clip and picture an equal share of the voice-over&apos;s length
          {!limits.auto_montage && <span className="text-white/40">{LOCKED}</span>}
        </label>
      </Section>
      )}

      <Section title="Voice-over" hint="Plays from the start of the scene. If it is longer than the clips, the last clip is held.">
        <select
          className={`${inputCls} w-full max-w-xs`}
          value={scene.voiceover?.asset_id ?? ""}
          disabled={disabled}
          aria-label="Voice-over file"
          onChange={(e) => patch({ voiceover: e.target.value ? { asset_id: e.target.value, volume: scene.voiceover?.volume ?? 1, offset: scene.voiceover?.offset ?? 0 } : null })}
        >
          <option value="">{audio.length === 0 ? "No audio uploaded yet" : "None"}</option>
          {audio.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} ({formatSeconds(a.duration ?? 0)})
            </option>
          ))}
        </select>
        {scene.voiceover && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <Row label="Volume">
              <input type="range" min={0} max={200} value={Math.round(scene.voiceover.volume * 100)} disabled={disabled} aria-label="Voice-over volume" className="w-32 accent-violet-500"
                onChange={(e) => patch({ voiceover: { ...scene.voiceover!, volume: Number(e.target.value) / 100 } })} />
              <span className="w-10 tabular-nums">{Math.round(scene.voiceover.volume * 100)}%</span>
            </Row>
            <Row label="Starts after">
              <NumberInput label="Voice-over starts after (seconds)" value={scene.voiceover.offset} max={600} disabled={disabled} onChange={(n) => patch({ voiceover: { ...scene.voiceover!, offset: n ?? 0 } })} />
              <span>s</span>
            </Row>
          </div>
        )}
      </Section>

      <Section title="Music in this scene" hint="Optional. For music under the whole video use the project settings.">
        <select
          className={`${inputCls} w-full max-w-xs`}
          value={scene.music?.asset_id ?? ""}
          disabled={disabled}
          aria-label="Music file"
          onChange={(e) => patch({ music: e.target.value ? { asset_id: e.target.value, start: scene.music?.start ?? 0, volume: scene.music?.volume ?? 0.6, fade_in: scene.music?.fade_in ?? 0, fade_out: scene.music?.fade_out ?? 0, duck: scene.music?.duck ?? true } : null })}
        >
          <option value="">{audio.length === 0 ? "No audio uploaded yet" : "None"}</option>
          {audio.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} ({formatSeconds(a.duration ?? 0)})
            </option>
          ))}
        </select>
        {scene.music && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <Row label="Play from">
              <NumberInput label="Start music from (seconds into the track)" value={scene.music.start} max={36000} disabled={disabled} onChange={(n) => patch({ music: { ...scene.music!, start: n ?? 0 } })} />
              <span>s into the track</span>
            </Row>
            <Row label="Volume">
              <input type="range" min={0} max={200} value={Math.round(scene.music.volume * 100)} disabled={disabled} aria-label="Music volume" className="w-32 accent-violet-500"
                onChange={(e) => patch({ music: { ...scene.music!, volume: Number(e.target.value) / 100 } })} />
              <span className="w-10 tabular-nums">{Math.round(scene.music.volume * 100)}%</span>
            </Row>
            <Row label="Fade in">
              <NumberInput label="Music fade in (seconds)" value={scene.music.fade_in} max={30} disabled={disabled} onChange={(n) => patch({ music: { ...scene.music!, fade_in: n ?? 0 } })} />
              <span>s</span>
            </Row>
            <Row label="Fade out">
              <NumberInput label="Music fade out (seconds)" value={scene.music.fade_out} max={30} disabled={disabled} onChange={(n) => patch({ music: { ...scene.music!, fade_out: n ?? 0 } })} />
              <span>s</span>
            </Row>
            <label className={`flex items-center gap-1.5 text-xs text-white/60 ${limits.ducking ? "" : "opacity-50"}`}>
              <input type="checkbox" checked={scene.music.duck && limits.ducking} disabled={disabled || !limits.ducking} className="accent-violet-500" onChange={(e) => patch({ music: { ...scene.music!, duck: e.target.checked } })} />
              Lower the music while the voice-over speaks
              {!limits.ducking && <span className="text-white/40">{LOCKED}</span>}
            </label>
          </div>
        )}
      </Section>

      <Section title="Text" hint="Drag a text on the picture to place it. Times are counted from the start of this scene.">
        <TextOnFrame project={project} scene={scene} duration={duration} fonts={allFonts} limits={limits} disabled={disabled} onChange={(texts) => patch({ texts })} />
      </Section>

      <Section title="Pictures and highlights" hint="Posters, flags, maps or small clips over the scene; boxes, circles and map pins to point things out.">
        {limits.overlays ? <OverlaysEditor project={project} scene={scene} disabled={disabled} onChange={patch} /> : <p className="text-xs text-white/40">{LOCKED}</p>}
      </Section>

      <Section title="Opening effect" hint="The scene starts as a narrow band, then opens to the full frame.">
        <Row label="Starts with">
          <select className={inputCls} value={scene.open_effect} disabled={disabled || !limits.overlays} aria-label="Opening effect" onChange={(e) => patch({ open_effect: e.target.value as Scene["open_effect"] })}>
            <option value="none">Nothing special</option>
            <option value="letterbox">Narrow frame that opens</option>
          </select>
          {scene.open_effect === "letterbox" && (
            <>
              <NumberInput label="Seconds to open" value={scene.open_s} min={0.3} max={5} disabled={disabled} className="w-14" onChange={(n) => patch({ open_s: n ?? 1.2 })} />
              <span>s</span>
            </>
          )}
          {!limits.overlays && <span className="text-white/40">{LOCKED}</span>}
        </Row>
      </Section>

      <Section title="Rolling credits" hint="Lines of text that scroll up the screen.">
        {!limits.credits ? (
          <p className="text-xs text-white/40">{LOCKED}</p>
        ) : scene.credits ? (
          <>
            <CreditsEditor credits={scene.credits} fonts={allFonts} limits={limits} disabled={disabled} onChange={patch} />
            <button className={`${buttonCls} text-xs`} disabled={disabled} onClick={() => patch({ credits: null })}>
              Remove the credits from this scene
            </button>
          </>
        ) : (
          <button className={buttonCls} disabled={disabled} onClick={() => patch({ credits: { lines: ["# Credits", "Name one", "Name two"], size: 3.4, color: "#ffffff", font: "", seconds: null } })}>
            + Add rolling credits to this scene
          </button>
        )}
      </Section>

      <Section title="Preview this scene" hint="A quick, small version of just this scene, so you can check it before making the whole video.">
        <button className={buttonCls} disabled={disabled || previewing} onClick={onPreview}>
          {previewing ? "Making the preview…" : "Preview this scene"}
        </button>
        {previewSrc && <video key={previewSrc} src={previewSrc} controls className="mt-2 w-full max-w-lg rounded-lg bg-black" />}
      </Section>
    </div>
  );
}

// ---- one clip or picture in a scene ---------------------------------------------------------

function VisualRow({ visual: v, asset, projectId, disabled, canUp, canDown, onChange, onMove, onRemove }: {
  visual: Visual;
  asset: Asset | undefined;
  projectId: string;
  disabled: boolean;
  canUp: boolean;
  canDown: boolean;
  onChange: (p: Partial<Visual>) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
}) {
  if (!asset)
    return (
      <li className="flex items-center justify-between gap-2 rounded-lg border border-amber-400/40 bg-amber-500/10 p-2 text-xs text-amber-100">
        This file was deleted.
        <button className="underline" onClick={onRemove}>
          Remove
        </button>
      </li>
    );
  const isVideo = asset.kind === "video";
  return (
    <li className="rounded-lg border border-white/10 bg-white/[0.02] p-2">
      <div className="flex items-start gap-2">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={thumbUrl(projectId, asset.id)} alt="" className="h-12 w-20 shrink-0 rounded object-cover" />
        <div className="min-w-0 flex-1 space-y-1.5">
          <p className="truncate text-sm" title={asset.name ?? ""}>
            {isVideo ? "Clip" : "Picture"}: {asset.name}
            {isVideo && asset.duration ? <span className="text-white/40"> ({formatSeconds(asset.duration)})</span> : null}
          </p>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-white/60">
            {isVideo && (
              <>
                <span className="flex items-center gap-1">
                  start at <NumberInput label="Start at (seconds into the clip)" value={v.start} max={36000} disabled={disabled} className="w-16" onChange={(n) => onChange({ start: n ?? 0 })} /> s
                </span>
                <span className="flex items-center gap-1">
                  use <NumberInput label="Seconds of the clip to use" value={v.length} nullable min={0.1} max={3600} placeholder="all" disabled={disabled} className="w-16" onChange={(n) => onChange({ length: n })} /> s
                </span>
              </>
            )}
            {!isVideo && (
              <span className="flex items-center gap-1">
                show for <NumberInput label="Seconds to show the picture" value={v.length} nullable min={0.1} max={3600} placeholder="3" disabled={disabled} className="w-16" onChange={(n) => onChange({ length: n })} /> s
              </span>
            )}
            <select className={inputCls} value={v.fit} disabled={disabled} aria-label="How it fills the frame" onChange={(e) => onChange({ fit: e.target.value as Visual["fit"] })}>
              <option value="blur">Fill with blurred copy</option>
              <option value="crop">Cut to fill</option>
              <option value="fit">Black bars</option>
            </select>
            <select className={inputCls} value={v.zoom} disabled={disabled} aria-label="Slow zoom" onChange={(e) => onChange({ zoom: e.target.value as Visual["zoom"] })}>
              <option value="none">No zoom</option>
              <option value="in">Slow zoom in</option>
              <option value="out">Slow zoom out</option>
            </select>
            {isVideo && asset.has_audio && (
              <span className="flex items-center gap-1.5">
                sound
                <input type="range" min={0} max={200} value={Math.round(v.volume * 100)} disabled={disabled} aria-label="Clip volume" className="w-24 accent-violet-500" onChange={(e) => onChange({ volume: Number(e.target.value) / 100 })} />
                <span className="w-10 tabular-nums">{v.volume === 0 ? "muted" : `${Math.round(v.volume * 100)}%`}</span>
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 flex-col gap-1">
          <button className={`${buttonCls} px-2 py-0.5 text-xs`} disabled={disabled || !canUp} onClick={() => onMove(-1)} aria-label="Move earlier">
            ↑
          </button>
          <button className={`${buttonCls} px-2 py-0.5 text-xs`} disabled={disabled || !canDown} onClick={() => onMove(1)} aria-label="Move later">
            ↓
          </button>
          <button className="rounded-lg border border-red-400/30 px-2 py-0.5 text-xs text-red-300 hover:bg-red-500/10 disabled:opacity-40" disabled={disabled} onClick={onRemove} aria-label="Remove from the scene">
            ✕
          </button>
        </div>
      </div>
    </li>
  );
}

// ---- texts, placed by dragging on the first picture of the scene ------------------------------

function TextOnFrame({ project, scene, duration, fonts, limits, disabled, onChange }: {
  project: Project;
  scene: Scene;
  duration: number;
  fonts: string[];
  limits: Limits;
  disabled: boolean;
  onChange: (texts: Scene["texts"]) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [time, setTime] = useState(0);
  const first = scene.visuals.map((v) => project.assets.find((a) => a.id === v.asset_id)).find((a) => a && a.kind !== "audio");
  const ratio = SHAPE_RATIO[project.doc.shape];
  const at = Math.min(time, duration);

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="space-y-2">
        <div
          className="on-dark relative w-full overflow-hidden rounded-lg"
          style={{ aspectRatio: ratio, containerType: "inline-size", background: scene.background }}
        >
          {first && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={thumbUrl(project.id, first.id)} alt="" className="absolute inset-0 h-full w-full object-cover opacity-80" />
          )}
          <OverlayLayer
            texts={scene.texts}
            time={at}
            total={duration}
            selectedId={selected}
            onSelect={setSelected}
            onMove={(id, x, y) => onChange(scene.texts.map((t) => (t.id === id ? { ...t, x, y } : t)))}
          />
        </div>
        <label className="flex items-center gap-2 text-xs text-white/50">
          Look at
          <input type="range" min={0} max={Math.max(duration, 0.1)} step={0.1} value={at} onChange={(e) => setTime(Number(e.target.value))} aria-label="Preview time in the scene" className="flex-1 accent-violet-500" />
          <span className="w-12 tabular-nums">{formatSeconds(at)}</span>
        </label>
      </div>
      <TextEditor
        texts={scene.texts}
        selectedId={selected}
        total={duration}
        disabled={disabled}
        onChange={onChange}
        onSelect={setSelected}
        extra={(t, p) =>
          limits.text_effects ? (
            <div className="flex flex-wrap items-center gap-3 text-xs text-white/60">
              <label className="flex items-center gap-1.5">
                Font
                <select className={inputCls} value={t.font ?? ""} disabled={disabled} aria-label="Font" onChange={(e) => p({ font: e.target.value })}>
                  <option value="">Default (Arial)</option>
                  {fonts.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-1.5">
                Movement
                <select className={inputCls} value={t.anim ?? "none"} disabled={disabled} aria-label="Text movement" onChange={(e) => p({ anim: e.target.value as NonNullable<typeof t.anim> })}>
                  <option value="none">None</option>
                  <option value="zoom_in">Slowly zoom in</option>
                  <option value="zoom_out">Slowly zoom out</option>
                </select>
              </label>
            </div>
          ) : (
            <p className="text-xs text-white/30">Title fonts and the zoom movement aren&apos;t included in your plan.</p>
          )
        }
      />
    </div>
  );
}
