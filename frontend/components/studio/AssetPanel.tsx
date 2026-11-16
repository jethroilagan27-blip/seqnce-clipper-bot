"use client";

import { useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { baseName, folderOf, fromFileList, mergePicked, naturalCompare, safeFromDataTransfer, splitByExtension, type Picked } from "@/lib/pickFiles";
import { assetFileUrl, deleteAsset, formatMegabytes, formatSeconds, thumbUrl, uploadAsset, type Asset, type AssetKind, type Project } from "@/lib/studio";
import { ConfirmButton } from "./ui";

type Props = {
  project: Project;
  accepts: string[];
  disabled: boolean;
  /** The project as the server has it after an upload or a delete. */
  onProject: (project: Project) => void;
  /** A file was deleted: the page's draft must forget it too. */
  onDeleted: (assetId: string, project: Project) => void;
};

type Upload = { key: number; name: string; fraction: number; error?: string };

const GROUPS: { kind: AssetKind; title: string; empty: string }[] = [
  { kind: "video", title: "Clips", empty: "No clips yet." },
  { kind: "audio", title: "Audio", empty: "No audio yet (voice-overs, music)." },
  { kind: "image", title: "Pictures", empty: "No pictures yet. A PNG with see-through parts keeps them (logos, map highlights)." },
  { kind: "font", title: "Fonts", empty: "Upload a .ttf or .otf file to use it for titles." },
];

let uploadKey = 0;

export default function AssetPanel({ project, accepts, disabled, onProject, onDeleted }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const busy = uploads.some((u) => !u.error && u.fraction < 1);
  const { limits, usage } = project;

  /** Files or whole folders: each file keeps the folder it came from (the assistant reads the folder names too). */
  async function send(chosen: Picked[]) {
    setNotice(null);
    const problems: string[] = [];
    const { accepted, skipped } = splitByExtension(mergePicked([], chosen), accepts);
    if (skipped.length) problems.push(`Left out (not a supported file): ${skipped.slice(0, 5).map((s) => baseName(s.path)).join(", ")}${skipped.length > 5 ? ` and ${skipped.length - 5} more` : ""}`);
    for (const { file, path } of accepted) {
      const key = (uploadKey += 1);
      setUploads((list) => [...list, { key, name: path, fraction: 0 }]);
      try {
        const result = await uploadAsset(project.id, file, folderOf(path), (f) => setUploads((list) => list.map((u) => (u.key === key ? { ...u, fraction: f } : u)))).promise;
        onProject(result.project);
        result.rejected.forEach((r) => problems.push(`${r.name}: ${r.reason}`));
        setUploads((list) => list.filter((u) => u.key !== key));
      } catch (e) {
        const message = e instanceof ApiError ? e.message : "Upload failed.";
        setUploads((list) => list.map((u) => (u.key === key ? { ...u, error: message } : u)));
      }
    }
    if (problems.length) setNotice(problems.join("\n"));
  }

  const row = (a: Asset) => (
    <li key={a.id} className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.02] p-1.5">
      {a.kind === "audio" || a.kind === "font" ? (
        <span className="flex h-10 w-14 shrink-0 items-center justify-center rounded bg-white/5 text-lg" aria-hidden>
          {a.kind === "audio" ? "♪" : "Aa"}
        </span>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={thumbUrl(project.id, a.id)} alt="" className="h-10 w-14 shrink-0 rounded object-cover" />
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm" title={a.folder ? `${a.folder}/${a.name}` : (a.name ?? "")}>
          {a.folder && <span className="text-white/40">{a.folder}/</span>}
          {a.name}
        </p>
        <p className="text-xs text-white/40">
          {a.family ? `${a.family} · ` : ""}
          {a.duration ? `${formatSeconds(a.duration)} · ` : ""}
          {a.width && a.height ? `${a.width}×${a.height} · ` : ""}
          {formatMegabytes(a.size_bytes)}
          {a.kind === "video" && !a.has_audio ? " · no sound" : ""}
        </p>
        {a.kind === "audio" && <audio controls preload="none" src={assetFileUrl(project.id, a.id)} className="mt-1 h-7 w-full" />}
      </div>
      <ConfirmButton label="Delete" disabled={disabled} onConfirm={() => void deleteAsset(project.id, a.id).then((p) => onDeleted(a.id, p)).catch((e) => setNotice(e instanceof ApiError ? e.message : "Could not delete."))} />
    </li>
  );

  return (
    <div className="space-y-4">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (!disabled)
            void safeFromDataTransfer(e.dataTransfer).then((items) => {
              if (items.length) void send(items);
            });
        }}
        className={`rounded-xl border-2 border-dashed p-4 text-center text-sm ${dragging ? "border-violet-400 bg-violet-500/10" : "border-white/15"}`}
      >
        <p className="text-white/70">Drop your clips, audio and pictures, or whole folders, here</p>
        <div className="mt-2 flex flex-wrap justify-center gap-2">
          <button disabled={disabled || busy} onClick={() => input.current?.click()} className="rounded-lg bg-violet-600 px-4 py-1.5 text-sm font-semibold hover:bg-violet-500 disabled:bg-white/10 disabled:text-white/30">
            Choose files
          </button>
          <button disabled={disabled || busy} onClick={() => folderInput.current?.click()} className="rounded-lg border border-white/20 px-4 py-1.5 text-sm hover:bg-white/5 disabled:opacity-40">
            Choose a folder
          </button>
        </div>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          accept={accepts.join(",")}
          onChange={(e) => {
            const items = fromFileList(e.target.files ?? []);
            e.target.value = "";
            if (items.length) void send(items);
          }}
        />
        <input
          ref={folderInput}
          type="file"
          hidden
          {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
          onChange={(e) => {
            const items = fromFileList(e.target.files ?? []);
            e.target.value = "";
            if (items.length) void send(items);
          }}
        />
        <p className="mt-2 text-xs text-white/40">
          {usage.assets} of {limits.max_assets} files · {formatMegabytes(usage.bytes)} of {limits.max_storage_mb} MB · up to {limits.max_file_mb} MB each
        </p>
      </div>

      {uploads.length > 0 && (
        <ul className="space-y-1" aria-label="Uploads">
          {uploads.map((u) => (
            <li key={u.key} className="text-xs">
              <div className="flex justify-between gap-2">
                <span className="truncate">{u.name}</span>
                {u.error ? (
                  <button className="text-red-300 underline" onClick={() => setUploads((list) => list.filter((x) => x.key !== u.key))}>
                    dismiss
                  </button>
                ) : (
                  <span className="tabular-nums text-white/50">{Math.round(u.fraction * 100)}%</span>
                )}
              </div>
              {u.error ? <p className="text-red-300">{u.error}</p> : <div className="mt-0.5 h-1 rounded bg-white/10"><div className="h-1 rounded bg-violet-500" style={{ width: `${u.fraction * 100}%` }} /></div>}
            </li>
          ))}
        </ul>
      )}
      {notice && (
        <p role="alert" className="whitespace-pre-line rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
          {notice}
        </p>
      )}

      {GROUPS.map((g) => {
        const items = project.assets
          .filter((a) => a.kind === g.kind)
          .sort((a, b) => naturalCompare(a.folder ?? "", b.folder ?? "") || naturalCompare(a.name ?? "", b.name ?? "")); // folder by folder, like the user's own folders
        if (g.kind === "font" && !limits.custom_fonts && items.length === 0) return null; // the plan has no custom fonts: don't mention them
        return (
          <div key={g.kind}>
            <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-white/40">
              {g.title} <span className="font-normal">({items.length})</span>
            </h3>
            {items.length === 0 ? <p className="text-xs text-white/30">{g.empty}</p> : <ul className="space-y-1.5">{items.map(row)}</ul>}
          </div>
        );
      })}
    </div>
  );
}
