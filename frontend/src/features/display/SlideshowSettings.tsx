import { useTranslation } from "react-i18next";

import { useDisplayCapabilities } from "@/api/queries";
import { cn } from "@/shared/cn";

import { DONT_CHANGE } from "./summary";

/** How a TV rotates: the interval (or "Don't change") and the order. */
export function SlideshowSettings({
  minutes,
  ordered,
  onChange,
  disabled,
}: {
  minutes: number;
  ordered: boolean;
  onChange: (next: { minutes?: number; ordered?: boolean }) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const caps = useDisplayCapabilities();
  // Only what the firmware accepts (measured: everything else answers -7), plus "Don't change".
  const intervals = [DONT_CHANGE, ...(caps.data?.slideshow_minutes ?? [3, 15, 60, 720, 1440])];
  const rotates = minutes !== DONT_CHANGE;

  return (
    <div className="flex flex-wrap items-center gap-3 text-xs">
      <label className="flex items-center gap-2">
        {t("display.every")}
        <select
          value={minutes}
          disabled={disabled}
          onChange={(event) => onChange({ minutes: Number(event.target.value) })}
          className="rounded border border-border-strong bg-bg px-1.5 py-1"
        >
          {intervals.map((value) => (
            <option key={value} value={value}>
              {t(`display.intervals.${value}`)}
            </option>
          ))}
        </select>
      </label>
      <div
        role="radiogroup"
        aria-label={t("display.order")}
        title={rotates ? undefined : t("display.orderStaticHint")}
        className={cn(
          "flex rounded-md border border-border-strong p-0.5",
          !rotates && "opacity-50",
        )}
      >
        {[true, false].map((value) => (
          <button
            key={String(value)}
            type="button"
            role="radio"
            aria-checked={ordered === value}
            disabled={disabled || !rotates}
            onClick={() => onChange({ ordered: value })}
            className={cn(
              "rounded px-2 py-0.5 text-xs text-muted hover:text-text disabled:hover:text-muted",
              ordered === value && "bg-panel-2 text-text",
            )}
          >
            {value ? t("display.inOrderOption") : t("display.shuffleOption")}
          </button>
        ))}
      </div>
    </div>
  );
}
