// Colour picker used for the mat, bands and shadows (§11.3): free picker, curated presets, saved
// swatches and the colours of the photo itself (server palette, OKLab k-means).
import * as Popover from "@radix-ui/react-popover";
import { Plus, X } from "lucide-react";
import { useState } from "react";
import { HexColorPicker } from "react-colorful";
import { useTranslation } from "react-i18next";

import { useColorPresets, usePhotoPalette, useSwatchActions, useSwatches } from "@/api/queries";
import { cn } from "@/shared/cn";

interface ColorFieldProps {
  color: string;
  onChange: (color: string) => void;
  /** Committed value (end of a drag): used to group undo steps. */
  onCommit?: () => void;
  label: string;
  /** Photo whose palette is offered (the selected slot's photo). */
  photoId?: string | null;
}

const normalize = (value: string) => `#${value.replace("#", "").toUpperCase().slice(0, 6)}`;
const isHex = (value: string) => /^#[0-9A-F]{6}$/.test(value);

export function ColorField({ color, onChange, onCommit, label, photoId }: ColorFieldProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(color);
  const presets = useColorPresets();
  const swatches = useSwatches();
  const palette = usePhotoPalette(open ? (photoId ?? null) : null);
  const { create, remove } = useSwatchActions();

  const pick = (value: string) => {
    onChange(normalize(value));
    setText(normalize(value));
    onCommit?.();
  };

  return (
    <Popover.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        setText(color);
        if (!next) onCommit?.();
      }}
    >
      <Popover.Trigger asChild>
        <button
          type="button"
          aria-label={label}
          className="flex h-7 min-w-0 flex-1 items-center gap-2 rounded border border-border bg-panel-2 px-1.5 text-xs"
        >
          <span
            className="h-4 w-4 shrink-0 rounded-sm border border-black/30"
            style={{ backgroundColor: color }}
          />
          <span className="truncate tabular-nums">{color}</span>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          sideOffset={6}
          align="end"
          // Radix sees `Escape` in the capture phase on the document while the command registry
          // listens on `window` (bubble): without this, closing the popover also ran the editor's
          // `Escape` command and left the editor.
          onEscapeKeyDown={(event) => event.stopPropagation()}
          className="z-50 w-64 rounded-lg border border-border bg-panel p-3 shadow-2xl"
        >
          <HexColorPicker
            color={color}
            onChange={(value) => {
              onChange(normalize(value));
              setText(normalize(value));
            }}
            onMouseUp={onCommit}
            onTouchEnd={onCommit}
          />
          <div className="mt-2 flex items-center gap-1.5">
            <input
              value={text}
              onChange={(event) => {
                setText(event.target.value);
                const next = normalize(event.target.value);
                if (isHex(next)) onChange(next);
              }}
              onBlur={() => {
                setText(color);
                onCommit?.();
              }}
              aria-label={t("editor.colors.hex")}
              className="h-7 w-24 rounded border border-border bg-panel-2 px-1.5 font-mono text-xs uppercase"
            />
            <button
              type="button"
              onClick={() => create.mutate({ color })}
              className="ml-auto inline-flex h-7 items-center gap-1 rounded border border-border px-1.5 text-[11px] text-muted hover:text-text"
            >
              <Plus size={12} /> {t("editor.colors.save")}
            </button>
          </div>

          <Swatches title={t("editor.colors.saved")}>
            {(swatches.data ?? []).map((swatch) => (
              <span key={swatch.id} className="group relative">
                <Dot color={swatch.color} active={swatch.color === color} onClick={pick} />
                <button
                  type="button"
                  aria-label={t("common.remove")}
                  onClick={() => remove.mutate(swatch.id)}
                  className="absolute -top-1 -right-1 hidden rounded-full bg-panel text-muted group-hover:block hover:text-danger"
                >
                  <X size={10} />
                </button>
              </span>
            ))}
            {(swatches.data ?? []).length === 0 && (
              <span className="text-[11px] text-muted">{t("editor.colors.noSwatches")}</span>
            )}
          </Swatches>

          <Swatches title={t("editor.colors.presets")}>
            {(presets.data ?? []).map((preset) => (
              <Dot
                key={preset.color}
                color={preset.color}
                title={preset.name}
                active={preset.color === color}
                onClick={pick}
              />
            ))}
          </Swatches>

          {photoId && (
            <Swatches title={t("editor.colors.fromPhoto")}>
              {(palette.data ?? []).map((entry) => (
                <Dot
                  key={`${entry.kind}-${entry.color}`}
                  color={entry.color}
                  title={t(`editor.colors.kinds.${entry.kind}`)}
                  active={entry.color === color}
                  onClick={pick}
                />
              ))}
              {palette.isLoading && (
                <span className="text-[11px] text-muted">{t("editor.colors.analyzing")}</span>
              )}
            </Swatches>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function Swatches({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-2.5">
      <div className="mb-1 text-[10px] tracking-wide text-muted uppercase">{title}</div>
      <div className="flex flex-wrap items-center gap-1.5">{children}</div>
    </div>
  );
}

function Dot({
  color,
  active,
  title,
  onClick,
}: {
  color: string;
  active: boolean;
  title?: string;
  onClick: (color: string) => void;
}) {
  return (
    <button
      type="button"
      title={title ? `${title} · ${color}` : color}
      onClick={() => onClick(color)}
      style={{ backgroundColor: color }}
      className={cn(
        "h-5 w-5 rounded border border-black/30",
        active && "ring-2 ring-accent ring-offset-1 ring-offset-panel",
      )}
    />
  );
}
