import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Photo = Schemas["PhotoOut"];
export type Device = Schemas["DeviceOut"];
export type Me = Schemas["Me"];
export type Tag = Schemas["TagOut"];
export type TagWithCount = Schemas["TagWithCount"];
export type Collection = Schemas["CollectionOut"];
export type CollectionKind = Collection["kind"];
export type ArtworkSort = NonNullable<Schemas["ArtworkQueryIn"]["sort"]>;
export type TrashListing = Schemas["TrashOut"];
export type TrashedPhoto = Schemas["TrashedPhotoOut"];
export type TrashedArtwork = Schemas["TrashedArtworkOut"];
export type AffectedArtwork = Schemas["AffectedArtworkOut"];
export type TrashCascade = Schemas["TrashPhotosIn"]["cascade"];
export type UploadOut = Schemas["UploadOut"];
export type LocalSendDevice = Schemas["LocalSendDeviceOut"];
export type LocalSendRequest = Schemas["LocalSendRequestOut"];
export type Artwork = Schemas["ArtworkOut"];
export type ArtworkSummary = Schemas["ArtworkSummaryOut"];
export type ArtworkDocument = Schemas["ArtworkDocument"];
export type FrameStyle = Schemas["FrameStyleOut"];
export type Layout = Schemas["LayoutOut"];
export type ApiRecipe = Schemas["RecipeOut"];
export type StyleDocumentApi = Schemas["FrameStyleDocument"];
export type LayoutDocumentApi = Schemas["LayoutDocument"];
export type TemplateFile = Schemas["TemplateFileOut"];
export type PushUpdate = Schemas["PushUpdateOut"];
export type ArtworkDefaults = Schemas["ArtworkDefaultsOut"];
export type Font = Schemas["FontOut"];
export type Texture = Schemas["TextureOut"];
export type Swatch = Schemas["SwatchOut"];
export type PaletteEntry = Schemas["PaletteEntryOut"];
export type ColorPreset = Schemas["ColorPresetOut"];
export type Snapshot = Schemas["SnapshotOut"];
export type DisplayTarget = Schemas["DisplayTargetOut"];
export type DisplayStatus = Schemas["DisplayStatusOut"];
export type DisplayCapabilities = Schemas["DisplayCapabilitiesOut"];
export type DisplaySource = Schemas["DisplaySourceIn"];
export type ExportJob = Schemas["ExportOut"];
export type ExportRequest = Schemas["ExportRequestIn"];
export type ImportSession = Schemas["ImportSessionOut"];
export type ImportReport = Schemas["ImportReportOut"];
export type ImportKindReport = Schemas["ImportKindOut"];
export type ImportEntry = Schemas["ImportEntryOut"];
export type ImportPolicy = Schemas["ImportPoliciesIn"]["default"];
export type ImportResult = Schemas["ImportApplyOut"];

export const API_BASE = "/api/v1";
/** Required on every mutating request (CSRF guard, see docs/security.md). */
export const CLIENT_HEADERS = { "X-TF-Client": "1" } as const;

export interface Problem {
  code: string;
  title: string;
  status: number;
  detail?: string;
  extra?: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.detail ?? problem.title);
    this.problem = problem;
  }

  get code(): string {
    return this.problem.code;
  }

  get status(): number {
    return this.problem.status;
  }
}

export function toProblem(status: number, body: unknown): Problem {
  if (body && typeof body === "object" && "code" in body) {
    return body as Problem;
  }
  return { code: status === 0 ? "network_error" : "http_error", title: "Request failed", status };
}

const clientHeaders: Middleware = {
  onRequest({ request }) {
    request.headers.set("X-TF-Client", "1");
    return request;
  },
};

export const api = createClient<paths>({ baseUrl: "", credentials: "same-origin" });
api.use(clientHeaders);

/** Unwrap an openapi-fetch result, throwing `ApiError` on failure. */
export async function unwrap<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await promise;
  if (!response.ok || error !== undefined) {
    throw new ApiError(toProblem(response.status, error));
  }
  return data as T;
}

/** The finished archive: a plain download, so the browser streams it straight to disk. */
export const exportDownloadUrl = (jobId: string) => `${API_BASE}/exports/${jobId}/download`;

export const photoThumbUrl = (id: string, size: 256 | 768 = 768) =>
  `${API_BASE}/photos/${id}/thumb/${size}`;
export const photoProxyUrl = (id: string) => `${API_BASE}/photos/${id}/proxy`;
export const photoOriginalUrl = (id: string) => `${API_BASE}/photos/${id}/original`;

/** Render URLs carry the render hash: cached forever once rendered, revalidated while pending. */
const renderVersion = (a: Pick<ArtworkSummary, "render_hash" | "document_version">) =>
  a.render_hash ?? `pending-${a.document_version}`;
export const artworkThumbUrl = (
  a: Pick<ArtworkSummary, "id" | "render_hash" | "document_version">,
  size: 256 | 768 = 768,
) => `${API_BASE}/artworks/${a.id}/thumb/${size}?v=${renderVersion(a)}`;
export const artworkRenderUrl = (
  a: Pick<ArtworkSummary, "id" | "render_hash" | "document_version">,
  format: "png" | "jpg",
) => `${API_BASE}/artworks/${a.id}/render.${format}?v=${renderVersion(a)}`;

/**
 * Region of the *current, possibly unsaved* document rendered by the server (loupe, §11.4).
 * Returns a PNG blob: `openapi-fetch` is JSON-only, so this one endpoint uses `fetch` directly.
 */
export async function renderRegion(
  document: ArtworkDocument,
  rect: { x: number; y: number; w: number; h: number },
  signal?: AbortSignal,
): Promise<Blob> {
  const response = await fetch(`${API_BASE}/render/region`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...CLIENT_HEADERS },
    body: JSON.stringify({ document, rect }),
    signal,
  });
  if (!response.ok) {
    throw new ApiError(toProblem(response.status, await response.json().catch(() => null)));
  }
  return response.blob();
}
