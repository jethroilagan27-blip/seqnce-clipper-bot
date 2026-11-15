"use client";

import { useState, type ReactNode } from "react";

export const inputCls =
  "rounded-md border border-white/10 bg-[#15151c] px-2 py-1 text-sm focus:border-violet-400 focus:outline-none disabled:opacity-50";
export const buttonCls =
  "rounded-lg border border-white/15 px-3 py-1.5 text-sm text-white/80 hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-40";
export const primaryCls =
  "rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold hover:bg-violet-500 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-white/30";

type NumberProps = {
  value: number | null;
  onChange: (value: number | null) => void;
  min?: number;
  max?: number;
  /** Allow an empty box (it means "automatic"); the empty value is reported as null. */
  nullable?: boolean;
  placeholder?: string;
  disabled?: boolean;
  label: string;
  className?: string;
};

/** A number box that lets you type "1." or clear it while typing, and reports only valid numbers. */
export function NumberInput({ value, onChange, min = 0, max, nullable, placeholder, disabled, label, className = "w-20" }: NumberProps) {
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <input
      type="text"
      inputMode="decimal"
      aria-label={label}
      title={label}
      disabled={disabled}
      placeholder={placeholder}
      className={`${inputCls} ${className} tabular-nums`}
      value={draft ?? (value === null ? "" : String(value))}
      onChange={(e) => {
        const raw = e.target.value;
        setDraft(raw);
        if (raw.trim() === "") {
          if (nullable) onChange(null);
          return;
        }
        const n = Number(raw.replace(",", "."));
        if (Number.isFinite(n) && n >= min && (max === undefined || n <= max)) onChange(Math.round(n * 1000) / 1000);
      }}
      onBlur={() => setDraft(null)}
    />
  );
}

export function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="space-y-2 border-t border-white/10 pt-3 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h4 className="text-sm font-semibold text-white/90">{title}</h4>
        {hint && <p className="text-xs text-white/40">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

export function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-wrap items-center gap-2 text-xs text-white/60">
      <span className="min-w-[5.5rem]">{label}</span>
      {children}
    </label>
  );
}

/** A delete button that asks "Sure?" on the first click. */
export function ConfirmButton({ label, onConfirm, disabled, className = "" }: { label: string; onConfirm: () => void; disabled?: boolean; className?: string }) {
  const [asked, setAsked] = useState(false);
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => {
        if (asked) {
          setAsked(false);
          onConfirm();
        } else setAsked(true);
      }}
      onBlur={() => setAsked(false)}
      className={`rounded-md border px-2 py-0.5 text-xs disabled:opacity-40 ${asked ? "border-red-400 bg-red-500/20 text-red-100" : "border-red-400/30 text-red-300 hover:bg-red-500/10"} ${className}`}
    >
      {asked ? "Sure?" : label}
    </button>
  );
}
