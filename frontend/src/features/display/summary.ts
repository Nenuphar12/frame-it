import type { TFunction } from "i18next";

import type { DisplayProgress, DisplayPushResult } from "@/api/client";

/** "Don't change": the first image stays on screen, nothing rotates and nothing is deleted. */
export const DONT_CHANGE = 0;

/** "Every 15 minutes · in order", "Don't change" — how a TV rotates, in one line. */
export function slideshowSummary(t: TFunction, minutes: number, ordered: boolean): string {
  if (minutes === DONT_CHANGE) return t("display.intervals.0");
  const every = t("display.everyInterval", { interval: t(`display.intervals.${minutes}`) });
  return `${every} · ${ordered ? t("display.inOrderOption") : t("display.shuffleOption")}`;
}

/** One sentence per fact, in the order a user asks them: what is on the TV, then the surprises. */
export function pushSummary(t: TFunction, result: DisplayPushResult): string {
  const counts = {
    count: result.total,
    uploaded: result.uploaded,
    reused: result.reused,
    removed: result.deleted_ours,
  };
  const parts = [
    result.mode === "static"
      ? t("display.result.static", counts)
      : t("display.result.slideshow", counts),
  ];
  if (result.deleted_foreign > 0) {
    parts.push(t("display.result.foreignDeleted", { count: result.deleted_foreign }));
  }
  if (result.foreign_remaining > 0) {
    parts.push(t("display.result.foreignShown", { count: result.foreign_remaining }));
  }
  if ((result.left_ours ?? 0) > 0) {
    parts.push(t("display.result.leftOurs", { count: result.left_ours }));
  }
  if (result.moved_to) parts.push(t("display.result.moved", { host: result.moved_to }));
  return parts.join(" ");
}

/** "Sending 5 of 12" — what a running push is doing now. */
export function phaseLabel(t: TFunction, progress: DisplayProgress): string {
  return t(`display.phases.${progress.phase}`, { done: progress.done, total: progress.total });
}
