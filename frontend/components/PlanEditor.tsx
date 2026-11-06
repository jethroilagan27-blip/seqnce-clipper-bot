"use client";

import { useState } from "react";
import {
  HOOK_CSS,
  formatDuration,
  type ChangedClip,
  type ManualEdit,
  type Version,
} from "@/lib/api";
import { ChangeChips } from "./RevisionPanel";

const BADGE: Record<string, string> = {
  added: "bg-emerald-500/15 text-emerald-300",
  trimmed: "bg-amber-400/15 text-amber-200",
  removed: "bg-red-500/15 text-red-300",
};

type Props = {
  version: Version;
  isCurrent: boolean;
  busy: boolean;
  onApply: (edit: ManualEdit) => Promise<string | null>; // resolves to an error message, or null
  onRestore: (version: number) => Promise<string | null>;
};

// Mount with key={version.version}: the draft below starts from that version's plan.
export default function PlanEditor({ version, isCurrent, busy, onApply, onRestore }: Props) {
  const plan = version.plan;
  const hook = plan.hook ?? { enabled: false, text: "", color: "yellow", duration_s: 4 };
  const captionsOn = plan.captions?.enabled ?? true;

  const [hookEnabled, setHookEnabled] = useState(hook.enabled);
  const [hookText, setHookText] = useState(hook.text);
  const [hookColor, setHookColor] = useState(hook.color);
  const [captions, setCaptions] = useState(captionsOn);
  const [removed, setRemoved] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const rows: ChangedClip[] =
    version.changes?.clips ?? plan.clips.map((c) => ({ ...c, status: "kept" as const }));
  const liveRows = rows.filter((r) => r.status !== "removed").length;

  const edit: ManualEdit = {};
  if (hookEnabled !== hook.enabled) edit.hook_enabled = hookEnabled;
  if (hookText.trim() !== hook.text) edit.hook_text = hookText.trim();
  if (hookColor !== hook.color) edit.hook_color = hookColor;
  if (captions !== captionsOn) edit.captions_enabled = captions;
  if (removed.length) edit.remove_clips = removed;
  const dirty = Object.keys(edit).length;
  const locked = busy || working;

  async function apply() {
    setWorking(true);
    setError(null);
    const err = await onApply(edit);
    setWorking(false);
    if (err) setError(err);
  }

  async function restore() {
    setWorking(true);
    setError(null);
    const err = await onRestore(version.version);
    setWorking(false);
    if (err) setError(err);
  }

  return (
    <div className="space-y-4 rounded-2xl border border-white/10 p-4 text-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-medium">
            Version {version.version}
            <span className="ml-2 text-xs font-normal text-white/40">
              {version.source === "initial"
                ? "first edit"
                : version.source === "chat"
                  ? "from chat"
                  : version.source === "manual"
                    ? "edited by hand"
                    : "restored"}
            </span>
          </p>
          <ChangeChips changes={version.changes} />
        </div>
        <span
          className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs ${
            plan.source === "ai" ? "bg-violet-500/20 text-violet-200" : "bg-amber-400/20 text-amber-100"
          }`}
        >
          {plan.source === "ai" ? "Chosen by AI" : "Basic cut"}
        </span>
      </div>

      {plan.instructions && (
        <p className="text-xs text-white/50">
          Your first request: <span className="text-white/70">&ldquo;{plan.instructions}&rdquo;</span>
        </p>
      )}

      <ul className="space-y-1.5">
        {rows.map((c) => {
          const gone = c.status === "removed" || removed.includes(c.id);
          return (
            <li key={`${c.status}-${c.id}-${c.start}`} className="flex items-start gap-3 text-white/60">
              <span className={`w-24 shrink-0 tabular-nums ${gone ? "text-white/30 line-through" : "text-violet-300"}`}>
                {formatDuration(c.start)}–{formatDuration(c.end)}
              </span>
              <span className={`min-w-0 flex-1 ${gone ? "text-white/30 line-through" : ""}`}>
                <span className="text-white/80">{c.purpose.replace("_", " ")}</span>
                {c.reason && <> — {c.reason}</>}
                {c.status === "trimmed" && c.before && (
                  <span className="ml-2 text-xs text-amber-200/70">
                    was {formatDuration(c.before.start)}–{formatDuration(c.before.end)}
                  </span>
                )}
              </span>
              {BADGE[c.status] && (
                <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${BADGE[c.status]}`}>{c.status}</span>
              )}
              {isCurrent && c.status !== "removed" && (
                <button
                  disabled={locked || (liveRows - removed.length <= 1 && !removed.includes(c.id))}
                  onClick={() =>
                    setRemoved((r) => (r.includes(c.id) ? r.filter((x) => x !== c.id) : [...r, c.id]))
                  }
                  className="shrink-0 text-xs text-white/50 underline hover:text-white disabled:opacity-30 disabled:no-underline"
                  title={liveRows - removed.length <= 1 ? "At least one clip has to stay" : undefined}
                >
                  {removed.includes(c.id) ? "Undo" : "Remove"}
                </button>
              )}
            </li>
          );
        })}
      </ul>

      {isCurrent ? (
        <div className="space-y-3 border-t border-white/10 pt-4">
          <div className="space-y-2">
            <label className="flex items-center justify-between gap-3">
              <span className="font-medium">Hook title</span>
              <input
                type="checkbox"
                className="h-5 w-5 accent-violet-500"
                checked={hookEnabled}
                disabled={locked}
                onChange={(e) => setHookEnabled(e.target.checked)}
              />
            </label>
            {hookEnabled && (
              <>
                <input
                  type="text"
                  value={hookText}
                  maxLength={60}
                  disabled={locked}
                  onChange={(e) => setHookText(e.target.value)}
                  aria-label="Hook title text"
                  placeholder="Type a hook (max 8 words)"
                  className="w-full rounded-md border border-white/10 bg-[#15151c] px-3 py-2 text-sm font-semibold uppercase focus:border-violet-400 focus:outline-none"
                  style={{ color: HOOK_CSS[hookColor] ?? "#ffe600" }}
                />
                <div className="flex gap-2" role="radiogroup" aria-label="Hook colour">
                  {Object.entries(HOOK_CSS).map(([name, css]) => (
                    <button
                      key={name}
                      role="radio"
                      aria-checked={hookColor === name}
                      aria-label={name}
                      title={name}
                      disabled={locked}
                      onClick={() => setHookColor(name)}
                      className={`h-7 w-7 rounded-full border-2 ${
                        hookColor === name ? "border-white" : "border-transparent"
                      }`}
                      style={{ backgroundColor: css }}
                    />
                  ))}
                </div>
              </>
            )}
          </div>
          <label className="flex items-center justify-between gap-3">
            <span className="font-medium">Captions</span>
            <input
              type="checkbox"
              className="h-5 w-5 accent-violet-500"
              checked={captions}
              disabled={locked}
              onChange={(e) => setCaptions(e.target.checked)}
            />
          </label>
          <button
            disabled={!dirty || locked || (hookEnabled && !hookText.trim())}
            onClick={apply}
            className="w-full rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold hover:bg-violet-500 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-white/30"
          >
            {working ? "Applying…" : dirty ? `Apply ${dirty} change${dirty > 1 ? "s" : ""} (re-renders)` : "No changes yet"}
          </button>
        </div>
      ) : (
        <div className="border-t border-white/10 pt-4">
          <button
            disabled={locked}
            onClick={restore}
            className="w-full rounded-xl border border-white/20 px-4 py-2.5 text-sm font-medium hover:bg-white/5 disabled:opacity-40"
          >
            {working ? "Restoring…" : `Go back to version ${version.version}`}
          </button>
        </div>
      )}

      {error && (
        <p role="alert" className="text-xs text-red-300">
          {error}
        </p>
      )}
      {plan.warnings.length > 0 && <p className="text-xs text-white/40">Notes: {plan.warnings.join(" · ")}</p>}
    </div>
  );
}
