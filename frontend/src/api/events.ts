import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { API_BASE } from "./client";

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
  "job.failed": { job_id: string; error: string | null };
  "photo.updated": { photo_ids: string[] };
  "artwork.rendered": { artwork_id: string; render_hash: string };
  "entity.changed": { entity: string; id: string };
}

type EventName = keyof ServerEvents;
type Listener<K extends EventName> = (data: ServerEvents[K]) => void;

const listeners = new Map<EventName, Set<Listener<EventName>>>();

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
    ];
    const handlers = names.map((name) => {
      const handler = (message: MessageEvent<string>) => {
        const data = JSON.parse(message.data) as ServerEvents[typeof name];
        emit(name, data);
        if (name === "artwork.rendered" || name === "entity.changed") {
          void qc.invalidateQueries({ queryKey: ["artworks"] });
        }
        if (name === "photo.ingested" || name === "photo.updated") {
          void qc.invalidateQueries({ queryKey: ["photos"] });
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
    };
  }, [enabled, qc]);
}
