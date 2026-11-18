import i18n from "@/i18n";

export function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1;
  return `${new Intl.NumberFormat(i18n.language, { maximumFractionDigits: digits }).format(value)} ${units[unit]}`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );
}

/** Capture times are floating wall-clock times stored as UTC: never convert them. */
export function formatCaptureTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(iso));
}

function capitalize(text: string): string {
  return text.charAt(0).toLocaleUpperCase(i18n.language) + text.slice(1);
}

/** A month's name on its own, as a heading ("March", "Mars"); `month` 1 = January. */
export function formatMonth(month: number): string {
  return capitalize(
    new Intl.DateTimeFormat(i18n.language, { month: "long", timeZone: "UTC" }).format(
      Date.UTC(2000, month - 1, 1),
    ),
  );
}

/** A capture period (`shared/period.ts`) inside a sentence: "2024", or "March 2024" ("mars 2024"). */
export function formatPeriod(period: string): string {
  if (period.length === 4) return period;
  const date = Date.UTC(Number(period.slice(0, 4)), Number(period.slice(5, 7)) - 1, 1);
  return new Intl.DateTimeFormat(i18n.language, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const seconds = (new Date(iso).getTime() - Date.now()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(i18n.language, { numeric: "auto" });
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ["second", 60],
    ["minute", 60],
    ["hour", 24],
    ["day", 30],
    ["month", 12],
    ["year", Infinity],
  ];
  let value = seconds;
  for (const [unit, size] of steps) {
    if (Math.abs(value) < size) return rtf.format(Math.round(value), unit);
    value /= size;
  }
  return formatDateTime(iso);
}

export function megapixels(width: number, height: number): string {
  return `${(Math.round((width * height) / 100_000) / 10).toFixed(1)} MP`;
}
