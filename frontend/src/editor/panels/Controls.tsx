// Small form controls shared by the editor panels (kept here so the panels stay readable).
import { useState, type ReactNode } from "react";

import { cn } from "@/shared/cn";

export function PanelSection({
  title,
  action,
  children,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="border-b border-border px-3 py-3 last:border-b-0">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-[11px] font-semibold tracking-wide text-muted uppercase">{title}</h3>
        {action}
      </div>
      <div className="flex flex-col gap-2">{children}</div>
    </section>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex items-center gap-2 text-xs">
      <span className="w-20 shrink-0 text-muted">{label}</span>
      {children}
    </label>
  );
}

/**
 * Number input that can actually be typed into: while it has the focus the text the user typed is
 * shown as is (a half-typed `1` of `120`, an empty field, a lone `-`), and only parseable values
 * reach `onChange`. Showing the document value instead would fight the keyboard — the value can
 * come back changed (clamped, snapped, re-placed) and put the caret back at the start.
 */
export function NumberField({
  value,
  onChange,
  min,
  max,
  step = 1,
  suffix,
  disabled,
}: {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = (text: string) => {
    const next = Number(text);
    if (text.trim() === "" || !Number.isFinite(next)) return;
    onChange(Math.min(max ?? Infinity, Math.max(min ?? -Infinity, next)));
  };
  return (
    <span className="flex min-w-0 flex-1 items-center gap-1">
      <input
        type="number"
        className="h-7 w-full min-w-0 rounded border border-border bg-panel-2 px-1.5 text-xs tabular-nums disabled:opacity-50"
        value={draft ?? (Number.isFinite(value) ? String(value) : "0")}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onFocus={(event) => event.currentTarget.select()}
        onChange={(event) => {
          setDraft(event.target.value);
          commit(event.target.value);
        }}
        onBlur={() => setDraft(null)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            commit(event.currentTarget.value);
            setDraft(null);
          } else if (event.key === "Escape") {
            setDraft(null);
            event.currentTarget.blur();
          }
        }}
      />
      {suffix && <span className="text-[10px] text-muted">{suffix}</span>}
    </span>
  );
}

export function Slider({
  value,
  onChange,
  onCommit,
  min,
  max,
  step = 1,
  disabled,
}: {
  value: number;
  onChange: (value: number) => void;
  onCommit?: () => void;
  min: number;
  max: number;
  step?: number;
  disabled?: boolean;
}) {
  return (
    <input
      type="range"
      className="h-7 min-w-0 flex-1 accent-accent disabled:opacity-50"
      value={value}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      onChange={(event) => onChange(Number(event.target.value))}
      onPointerUp={onCommit}
      onKeyUp={onCommit}
    />
  );
}

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  title?: string;
  disabled?: boolean;
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: SegmentOption<T>[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div
      className="flex rounded-md border border-border p-0.5"
      role="radiogroup"
      aria-label={label}
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          title={option.title}
          disabled={option.disabled}
          onClick={() => onChange(option.value)}
          className={cn(
            "flex-1 rounded px-1.5 py-1 text-[11px] text-muted disabled:opacity-40",
            value === option.value && "bg-panel-2 text-text",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** Square icon button used by the panels (orientation, slots, arranging). */
export function IconButton({
  title,
  onClick,
  disabled,
  children,
}: {
  title: string;
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      disabled={disabled}
      onClick={onClick}
      className="inline-flex h-7 w-7 items-center justify-center rounded border border-border text-muted hover:text-text disabled:opacity-40 disabled:hover:text-muted"
    >
      {children}
    </button>
  );
}
