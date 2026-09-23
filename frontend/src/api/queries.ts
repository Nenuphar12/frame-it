import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  api,
  unwrap,
  type Artwork,
  type ArtworkDefaults,
  type FrameStyle,
  type Layout,
  type LayoutDocumentApi,
  type Photo,
  type StyleDocumentApi,
} from "./client";

export const queryKeys = {
  me: ["me"] as const,
  systemInfo: ["system", "info"] as const,
  stats: ["photos", "stats"] as const,
  photos: (filter: PhotoFilter) => ["photos", "list", filter] as const,
  photo: (id: string) => ["photos", "detail", id] as const,
  devices: ["devices"] as const,
  tags: (q: string) => ["tags", q] as const,
  collections: ["collections"] as const,
  localsendStatus: ["localsend", "status"] as const,
  localsendRequests: ["localsend", "requests"] as const,
  localsendDevices: ["localsend", "devices"] as const,
  artworks: (filter: ArtworkFilter) => ["artworks", "list", filter] as const,
  artwork: (id: string) => ["artworks", "detail", id] as const,
  frameStyles: ["templates", "styles"] as const,
  layouts: ["templates", "layouts"] as const,
  recipes: ["templates", "recipes"] as const,
  fonts: ["assets", "fonts"] as const,
  textures: ["assets", "textures"] as const,
  colorPresets: ["colors", "presets"] as const,
  palette: (photoId: string) => ["colors", "palette", photoId] as const,
  swatches: ["colors", "swatches"] as const,
  snapshots: (artworkId: string) => ["artworks", "snapshots", artworkId] as const,
  templateUsage: (kind: TemplateKind, id: string) => ["templates", "usage", kind, id] as const,
  artworkDefaults: ["templates", "defaults"] as const,
};

export interface ArtworkFilter {
  status?: "draft" | "ready";
  favorite?: boolean;
}

export interface PhotoFilter {
  inbox_state?: "inbox" | "processed" | "dismissed";
  q?: string;
  tag_id?: string;
}

export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: () => unwrap(api.GET("/api/v1/system/me")),
    staleTime: 60_000,
  });
}

export function useSystemInfo() {
  return useQuery({
    queryKey: queryKeys.systemInfo,
    queryFn: () => unwrap(api.GET("/api/v1/system/info")),
    staleTime: Infinity,
  });
}

export function useLibraryStats(enabled = true) {
  return useQuery({
    queryKey: queryKeys.stats,
    queryFn: () => unwrap(api.GET("/api/v1/photos/stats")),
    enabled,
  });
}

const PAGE_SIZE = 200;

export function usePhotos(filter: PhotoFilter) {
  return useInfiniteQuery({
    queryKey: queryKeys.photos(filter),
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/photos", {
          params: { query: { ...filter, limit: PAGE_SIZE, cursor: pageParam ?? undefined } },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
  });
}

export function usePhoto(id: string | null) {
  return useQuery({
    queryKey: queryKeys.photo(id ?? ""),
    queryFn: () =>
      unwrap(api.GET("/api/v1/photos/{photo_id}", { params: { path: { photo_id: id! } } })),
    enabled: id !== null,
  });
}

export function useUpdatePhoto() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; tag_ids?: string[]; inbox_state?: Photo["inbox_state"] }) =>
      unwrap(
        api.PATCH("/api/v1/photos/{photo_id}", {
          params: { path: { photo_id: vars.id } },
          body: { tag_ids: vars.tag_ids ?? null, inbox_state: vars.inbox_state ?? null },
        }),
      ),
    onSuccess: (photo) => {
      qc.setQueryData(queryKeys.photo(photo.id), photo);
      void qc.invalidateQueries({ queryKey: ["photos"] });
      void qc.invalidateQueries({ queryKey: ["tags"] });
    },
  });
}

export function useInboxAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ids, action }: { ids: string[]; action: "dismiss" | "restore" }) =>
      unwrap(
        action === "dismiss"
          ? api.POST("/api/v1/inbox/dismiss", { body: { photo_ids: ids } })
          : api.POST("/api/v1/inbox/restore", { body: { photo_ids: ids } }),
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["photos"] }),
  });
}

export function useDevices(refetchInterval: number | false = false) {
  return useQuery({
    queryKey: queryKeys.devices,
    queryFn: () => unwrap(api.GET("/api/v1/devices")),
    refetchInterval,
  });
}

export function useTags(q: string) {
  return useQuery({
    queryKey: queryKeys.tags(q),
    queryFn: () => unwrap(api.GET("/api/v1/tags", { params: { query: { q, limit: 20 } } })),
    placeholderData: keepPreviousData,
  });
}

export function useCreateTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => unwrap(api.POST("/api/v1/tags", { body: { name } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["tags"] }),
  });
}

export function useCollections() {
  return useQuery({
    queryKey: queryKeys.collections,
    queryFn: () => unwrap(api.GET("/api/v1/collections")),
  });
}

export function useLocalSendStatus() {
  return useQuery({
    queryKey: queryKeys.localsendStatus,
    queryFn: () => unwrap(api.GET("/api/v1/localsend/status")),
  });
}

export function useLocalSendRequests(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.localsendRequests,
    queryFn: () => unwrap(api.GET("/api/v1/localsend/requests")),
    enabled,
  });
}

export function useLocalSendDecision() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) =>
      unwrap(
        api.POST("/api/v1/localsend/requests/{request_id}/decision", {
          params: { path: { request_id: id } },
          body: { approve },
        }),
      ),
    onSettled: () => void qc.invalidateQueries({ queryKey: ["localsend"] }),
  });
}

export function useLocalSendDevices() {
  return useQuery({
    queryKey: queryKeys.localsendDevices,
    queryFn: () => unwrap(api.GET("/api/v1/localsend/devices")),
  });
}

export function useLocalSendDeviceActions() {
  const qc = useQueryClient();
  const onSuccess = () => void qc.invalidateQueries({ queryKey: ["localsend"] });
  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "approved" | "blocked" }) =>
      unwrap(
        api.PATCH("/api/v1/localsend/devices/{device_id}", {
          params: { path: { device_id: id } },
          body: { status },
        }),
      ),
    onSuccess,
  });
  const forget = useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/api/v1/localsend/devices/{device_id}", {
          params: { path: { device_id: id } },
        }),
      ),
    onSuccess,
  });
  return { setStatus, forget };
}

export function useArtworks(filter: ArtworkFilter) {
  return useInfiniteQuery({
    queryKey: queryKeys.artworks(filter),
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/artworks", {
          params: { query: { ...filter, limit: PAGE_SIZE, cursor: pageParam ?? undefined } },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
  });
}

export function useArtwork(id: string | null) {
  return useQuery({
    queryKey: queryKeys.artwork(id ?? ""),
    queryFn: () =>
      unwrap(api.GET("/api/v1/artworks/{artwork_id}", { params: { path: { artwork_id: id! } } })),
    enabled: id !== null,
  });
}

export function useFrameStyles() {
  return useQuery({
    queryKey: queryKeys.frameStyles,
    queryFn: () => unwrap(api.GET("/api/v1/frame-styles")),
    staleTime: 60_000,
  });
}

export function useLayouts() {
  return useQuery({
    queryKey: queryKeys.layouts,
    queryFn: () => unwrap(api.GET("/api/v1/layouts")),
    staleTime: 60_000,
  });
}

/** The bundled composition catalogue (§6.3): static, so it never goes stale. */
export function useRecipes() {
  return useQuery({
    queryKey: queryKeys.recipes,
    queryFn: () => unwrap(api.GET("/api/v1/recipes")),
    staleTime: Infinity,
  });
}

export interface CreateArtworksInput {
  /** One artwork per group, photos in slot order. */
  groups: string[][];
  style_id: string;
  /** A saved layout (docs/templates.md §4): its recipe and parameters, recorded as the origin. */
  layout_id?: string;
  /** Parametric layout (docs/simple-editor.md §7); omitted ⇒ the recipe for the photo count. */
  composition?: { recipe?: string; format?: string };
}

/** Creates artworks one request at a time (keeps render jobs and SQLite writes sequential). */
export function useCreateArtworks() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ groups, ...options }: CreateArtworksInput) => {
      const created: Artwork[] = [];
      for (const photo_ids of groups) {
        created.push(
          await unwrap(api.POST("/api/v1/artworks", { body: { photo_ids, ...options } })),
        );
      }
      return created;
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["artworks"] });
      void qc.invalidateQueries({ queryKey: ["photos"] });
    },
  });
}

export function useArtworkActions() {
  const qc = useQueryClient();
  const onSuccess = (artwork?: Artwork) => {
    if (artwork) qc.setQueryData(queryKeys.artwork(artwork.id), artwork);
    void qc.invalidateQueries({ queryKey: ["artworks", "list"] });
  };
  const path = (id: string) => ({ params: { path: { artwork_id: id } } });
  const update = useMutation({
    mutationFn: ({
      id,
      ...body
    }: {
      id: string;
      favorite?: boolean;
      title?: string;
      status?: "draft";
      tag_ids?: string[];
      origin_style_id?: string;
      origin_layout_id?: string;
    }) => unwrap(api.PATCH("/api/v1/artworks/{artwork_id}", { ...path(id), body })),
    onSuccess,
  });
  const validate = useMutation({
    mutationFn: (id: string) =>
      unwrap(api.POST("/api/v1/artworks/{artwork_id}/validate", path(id))),
    onSuccess,
  });
  const duplicate = useMutation({
    mutationFn: (id: string) =>
      unwrap(api.POST("/api/v1/artworks/{artwork_id}/duplicate", path(id))),
    onSuccess,
  });
  const trash = useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/v1/artworks/{artwork_id}", path(id))),
    onSuccess: () => onSuccess(),
  });
  return { update, validate, duplicate, trash };
}

// ---- editor: assets, colours, snapshots (Phase 5) ----------------------------------------------

export function useFonts() {
  return useQuery({
    queryKey: queryKeys.fonts,
    queryFn: () => unwrap(api.GET("/api/v1/fonts")),
    staleTime: Infinity,
  });
}

export function useTextures() {
  return useQuery({
    queryKey: queryKeys.textures,
    queryFn: () => unwrap(api.GET("/api/v1/textures")),
    staleTime: Infinity,
  });
}

export function useColorPresets() {
  return useQuery({
    queryKey: queryKeys.colorPresets,
    queryFn: () => unwrap(api.GET("/api/v1/presets/colors")),
    staleTime: Infinity,
  });
}

/** Mat colours suggested from a photo (server-side k-means, cached there too). */
export function usePhotoPalette(photoId: string | null) {
  return useQuery({
    queryKey: queryKeys.palette(photoId ?? ""),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/photos/{photo_id}/palette", {
          params: { path: { photo_id: photoId! } },
        }),
      ),
    enabled: photoId !== null,
    staleTime: Infinity,
  });
}

export function useSwatches() {
  return useQuery({
    queryKey: queryKeys.swatches,
    queryFn: () => unwrap(api.GET("/api/v1/swatches")),
  });
}

export function useSwatchActions() {
  const qc = useQueryClient();
  const onSuccess = () => void qc.invalidateQueries({ queryKey: queryKeys.swatches });
  const create = useMutation({
    mutationFn: (vars: { color: string; name?: string }) =>
      unwrap(api.POST("/api/v1/swatches", { body: { color: vars.color, name: vars.name ?? "" } })),
    onSuccess,
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/v1/swatches/{swatch_id}", { params: { path: { swatch_id: id } } })),
    onSuccess,
  });
  return { create, remove };
}

export function useSnapshots(artworkId: string | null) {
  return useQuery({
    queryKey: queryKeys.snapshots(artworkId ?? ""),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/artworks/{artwork_id}/snapshots", {
          params: { path: { artwork_id: artworkId! } },
        }),
      ),
    enabled: artworkId !== null,
  });
}

export function useRestoreSnapshot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { artworkId: string; snapshotId: string }) =>
      unwrap(
        api.POST("/api/v1/artworks/{artwork_id}/snapshots/{snapshot_id}/restore", {
          params: { path: { artwork_id: vars.artworkId, snapshot_id: vars.snapshotId } },
        }),
      ),
    onSuccess: (artwork) => {
      qc.setQueryData(queryKeys.artwork(artwork.id), artwork);
      void qc.invalidateQueries({ queryKey: ["artworks"] });
    },
  });
}

// ---- templates (docs/templates.md) --------------------------------------------------------------
export type TemplateKind = "frame_style" | "layout";

/** A template row, whichever kind it is (the two lists share every management action). */
export type Template = FrameStyle | Layout;

/** Every template mutation invalidates both lists: a "save as" can come from either page. */
function useTemplateMutation<TVariables>(
  mutationFn: (variables: TVariables) => Promise<Template | undefined>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["templates"] });
    },
  });
}

export interface StyleInput {
  name: string;
  document: StyleDocumentApi;
}

export interface LayoutInput {
  name: string;
  document: LayoutDocumentApi;
}

export function useCreateStyle() {
  return useTemplateMutation((body: StyleInput) =>
    unwrap(api.POST("/api/v1/frame-styles", { body })),
  );
}

export function useCreateLayout() {
  return useTemplateMutation((body: LayoutInput) => unwrap(api.POST("/api/v1/layouts", { body })));
}

export function useUpdateStyle() {
  return useTemplateMutation(({ id, ...body }: { id: string } & Partial<StyleInput>) =>
    unwrap(
      api.PATCH("/api/v1/frame-styles/{style_id}", { params: { path: { style_id: id } }, body }),
    ),
  );
}

export function useUpdateLayout() {
  return useTemplateMutation(({ id, ...body }: { id: string } & Partial<LayoutInput>) =>
    unwrap(api.PATCH("/api/v1/layouts/{layout_id}", { params: { path: { layout_id: id } }, body })),
  );
}

export function useDuplicateTemplate() {
  return useTemplateMutation(
    ({ kind, id }: { kind: TemplateKind; id: string }): Promise<Template> =>
      kind === "frame_style"
        ? unwrap(
            api.POST("/api/v1/frame-styles/{style_id}/duplicate", {
              params: { path: { style_id: id } },
              body: { name: null },
            }),
          )
        : unwrap(
            api.POST("/api/v1/layouts/{layout_id}/duplicate", {
              params: { path: { layout_id: id } },
              body: { name: null },
            }),
          ),
  );
}

export function useDeleteTemplate() {
  return useTemplateMutation(({ kind, id }: { kind: TemplateKind; id: string }) =>
    kind === "frame_style"
      ? unwrap(
          api.DELETE("/api/v1/frame-styles/{style_id}", { params: { path: { style_id: id } } }),
        )
      : unwrap(api.DELETE("/api/v1/layouts/{layout_id}", { params: { path: { layout_id: id } } })),
  );
}

/** "Save as style" / "Save as layout" from an artwork (docs/templates.md §3). */
export function useSaveAsTemplate() {
  return useTemplateMutation(
    ({
      kind,
      artworkId,
      name,
    }: {
      kind: TemplateKind;
      artworkId: string;
      name: string;
    }): Promise<Template> => {
      const body = { artwork_id: artworkId, name };
      return kind === "frame_style"
        ? unwrap(api.POST("/api/v1/frame-styles/from-artwork", { body }))
        : unwrap(api.POST("/api/v1/layouts/from-artwork", { body }));
    },
  );
}

/** Import a `.tfstyle.json` / `.tflayout.json` file the browser has read (§6). */
export function useImportTemplate() {
  return useTemplateMutation(
    ({ kind, file }: { kind: TemplateKind; file: Record<string, unknown> }): Promise<Template> => {
      const body = file as { kind: string; version: number; document: Record<string, unknown> };
      return kind === "frame_style"
        ? unwrap(api.POST("/api/v1/frame-styles/import", { body }))
        : unwrap(api.POST("/api/v1/layouts/import", { body }));
    },
  );
}

export function useTemplateUsage(kind: TemplateKind, id: string | null) {
  return useQuery({
    queryKey: queryKeys.templateUsage(kind, id ?? ""),
    queryFn: () =>
      kind === "frame_style"
        ? unwrap(
            api.GET("/api/v1/frame-styles/{style_id}/usage", {
              params: { path: { style_id: id! } },
            }),
          )
        : unwrap(
            api.GET("/api/v1/layouts/{layout_id}/usage", { params: { path: { layout_id: id! } } }),
          ),
    enabled: id !== null,
  });
}

/** Preview (dry run) or apply a push update; applying re-renders every touched artwork. */
export function usePushUpdate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, id, dryRun }: { kind: TemplateKind; id: string; dryRun: boolean }) => {
      const suffix = dryRun ? "/push-update/preview" : "/push-update";
      return kind === "frame_style"
        ? unwrap(
            api.POST(
              `/api/v1/frame-styles/{style_id}${suffix}` as "/api/v1/frame-styles/{style_id}/push-update",
              {
                params: { path: { style_id: id } },
              },
            ),
          )
        : unwrap(
            api.POST(
              `/api/v1/layouts/{layout_id}${suffix}` as "/api/v1/layouts/{layout_id}/push-update",
              {
                params: { path: { layout_id: id } },
              },
            ),
          );
    },
    onSuccess: (_result, variables) => {
      if (variables.dryRun) return;
      void qc.invalidateQueries({ queryKey: ["artworks"] });
      void qc.invalidateQueries({ queryKey: ["templates"] });
    },
  });
}

/** Apply a template to one artwork, server-side (copy + origin, snapshotted). */
export function useApplyTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      artworkId,
      styleId,
      layoutId,
    }: {
      artworkId: string;
      styleId?: string;
      layoutId?: string;
    }) =>
      unwrap(
        api.POST("/api/v1/artworks/{artwork_id}/apply-template", {
          params: { path: { artwork_id: artworkId } },
          body: { style_id: styleId ?? null, layout_id: layoutId ?? null },
        }),
      ),
    onSuccess: (artwork) => {
      qc.setQueryData(queryKeys.artwork(artwork.id), artwork);
      void qc.invalidateQueries({ queryKey: ["artworks"] });
    },
  });
}

export function useArtworkDefaults() {
  return useQuery({
    queryKey: queryKeys.artworkDefaults,
    queryFn: () => unwrap(api.GET("/api/v1/artwork-defaults")),
    staleTime: 60_000,
  });
}

export function useSetArtworkDefaults() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ArtworkDefaults) => unwrap(api.PUT("/api/v1/artwork-defaults", { body })),
    onSuccess: (defaults) => qc.setQueryData(queryKeys.artworkDefaults, defaults),
  });
}

/** Details of several photos at once (the editor needs their pixel sizes for the geometry). */
export function usePhotosByIds(ids: string[]) {
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKeys.photo(id),
      queryFn: () =>
        unwrap(api.GET("/api/v1/photos/{photo_id}", { params: { path: { photo_id: id } } })),
      staleTime: 60_000,
    })),
    combine: (results) => ({
      photos: results.flatMap((result) => (result.data ? [result.data] : [])),
      isLoading: results.some((result) => result.isLoading),
    }),
  });
}
