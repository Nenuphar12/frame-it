/**
 * Pushes in flight, by TV, fed by `display.progress` (outside React, like the upload queue).
 *
 * The server also keeps the running push's progress on the target, so a page loaded mid-push
 * starts from `target.progress`; the events then take over until `display.pushed` (or the job's
 * failure) ends it. `livePush` merges both: whichever is newer for that target wins.
 */
import { create } from "zustand";

import type { DisplayProgress, DisplayPushResult, DisplayTarget } from "@/api/client";
import { onServerEvent } from "@/api/events";

export type Phase = DisplayProgress["phase"];

interface PushState {
  live: Record<string, DisplayProgress>;
  /**
   * Targets whose push ended since the targets list was last fetched (it may still show it):
   * the job id, or `*` when the end came before any progress event of that job.
   */
  ended: Record<string, string>;
}

export const usePushes = create<PushState>(() => ({ live: {}, ended: {} }));

/** Where each phase sits on one bar (the server's job progress uses the same spans). */
const SPANS: Record<Phase, [number, number]> = {
  queued: [0, 0],
  rendering: [0, 0.4],
  uploading: [0.4, 0.9],
  removing: [0.9, 0.95],
  starting: [0.95, 1],
};

export function pushFraction(progress: DisplayProgress): number {
  const [start, end] = SPANS[progress.phase];
  const part = progress.total > 0 ? progress.done / progress.total : 0;
  return start + (end - start) * part;
}

/** The push running on this TV, if any: the live event, else what the server last stored. */
export function livePush(
  target: Pick<DisplayTarget, "id" | "progress">,
  state: PushState,
): DisplayProgress | null {
  const live = state.live[target.id];
  if (live) return live;
  const stored = target.progress ?? null;
  if (!stored) return null;
  // The list can be older than the event that ended this very job.
  const ended = state.ended[target.id];
  return ended === "*" || ended === stored.job_id ? null : stored;
}

let watching = false;

/**
 * Subscribe once (the sidebar tray calls it). `onDone` hears every finished push — the tray turns
 * it into the summary toast.
 */
export function watchPushes(onDone: (result: DisplayPushResult) => void): () => void {
  if (watching) return () => undefined;
  watching = true;
  const offProgress = onServerEvent("display.progress", ({ target_id, ...progress }) =>
    usePushes.setState((state) => ({
      live: { ...state.live, [target_id]: progress },
      ended: omit(state.ended, target_id),
    })),
  );
  const end = (targetId: string, jobId: string | undefined) =>
    usePushes.setState((state) => ({
      live: omit(state.live, targetId),
      ended: { ...state.ended, [targetId]: jobId ?? "*" },
    }));
  const offPushed = onServerEvent("display.pushed", (result) => {
    end(result.target_id, usePushes.getState().live[result.target_id]?.job_id);
    onDone(result);
  });
  const offFailed = onServerEvent("job.failed", (event) => {
    if (event.kind !== "display.push") return;
    const live = usePushes.getState().live;
    const targetId = Object.keys(live).find((id) => live[id]?.job_id === event.job_id);
    if (targetId) end(targetId, event.job_id);
  });
  return () => {
    offProgress();
    offPushed();
    offFailed();
    watching = false;
  };
}

function omit<T>(record: Record<string, T>, key: string): Record<string, T> {
  if (!(key in record)) return record;
  return Object.fromEntries(Object.entries(record).filter(([name]) => name !== key));
}
