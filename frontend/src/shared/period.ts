/**
 * A capture period — a year (`2024`) or a month (`2024-03`) — as the Timeline links carry it
 * (`/photos?taken=`, `/artworks?taken=`). The server checks the same shape
 * (`services/timeline.PERIOD_PATTERN`). Capture times are floating camera-local time, so a period
 * is plain calendar arithmetic: no Date, no timezone (invariant 9).
 */

const PERIOD = /^\d{4}(-(0[1-9]|1[0-2]))?$/;

export function isPeriod(value: unknown): value is string {
  return typeof value === "string" && PERIOD.test(value) && Number(value.slice(0, 4)) >= 1;
}

/** `periodOf(2024)` = `"2024"`, `periodOf(2024, 3)` = `"2024-03"`. */
export function periodOf(year: number, month?: number): string {
  const y = String(year).padStart(4, "0");
  return month === undefined ? y : `${y}-${String(month).padStart(2, "0")}`;
}

function daysIn(year: number, month: number): number {
  if (month === 2) return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28;
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}

/** First and last day (`YYYY-MM-DD`, both included): the `taken_at` "between" clause's value. */
export function periodDays(period: string): [string, string] {
  const year = Number(period.slice(0, 4));
  if (period.length === 4) return [`${period}-01-01`, `${period}-12-31`];
  const month = Number(period.slice(5, 7));
  return [`${period}-01`, `${period}-${String(daysIn(year, month)).padStart(2, "0")}`];
}
