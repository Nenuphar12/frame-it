// Sending an archive to `POST /imports` + `PATCH /imports/{id}` (docs/archive-format.md §12.2).
//
// The same `Upload-Offset` protocol as photo uploads, but an archive is one big file and the
// interesting state (staging, the report) lives on the server afterwards — so this is a plain
// async function with a progress callback rather than a queue: `openapi-fetch` is JSON-only, and
// a chunked body needs `fetch` directly.
import { ApiError, API_BASE, CLIENT_HEADERS, toProblem } from "@/api/client";

const MAX_RETRIES = 3;

interface Session {
  import_id: string;
  offset: number;
  size: number;
  chunk_bytes: number;
}

async function json<T>(response: Response): Promise<T> {
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(toProblem(response.status, body));
  return body as T;
}

/** Open a staging slot, send the file in chunks, and return the import id once it is all there. */
export async function uploadArchive(
  file: File,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<string> {
  const created = await fetch(`${API_BASE}/imports`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...CLIENT_HEADERS },
    body: JSON.stringify({ filename: file.name, size: file.size }),
    signal,
  });
  const session = await json<Session>(created);
  let offset = session.offset;
  const chunk = session.chunk_bytes;
  while (offset < file.size) {
    const next = await sendChunk(session.import_id, file, offset, chunk, signal);
    offset = next;
    onProgress(offset / file.size);
  }
  return session.import_id;
}

async function sendChunk(
  importId: string,
  file: File,
  offset: number,
  chunkBytes: number,
  signal?: AbortSignal,
): Promise<number> {
  for (let attempt = 0; ; attempt++) {
    try {
      const response = await fetch(`${API_BASE}/imports/${importId}`, {
        method: "PATCH",
        credentials: "same-origin",
        headers: {
          ...CLIENT_HEADERS,
          "Upload-Offset": String(offset),
          "Content-Type": "application/offset+octet-stream",
        },
        body: file.slice(offset, offset + chunkBytes),
        signal,
      });
      const body: unknown = await response.json().catch(() => null);
      if (response.status === 409) {
        // The server committed a different offset (a partial chunk arrived): resume from it.
        return Number(toProblem(409, body).extra?.offset ?? offset);
      }
      if (!response.ok) throw new ApiError(toProblem(response.status, body));
      return (body as Session).offset;
    } catch (error) {
      const transient = !(error instanceof ApiError) || error.status >= 500;
      if (!transient || attempt >= MAX_RETRIES) throw error;
      await new Promise((resolve) => setTimeout(resolve, 1000 * 2 ** attempt));
    }
  }
}
