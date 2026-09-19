/**
 * Upload queue shared by desktop and mobile.
 *
 * Pipeline per file: hash (SHA-256, hash-wasm — works over plain HTTP, loaded on demand) →
 * open/resume session →
 * PATCH chunks (retry with backoff, resume from server offset) → wait for ingestion (SSE, with
 * polling fallback). Protocol: docs/PLAN.md §10 "uploads".
 *
 * Files received by the LocalSend receiver are mirrored as "remote" items (no `file`, driven by
 * `localsend.*` events only), so already-sent photos are reported in the same tray.
 */
import { create } from "zustand";

import { API_BASE, ApiError, api, CLIENT_HEADERS, toProblem, unwrap } from "@/api/client";
import { onServerEvent } from "@/api/events";

export type UploadStatus =
  | "queued"
  | "hashing"
  | "uploading"
  | "processing"
  | "done"
  | "duplicate"
  | "merged"
  | "failed"
  | "rejected";

export interface UploadMeta {
  tag_ids: string[];
  collection_ids: string[];
  favorite: boolean;
}

export interface UploadItem {
  id: string;
  /** Absent for remote (LocalSend) items. */
  file?: File;
  /** Remote items: sending device name. */
  source?: string;
  /** Remote items: `<session_id>/<file_id>`. */
  remoteKey?: string;
  /** Already-sent photo that was in the trash and has been restored. */
  restored?: boolean;
  name: string;
  size: number;
  status: UploadStatus;
  /** 0..1 for hashing/uploading. */
  progress: number;
  sha256?: string;
  uploadId?: string;
  photoId?: string;
  /** Problem code for failed/rejected items (translated via `errors.<code>`). */
  errorCode?: string;
  meta: UploadMeta;
}

interface UploadState {
  items: UploadItem[];
  add: (files: File[], meta?: Partial<UploadMeta>) => number;
  retry: (id: string) => void;
  remove: (id: string) => void;
  clearFinished: () => void;
}

const CONCURRENCY = 2;
const HASH_SLICE = 8 * 1024 * 1024;
const MAX_NETWORK_RETRIES = 6;
const PROCESSING_POLL_MS = 4000;
export const ACCEPTED_EXTENSIONS = ["jpg", "jpeg", "png", "avif"];
const REJECTED_EXTENSIONS = new Set(["heic", "heif"]);
const EMPTY_META: UploadMeta = { tag_ids: [], collection_ids: [], favorite: false };

let counter = 0;
const nextId = () => `u${Date.now().toString(36)}${(counter++).toString(36)}`;
const active = new Set<string>();

const extensionOf = (name: string) => name.split(".").pop()?.toLowerCase() ?? "";

export const isFinished = (s: UploadStatus) =>
  s === "done" || s === "duplicate" || s === "merged" || s === "failed" || s === "rejected";

export const useUploads = create<UploadState>((set, get) => ({
  items: [],
  add(files, meta) {
    const fullMeta = { ...EMPTY_META, ...meta };
    const accepted: UploadItem[] = [];
    for (const file of files) {
      const ext = extensionOf(file.name);
      const looksLikeImage = file.type.startsWith("image/") || ACCEPTED_EXTENSIONS.includes(ext);
      if (!looksLikeImage && !REJECTED_EXTENSIONS.has(ext)) continue;
      const item: UploadItem = {
        id: nextId(),
        file,
        name: file.name,
        size: file.size,
        status: REJECTED_EXTENSIONS.has(ext) ? "rejected" : "queued",
        progress: 0,
        meta: fullMeta,
      };
      if (item.status === "rejected") item.errorCode = "unsupported_format_heic";
      accepted.push(item);
    }
    set({ items: [...get().items, ...accepted] });
    pump();
    return accepted.length;
  },
  retry(id) {
    if (!findItem(id)?.file) return;
    patch(id, { status: "queued", progress: 0, errorCode: undefined });
    pump();
  },
  remove(id) {
    if (active.has(id)) return;
    set({ items: get().items.filter((i) => i.id !== id) });
  },
  clearFinished() {
    set({ items: get().items.filter((i) => !isFinished(i.status)) });
  },
}));

function patch(id: string, changes: Partial<UploadItem>) {
  useUploads.setState((state) => ({
    items: state.items.map((item) => (item.id === id ? { ...item, ...changes } : item)),
  }));
}

const findItem = (id: string) => useUploads.getState().items.find((i) => i.id === id);

function pump() {
  const { items } = useUploads.getState();
  const running = items.filter((i) => i.status === "hashing" || i.status === "uploading").length;
  let slots = CONCURRENCY - running;
  for (const item of items) {
    if (slots <= 0) break;
    if (item.status === "queued" && item.file && !active.has(item.id)) {
      slots -= 1;
      void process(item.id);
    }
  }
}

async function process(id: string) {
  active.add(id);
  try {
    const item = findItem(id);
    if (!item?.file) return;
    const file = item.file;
    const sha256 = item.sha256 ?? (await hashFile(id, file));
    patch(id, { sha256, status: "uploading", progress: 0 });
    const opened = await withRetry(() =>
      unwrap(
        api.POST("/api/v1/uploads", {
          body: {
            filename: item.name,
            size: item.size,
            sha256,
            mime: file.type,
            meta: item.meta,
          },
        }),
      ),
    );
    if (opened.status === "exists") {
      patch(id, { status: "duplicate", progress: 1, photoId: opened.photo_id ?? undefined });
      return;
    }
    const uploadId = opened.upload_id!;
    patch(id, { uploadId });
    const final = await sendChunks(id, file, uploadId, opened.offset, opened.chunk_bytes);
    if (final.status === "failed") {
      patch(id, { status: "rejected", errorCode: final.error ?? "upload_failed" });
      return;
    }
    patch(id, { status: "processing", progress: 1 });
    watchProcessing(id, uploadId);
  } catch (error) {
    const code = error instanceof ApiError ? error.code : "network_error";
    const rejected = error instanceof ApiError && error.status >= 400 && error.status < 500;
    patch(id, { status: rejected ? "rejected" : "failed", errorCode: code });
  } finally {
    active.delete(id);
    pump();
  }
}

async function hashFile(id: string, file: File): Promise<string> {
  patch(id, { status: "hashing", progress: 0 });
  // 18 kB (wasm inlined) that only an actual upload needs: kept out of the initial bundle, which
  // every page — the phone upload page included — would otherwise download. The module registry
  // caches it, so only the first file of a session pays; a failed load lands in `runItem`'s catch
  // as a retryable `failed` item, like any other network error.
  const { createSHA256 } = await import("hash-wasm");
  const hasher = await createSHA256();
  hasher.init();
  for (let offset = 0; offset < file.size; offset += HASH_SLICE) {
    const buffer = await file.slice(offset, offset + HASH_SLICE).arrayBuffer();
    hasher.update(new Uint8Array(buffer));
    patch(id, { progress: Math.min(1, (offset + HASH_SLICE) / file.size) });
  }
  return hasher.digest("hex");
}

async function sendChunks(
  id: string,
  file: File,
  uploadId: string,
  startOffset: number,
  chunkBytes: number,
) {
  let offset = startOffset;
  let last: { status: string; offset: number; error?: string | null } = {
    status: "open",
    offset,
  };
  // Always send at least one request: an empty chunk finalizes a fully received session.
  for (let first = true; first || offset < file.size; first = false) {
    last = await withRetry(
      async () => {
        const body = file.slice(offset, offset + chunkBytes);
        const response = await fetch(`${API_BASE}/uploads/${uploadId}`, {
          method: "PATCH",
          headers: {
            ...CLIENT_HEADERS,
            "Upload-Offset": String(offset),
            "Content-Type": "application/offset+octet-stream",
          },
          body,
          credentials: "same-origin",
        });
        const json: unknown = await response.json().catch(() => null);
        if (response.status === 409) {
          // The server has a different offset (e.g. a partial chunk arrived): resume from it.
          const problem = toProblem(409, json);
          const serverOffset = Number(problem.extra?.offset ?? offset);
          return { status: "open", offset: serverOffset };
        }
        if (!response.ok) throw new ApiError(toProblem(response.status, json));
        return json as { status: string; offset: number; error?: string | null };
      },
      () => resyncOffset(uploadId).then((o) => (offset = o ?? offset)),
    );
    offset = last.offset;
    patch(id, { progress: offset / file.size });
    if (last.status !== "open") break;
  }
  return last;
}

async function resyncOffset(uploadId: string): Promise<number | null> {
  try {
    const res = await fetch(`${API_BASE}/uploads/${uploadId}`, { method: "HEAD" });
    return res.ok ? Number(res.headers.get("Upload-Offset")) : null;
  } catch {
    return null;
  }
}

/** Retry transient failures (network errors, 5xx) with exponential backoff. */
async function withRetry<T>(fn: () => Promise<T>, beforeRetry?: () => Promise<unknown>) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn();
    } catch (error) {
      const transient = !(error instanceof ApiError) || error.status >= 500;
      if (!transient || attempt >= MAX_NETWORK_RETRIES) throw error;
      await new Promise((r) => setTimeout(r, Math.min(30_000, 1000 * 2 ** attempt)));
      await beforeRetry?.();
    }
  }
}

/** Waits for the ingestion result. `poll`: fallback for sessions owned by this client. */
function watchProcessing(id: string, uploadId: string, { poll = true } = {}) {
  let settled = false;
  const finish = (changes: Partial<UploadItem>) => {
    if (settled) return;
    settled = true;
    offIngested();
    offFailed();
    if (timer !== undefined) clearInterval(timer);
    patch(id, changes);
  };
  const offIngested = onServerEvent("photo.ingested", (e) => {
    if (e.upload_id !== uploadId) return;
    const status = !e.duplicate ? "done" : e.merged.length > 0 ? "merged" : "duplicate";
    finish({ status, photoId: e.photo_id });
  });
  const offFailed = onServerEvent("photo.ingest_failed", (e) => {
    if (e.upload_id === uploadId) finish({ status: "rejected", errorCode: e.code });
  });
  // Fallback when the event stream was interrupted: a vanished session means ingestion finished.
  const timer = !poll
    ? undefined
    : setInterval(async () => {
        const response = await fetch(`${API_BASE}/uploads/${uploadId}`).catch(() => null);
        if (!response) return;
        if (response.status === 404) {
          const sha = findItem(id)?.sha256;
          const check = sha
            ? await unwrap(api.POST("/api/v1/uploads/check", { body: { sha256: [sha] } })).catch(
                () => null,
              )
            : null;
          const photoId = check?.results[0]?.photo_id ?? undefined;
          finish(
            photoId ? { status: "done", photoId } : { status: "failed", errorCode: "unknown" },
          );
        } else if (response.ok) {
          const body = (await response.json()) as { status: string; error?: string | null };
          if (body.status === "failed") finish({ status: "rejected", errorCode: body.error ?? "" });
        }
      }, PROCESSING_POLL_MS);
}

const findRemote = (sessionId: string, fileId: string) =>
  useUploads.getState().items.find((i) => i.remoteKey === `${sessionId}/${fileId}`);

/** Mirrors LocalSend transfers into the tray (admin clients). Returns an unsubscribe. */
export function mirrorLocalSendTransfers(): () => void {
  const offTransfer = onServerEvent("localsend.transfer", (e) => {
    const items = e.files.map((f): UploadItem => ({
      id: nextId(),
      source: e.alias,
      remoteKey: `${e.session_id}/${f.file_id}`,
      name: f.filename,
      size: f.size,
      status: f.status === "known" ? "duplicate" : f.status === "rejected" ? "rejected" : "queued",
      progress: f.status === "incoming" ? 0 : 1,
      photoId: f.photo_id,
      restored: f.restored,
      errorCode: f.code,
      meta: EMPTY_META,
    }));
    useUploads.setState((state) => ({ items: [...state.items, ...items] }));
  });
  const offFile = onServerEvent("localsend.file", (e) => {
    const item = findRemote(e.session_id, e.file_id);
    if (!item) return;
    switch (e.status) {
      case "receiving":
        patch(item.id, { status: "uploading", progress: 0, errorCode: undefined });
        break;
      case "processing":
        patch(item.id, { status: "processing", progress: 1, uploadId: e.upload_id });
        watchProcessing(item.id, e.upload_id, { poll: false });
        break;
      case "known":
        patch(item.id, {
          status: "duplicate",
          progress: 1,
          photoId: e.photo_id,
          restored: e.restored,
        });
        break;
      case "failed":
        patch(item.id, { status: "failed", errorCode: e.code });
        break;
    }
  });
  const offCancelled = onServerEvent("localsend.cancelled", (e) => {
    useUploads.setState((state) => ({
      items: state.items.map((i) =>
        i.remoteKey?.startsWith(`${e.session_id}/`) && !isFinished(i.status)
          ? { ...i, status: "rejected", errorCode: "localsend_cancelled" }
          : i,
      ),
    }));
  });
  return () => {
    offTransfer();
    offFile();
    offCancelled();
  };
}
