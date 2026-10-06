import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { API_BASE, type DisplayProgress, type DisplayPushResult } from "./client";

export interface IngestedEvent {
  photo_id: string;
  upload_id: string;
  sha256: string;
  filename: string;
  duplicate: boolean;
  /** For duplicates: what this copy added to the existing photo (`location`, `filename`). */
  merged: string[];
}

export interface IngestFailedEvent {
  upload_id: string;
  sha256: string;
  filename: string;
  code: string;
  message: string;
}

export interface LocalSendTransferFile {
  file_id: string;
  filename: string;
  size: number;
  /** `known`: already in the library (not imported again); `rejected`: unsupported (`code`). */
  status: "incoming" | "known" | "rejected";
  photo_id?: string;
  restored?: boolean;
  code?: string;
}

export type LocalSendFileEvent = { session_id: string; file_id: string } & (
  | { status: "receiving" }
  | { status: "processing"; upload_id: string }
  | { status: "known"; photo_id: string; restored: boolean }
  | { status: "failed"; code: string }
);

export interface ServerEvents {
  "localsend.request": { id: string; alias: string };
  "localsend.request_closed": { id: string; approved: boolean };
  "localsend.transfer": {
    session_id: string;
    device_id: string;
    alias: string;
    files: LocalSendTransferFile[];
  };
  "localsend.file": LocalSendFileEvent;
  "localsend.cancelled": { session_id: string };
  "photo.ingested": IngestedEvent;
  "photo.ingest_failed": IngestFailedEvent;
  "job.failed": { job_id: string; kind: string; code: string | null; error: string | null };
  "photo.updated": { photo_ids: string[] };
  "artwork.rendered": { artwork_id: string; render_hash: string };
  /** `entity`: `artwork` | `collection` | `tag` — what a page has to refetch. */
  "entity.changed": { entity: string; id: string };
  "trash.purged": { photos: number; artworks: number; bytes: number };
  "trash.changed": { batch_id: string };
  /** A push finished: what went to the TV, and what it refused to delete on its own. */
  "display.pushed": DisplayPushResult;
  /** How far a push is (throttled): `queued` → `rendering` → `uploading` → `removing` → `starting`. */
  "display.progress": DisplayProgress & { target_id: string };
}

type EventName = keyof ServerEvents;
type Listener<K extends EventName> = (data: ServerEvents[K]) => void;

const listeners = new Map<EventName, Set<Listener<EventName>>>();

/** At most one refetch of the derived counts (collection tree, tags) per this many ms. */
const COUNTS_REFRESH_MS = 1000;

/** Subscribe to a server event outside React (e.g. the upload store). Returns an unsubscribe. */
export function onServerEvent<K extends EventName>(name: K, listener: Listener<K>): () => void {
  const set = listeners.get(name) ?? new Set();
  set.add(listener as Listener<EventName>);
  listeners.set(name, set);
  return () => set.delete(listener as Listener<EventName>);
}

function emit<K extends EventName>(name: K, data: ServerEvents[K]) {
  listeners.get(name)?.forEach((listener) => listener(data));
}

/** Keeps one EventSource open while mounted and refreshes cached queries on changes. */
export function useServerEvents(enabled: boolean) {
  const qc = useQueryClient();

  useEffect(() => {
    if (!enabled) return;
    const source = new EventSource(`${API_BASE}/events`);
    // The tree's counts and the tag counts are derived from many artworks, and the editor saves
    // every `AUTOSAVE_MS` while a slider moves: one refetch per burst is enough. The refetch runs
    // after the first event of a burst, so it reads every change made until then; a later event
    // schedules another one — the last change is never missed.
    const timers = new Map<string, ReturnType<typeof setTimeout>>();
    const invalidateSoon = (key: "collections" | "tags") => {
      if (timers.has(key)) return;
      timers.set(
        key,
        setTimeout(() => {
          timers.delete(key);
          void qc.invalidateQueries({ queryKey: [key] });
        }, COUNTS_REFRESH_MS),
      );
    };
    const names: EventName[] = [
      "photo.ingested",
      "photo.ingest_failed",
      "job.failed",
      "localsend.request",
      "localsend.request_closed",
      "localsend.transfer",
      "localsend.file",
      "localsend.cancelled",
      "photo.updated",
      "artwork.rendered",
      "entity.changed",
      "trash.changed",
      "trash.purged",
      "display.pushed",
      "display.progress",
    ];
    const handlers = names.map((name) => {
      const handler = (message: MessageEvent<string>) => {
        const data = JSON.parse(message.data) as ServerEvents[typeof name];
        emit(name, data);
        if (name === "artwork.rendered" || name === "entity.changed") {
          void qc.invalidateQueries({ queryKey: ["artworks"] });
        }
        if (name === "entity.changed") {
          const entity = (data as ServerEvents["entity.changed"]).entity;
          // Smart collections match on an artwork's fields and tags, so a changed artwork or tag
          // moves the tree's counts, and tag counts move with artworks (user feedback). Every
          // artwork write publishes this event — the editor's autosave included, hence the
          // coalescing for artworks; a collection or a tag changes on a deliberate action.
          if (entity === "collection" || entity === "tag") {
            void qc.invalidateQueries({ queryKey: ["collections"] });
          }
          if (entity === "tag") void qc.invalidateQueries({ queryKey: ["tags"] });
          if (entity === "artwork") {
            invalidateSoon("collections");
            invalidateSoon("tags");
          }
        }
        if (name === "photo.ingested" || name === "photo.updated") {
          void qc.invalidateQueries({ queryKey: ["photos"] });
        }
        if (name === "photo.updated") {
          // An artwork carries its photos' tags, and marking it ready moves its photos out of
          // the inbox: what an artwork list, a smart collection or a tag count shows moves too.
          void qc.invalidateQueries({ queryKey: ["artworks"] });
          void qc.invalidateQueries({ queryKey: ["tags"] });
          void qc.invalidateQueries({ queryKey: ["collections"] });
        }
        if (
          name === "entity.changed" &&
          (data as ServerEvents["entity.changed"]).entity === "tag"
        ) {
          // A tag renamed, merged, deleted or re-categorised elsewhere: the chips on photos and
          // artworks, and the smart collections matching on it, change too.
          void qc.invalidateQueries({ queryKey: ["photos"] });
          void qc.invalidateQueries({ queryKey: ["collections"] });
        }
        if (name === "job.failed") {
          // The activity centre badges the count, and the failure is said out loud once.
          void qc.invalidateQueries({ queryKey: ["jobs"] });
        }
        if (name.startsWith("trash.")) {
          // A purge or a restore moves rows between the library and the trash: refetch both.
          void qc.invalidateQueries({ queryKey: ["trash"] });
          void qc.invalidateQueries({ queryKey: ["photos"] });
          void qc.invalidateQueries({ queryKey: ["artworks"] });
          void qc.invalidateQueries({ queryKey: ["collections"] });
          // Tag counts ignore trashed rows (docs/organization.md §1).
          void qc.invalidateQueries({ queryKey: ["tags"] });
        }
        if (name === "display.pushed") {
          void qc.invalidateQueries({ queryKey: ["display"] });
        }
        if (name === "job.failed" && (data as ServerEvents["job.failed"]).kind === "display.push") {
          // The TV card shows the error and drops the progress it was showing.
          void qc.invalidateQueries({ queryKey: ["display"] });
        }
        if (name.startsWith("localsend.")) {
          void qc.invalidateQueries({ queryKey: ["localsend"] });
        }
      };
      source.addEventListener(name, handler);
      return [name, handler] as const;
    });
    return () => {
      handlers.forEach(([name, handler]) => source.removeEventListener(name, handler));
      source.close();
      timers.forEach((timer) => clearTimeout(timer));
    };
  }, [enabled, qc]);
}
