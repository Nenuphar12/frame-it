import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import type { ChipFilter, FilterGroup } from "@/features/library/filters";
import { asJson, toGroup } from "@/features/library/filters";

import {
  api,
  unwrap,
  type Artwork,
  type ArtworkDefaults,
  type ArtworkSort,
  type CollectionKind,
  type DisplaySource,
  type FrameStyle,
  type Layout,
  type LayoutDocumentApi,
  type Photo,
  type ExportRequest,
  type ImportPolicy,
  type Schemas,
  type StyleDocumentApi,
  type TagSort,
  type TrashCascade,
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
  collection: (id: string) => ["collections", "detail", id] as const,
  trash: ["trash"] as const,
  jobs: (states: readonly string[]) => ["jobs", states] as const,
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
  displayTargets: ["display", "targets"] as const,
  displayStatus: (id: string) => ["display", "status", id] as const,
  displayCapabilities: ["display", "capabilities"] as const,
  displayDiscover: ["display", "discover"] as const,
  displayPlan: (id: string, body: unknown) => ["display", "plan", id, body] as const,
  templateUsage: (kind: TemplateKind, id: string) => ["templates", "usage", kind, id] as const,
  artworkDefaults: ["templates", "defaults"] as const,
  exports: ["archive", "exports"] as const,
  imports: ["archive", "imports"] as const,
  importSession: (id: string) => ["archive", "imports", id] as const,
  importReport: (id: string) => ["archive", "imports", id, "report"] as const,
};

export interface ArtworkFilter {
  status?: "draft" | "ready";
  favorite?: boolean;
  collection_id?: string;
  include_nested?: boolean;
  photo_id?: string;
  q?: string;
  sort?: ArtworkSort;
  /** The filter bar's chips (docs/data-model.md §5.2); sent as an AST to `POST /artworks/query`. */
  chips?: ChipFilter;
}

export interface PhotoFilter {
  inbox_state?: "inbox" | "processed" | "dismissed";
  q?: string;
  tag_id?: string;
  /** A photo id: only the photos taken in the same few days, or at the same spot. */
  around?: string;
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
      invalidatePhotoTags(qc);
    },
  });
}

/**
 * A photo's tags changed: the artworks made of it carry them too (docs/organization.md §1), so
 * their lists, the smart collections matching on a tag and the counts all move with it.
 */
function invalidatePhotoTags(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ["photos"] });
  void qc.invalidateQueries({ queryKey: ["artworks"] });
  void qc.invalidateQueries({ queryKey: ["tags"] });
  void qc.invalidateQueries({ queryKey: ["collections"] });
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

/**
 * Tags matching `q`. The autocomplete asks for a handful in `recent` order (what you tagged with a
 * minute ago comes first); the manager, the filters and the tag menu ask for all of them.
 */
export function useTags(q: string, options: { sort?: TagSort; limit?: number } = {}) {
  const sort = options.sort ?? "usage";
  const limit = options.limit ?? 20;
  return useQuery({
    queryKey: [...queryKeys.tags(q), sort, limit] as const,
    queryFn: () => unwrap(api.GET("/api/v1/tags", { params: { query: { q, limit, sort } } })),
    placeholderData: keepPreviousData,
  });
}

/** Every tag (the server caps a page at 500), alphabetical — for lists rather than suggestions. */
export function useAllTags() {
  return useTags("", { sort: "name", limit: 500 });
}

export function useCreateTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: string | { name: string; category_id?: string | null }) =>
      unwrap(
        api.POST("/api/v1/tags", {
          body: typeof vars === "string" ? { name: vars } : vars,
        }),
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["tags"] }),
  });
}

export function useCollections() {
  return useQuery({
    queryKey: queryKeys.collections,
    queryFn: () => unwrap(api.GET("/api/v1/collections")),
  });
}

/** Every collection mutation refreshes the tree *and* the lists a collection can filter. */
function useCollectionMutation<TVariables, TResult>(
  mutationFn: (variables: TVariables) => Promise<TResult>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["collections"] });
      void qc.invalidateQueries({ queryKey: ["artworks", "list"] });
    },
  });
}

export interface CollectionInput {
  name: string;
  parent_id?: string | null;
  kind?: CollectionKind;
  description?: string;
  filter?: FilterGroup | null;
}

export function useCreateCollection() {
  return useCollectionMutation((body: CollectionInput) =>
    unwrap(
      api.POST("/api/v1/collections", {
        body: {
          name: body.name,
          parent_id: body.parent_id ?? null,
          kind: body.kind ?? "manual",
          description: body.description ?? "",
          filter: asJson(body.filter) ?? null,
        },
      }),
    ),
  );
}

export interface CollectionPatch {
  id: string;
  name?: string;
  description?: string;
  date_start?: string;
  date_end?: string;
  /** An artwork id, or `""` to clear the cover. */
  cover_artwork_id?: string;
  filter?: FilterGroup;
}

export function useUpdateCollection() {
  return useCollectionMutation(({ id, filter, ...rest }: CollectionPatch) =>
    unwrap(
      api.PATCH("/api/v1/collections/{collection_id}", {
        params: { path: { collection_id: id } },
        body: { ...rest, filter: asJson(filter) ?? null },
      }),
    ),
  );
}

/** Drag and drop in the tree: a new parent and the sibling to land before (cycles are a 422). */
export function useMoveCollection() {
  return useCollectionMutation(
    (vars: { id: string; parent_id: string | null; before_id?: string | null }) =>
      unwrap(
        api.POST("/api/v1/collections/{collection_id}/move", {
          params: { path: { collection_id: vars.id } },
          body: { parent_id: vars.parent_id, before_id: vars.before_id ?? null },
        }),
      ),
  );
}

export function useDeleteCollection() {
  return useCollectionMutation((id: string) =>
    unwrap(
      api.DELETE("/api/v1/collections/{collection_id}", {
        params: { path: { collection_id: id } },
      }),
    ),
  );
}

export function useCollectionItems() {
  const add = useCollectionMutation((vars: { id: string; artwork_ids: string[] }) =>
    unwrap(
      api.POST("/api/v1/collections/{collection_id}/items", {
        params: { path: { collection_id: vars.id } },
        body: { artwork_ids: vars.artwork_ids },
      }),
    ),
  );
  const remove = useCollectionMutation((vars: { id: string; artwork_ids: string[] }) =>
    unwrap(
      api.POST("/api/v1/collections/{collection_id}/items/remove", {
        params: { path: { collection_id: vars.id } },
        body: { artwork_ids: vars.artwork_ids },
      }),
    ),
  );
  const reorder = useCollectionMutation(
    (vars: { id: string; artwork_id: string; before_id: string | null }) =>
      unwrap(
        api.POST("/api/v1/collections/{collection_id}/reorder", {
          params: { path: { collection_id: vars.id } },
          body: { artwork_id: vars.artwork_id, before_id: vars.before_id },
        }),
      ),
  );
  return { add, remove, reorder };
}

/** Live count for the smart-collection editor: "matches 12 artworks", or why it does not. */
export function useValidateFilter(filter: FilterGroup | undefined) {
  return useQuery({
    queryKey: ["filters", "validate", filter],
    queryFn: () =>
      unwrap(
        api.POST("/api/v1/filters/validate", {
          body: { filter: asJson(filter) ?? { op: "and", clauses: [] } },
        }),
      ),
    enabled: filter !== undefined,
    placeholderData: keepPreviousData,
  });
}

// ---- tag manager (docs/organization.md §1) ------------------------------------------------------

function useTagMutation<TVariables, TResult>(
  mutationFn: (variables: TVariables) => Promise<TResult>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tags"] });
      void qc.invalidateQueries({ queryKey: ["photos"] });
      void qc.invalidateQueries({ queryKey: ["artworks"] });
      // a smart collection matching on a tag changes size when the tag is merged or deleted
      void qc.invalidateQueries({ queryKey: ["collections"] });
    },
  });
}

/** `category_id`: a category, `null` for "Other", absent to leave it alone. */
export function useUpdateTag() {
  return useTagMutation(
    ({ id, ...body }: { id: string; name?: string; color?: string; category_id?: string | null }) =>
      unwrap(api.PATCH("/api/v1/tags/{tag_id}", { params: { path: { tag_id: id } }, body })),
  );
}

/** Move every use of `source_ids` onto `id`; the sources disappear, duplicate links collapse. */
export function useMergeTags() {
  return useTagMutation((vars: { id: string; source_ids: string[] }) =>
    unwrap(
      api.POST("/api/v1/tags/{tag_id}/merge", {
        params: { path: { tag_id: vars.id } },
        body: { source_ids: vars.source_ids },
      }),
    ),
  );
}

export function useDeleteTag() {
  return useTagMutation((id: string) =>
    unwrap(api.DELETE("/api/v1/tags/{tag_id}", { params: { path: { tag_id: id } } })),
  );
}

/** Move many tags into one category (`null` ⇒ "Other"). */
export function useCategorizeTags() {
  return useTagMutation((vars: { tag_ids: string[]; category_id: string | null }) =>
    unwrap(api.POST("/api/v1/tags/categorize", { body: vars })),
  );
}

/** Tags attached to nothing at all (trashed rows count as a use). */
export function useUnusedTags() {
  return useQuery({
    queryKey: ["tags", "unused"] as const,
    queryFn: () => unwrap(api.GET("/api/v1/tags/unused")),
  });
}

export function useDeleteUnusedTags() {
  return useTagMutation(() => unwrap(api.POST("/api/v1/tags/delete-unused")));
}

/** Categories live under `["tags"]`, so every tag mutation refreshes them too. */
export function useTagCategories() {
  return useQuery({
    queryKey: ["tags", "categories"] as const,
    queryFn: () => unwrap(api.GET("/api/v1/tag-categories")),
    staleTime: 60_000,
  });
}

export function useTagCategoryActions() {
  const create = useTagMutation((body: { name: string; color?: string | null }) =>
    unwrap(api.POST("/api/v1/tag-categories", { body })),
  );
  const update = useTagMutation(({ id, ...body }: { id: string; name?: string; color?: string }) =>
    unwrap(
      api.PATCH("/api/v1/tag-categories/{category_id}", {
        params: { path: { category_id: id } },
        body,
      }),
    ),
  );
  const remove = useTagMutation((id: string) =>
    unwrap(
      api.DELETE("/api/v1/tag-categories/{category_id}", {
        params: { path: { category_id: id } },
      }),
    ),
  );
  return { create, update, remove };
}

/**
 * Bulk tagging (docs/organization.md §1): additive `add` / `remove`, never a replacement. On
 * artworks, `remove` only reaches their own tags — an inherited one belongs to a photo.
 */
export function useBulkTags() {
  const qc = useQueryClient();
  const photos = useMutation({
    mutationFn: (vars: { photo_ids: string[]; add?: string[]; remove?: string[] }) =>
      unwrap(
        api.POST("/api/v1/photos/tags", {
          body: { photo_ids: vars.photo_ids, add: vars.add ?? [], remove: vars.remove ?? [] },
        }),
      ),
    onSuccess: () => invalidatePhotoTags(qc),
  });
  const artworks = useMutation({
    mutationFn: (vars: { artwork_ids: string[]; add?: string[]; remove?: string[] }) =>
      unwrap(
        api.POST("/api/v1/artworks/tags", {
          body: { artwork_ids: vars.artwork_ids, add: vars.add ?? [], remove: vars.remove ?? [] },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["artworks"] });
      void qc.invalidateQueries({ queryKey: ["tags"] });
      void qc.invalidateQueries({ queryKey: ["collections"] });
    },
  });
  return { photos, artworks };
}

/** Where the photos were taken — derived from their metadata, read-only. */
export function usePlaces() {
  return useQuery({
    queryKey: ["photos", "places"] as const,
    queryFn: () => unwrap(api.GET("/api/v1/places")),
  });
}

/** The `place near` picker: places of the offline dataset by name, the library's own first. */
export function usePlaceSearch(q: string) {
  return useQuery({
    queryKey: ["places-search", q] as const,
    queryFn: () => unwrap(api.GET("/api/v1/places/search", { params: { query: { q } } })),
    enabled: q.length > 0,
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  });
}

// ---- trash (docs/organization.md §5) ------------------------------------------------------------

export function useTrash(enabled = true) {
  return useQuery({
    queryKey: queryKeys.trash,
    queryFn: () => unwrap(api.GET("/api/v1/trash")),
    enabled,
  });
}

function useTrashMutation<TVariables, TResult>(
  mutationFn: (variables: TVariables) => Promise<TResult>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["trash"] });
      void qc.invalidateQueries({ queryKey: ["photos"] });
      void qc.invalidateQueries({ queryKey: ["artworks"] });
      void qc.invalidateQueries({ queryKey: ["collections"] });
    },
  });
}

/** What deleting these photos would do to the artworks using them (the cascade dialog). */
export function useTrashPreview(photoIds: string[]) {
  return useQuery({
    queryKey: ["trash", "preview", photoIds],
    queryFn: () => unwrap(api.POST("/api/v1/trash/preview", { body: { photo_ids: photoIds } })),
    enabled: photoIds.length > 0,
  });
}

export function useTrashActions() {
  const photos = useTrashMutation((vars: { photo_ids: string[]; cascade: TrashCascade }) =>
    unwrap(api.POST("/api/v1/trash/photos", { body: vars })),
  );
  const artworks = useTrashMutation((artwork_ids: string[]) =>
    unwrap(api.POST("/api/v1/trash/artworks", { body: { artwork_ids } })),
  );
  const restore = useTrashMutation(
    (vars: { photo_ids?: string[]; artwork_ids?: string[]; batch_ids?: string[] }) =>
      unwrap(
        api.POST("/api/v1/trash/restore", {
          body: {
            photo_ids: vars.photo_ids ?? [],
            artwork_ids: vars.artwork_ids ?? [],
            batch_ids: vars.batch_ids ?? [],
          },
        }),
      ),
  );
  const purge = useTrashMutation((all: boolean) =>
    unwrap(api.POST("/api/v1/trash/purge", { body: { all } })),
  );
  return { photos, artworks, restore, purge };
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

/**
 * One page of artworks. Everything goes through `POST /artworks/query`: the filter bar sends an
 * AST, and a smart collection *is* one, so both take the same path as a plain list.
 */
export function useArtworks(filter: ArtworkFilter, options: { enabled?: boolean } = {}) {
  const { chips, ...rest } = filter;
  const body = {
    ...rest,
    include_nested: filter.include_nested ?? false,
    sort: filter.sort ?? "created_desc",
    filter: asJson(toGroup(chips ?? [])),
  };
  return useInfiniteQuery({
    queryKey: queryKeys.artworks(filter),
    queryFn: ({ pageParam }) =>
      unwrap(
        api.POST("/api/v1/artworks/query", {
          body: { ...body, limit: PAGE_SIZE, cursor: pageParam ?? undefined },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
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
    meta: { silentError: true }, // the create dialog keeps the reason under its button
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
    // An artwork's tags, favourite, status… are what smart collections match on, and the tree's
    // counts and the tag counts live in their own queries (user feedback).
    void qc.invalidateQueries({ queryKey: ["collections"] });
    void qc.invalidateQueries({ queryKey: ["tags"] });
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
    // The templates page and both editors render the failure under the form it came from.
    meta: { silentError: true },
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

// ---- export / import (docs/archive-format.md) --------------------------------------------------

/** Export jobs, newest first. Polled while one is running: the file appears when it is done. */
export function useExports() {
  return useQuery({
    queryKey: queryKeys.exports,
    queryFn: () => unwrap(api.GET("/api/v1/exports")),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((job) => job.state === "queued" || job.state === "running")
        ? 1000
        : false,
  });
}

export function useExportActions() {
  const qc = useQueryClient();
  const invalidate = () => void qc.invalidateQueries({ queryKey: queryKeys.exports });
  const start = useMutation({
    mutationFn: (body: ExportRequest) => unwrap(api.POST("/api/v1/exports", { body })),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (jobId: string) =>
      unwrap(api.DELETE("/api/v1/exports/{job_id}", { params: { path: { job_id: jobId } } })),
    onSuccess: invalidate,
  });
  return { start, remove };
}

export function useImports() {
  return useQuery({
    queryKey: queryKeys.imports,
    queryFn: () => unwrap(api.GET("/api/v1/imports")),
  });
}

/** One import session. Polled while the archive is being staged (validated + classified). */
export function useImportSession(importId: string | null) {
  return useQuery({
    queryKey: queryKeys.importSession(importId ?? ""),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/imports/{import_id}", {
          params: { path: { import_id: importId as string } },
        }),
      ),
    enabled: importId !== null,
    refetchInterval: (query) => (query.state.data?.state === "staging" ? 700 : false),
  });
}

export function useImportReport(importId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.importReport(importId ?? ""),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/imports/{import_id}/report", {
          params: { path: { import_id: importId as string } },
        }),
      ),
    enabled: enabled && importId !== null,
  });
}

export interface ImportDecision {
  importId: string;
  default: ImportPolicy;
  per_kind?: Record<string, ImportPolicy>;
  per_item?: Record<string, ImportPolicy>;
}

export function useImportActions() {
  const qc = useQueryClient();
  const apply = useMutation({
    mutationFn: (decision: ImportDecision) =>
      unwrap(
        api.POST("/api/v1/imports/{import_id}/apply", {
          params: { path: { import_id: decision.importId } },
          body: {
            default: decision.default,
            per_kind: decision.per_kind ?? {},
            per_item: decision.per_item ?? {},
          },
        }),
      ),
    onSuccess: () => {
      // An import can touch anything: start every list over rather than guess.
      qc.clear();
    },
  });
  const discard = useMutation({
    mutationFn: (importId: string) =>
      unwrap(
        api.DELETE("/api/v1/imports/{import_id}", {
          params: { path: { import_id: importId } },
        }),
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: queryKeys.imports }),
  });
  return { apply, discard };
}

// ---- background jobs (the activity centre) ------------------------------------------------------

/**
 * Failed jobs, and the count the sidebar badges. `job.failed` invalidates `["jobs"]` (see
 * `api/events.ts`), so the page and the badge follow a failure without polling.
 */
export function useJobs(states: readonly string[] = ["failed"], enabled = true) {
  return useQuery({
    queryKey: queryKeys.jobs(states),
    queryFn: () => unwrap(api.GET("/api/v1/jobs", { params: { query: { state: [...states] } } })),
    enabled,
  });
}

export function useJobActions() {
  const qc = useQueryClient();
  const invalidate = () => void qc.invalidateQueries({ queryKey: ["jobs"] });
  const retry = useMutation({
    mutationFn: (jobId: string) =>
      unwrap(api.POST("/api/v1/jobs/{job_id}/retry", { params: { path: { job_id: jobId } } })),
    onSuccess: invalidate,
  });
  const dismiss = useMutation({
    mutationFn: (jobId: string) =>
      unwrap(api.POST("/api/v1/jobs/{job_id}/dismiss", { params: { path: { job_id: jobId } } })),
    onSuccess: invalidate,
  });
  const dismissAll = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/jobs/dismiss-all")),
    onSuccess: invalidate,
  });
  return { retry, dismiss, dismissAll };
}

// ---- Display targets (docs/tv-display.md) -------------------------------------------------------

export function useDisplayTargets() {
  return useQuery({
    queryKey: queryKeys.displayTargets,
    queryFn: () => unwrap(api.GET("/api/v1/display/targets")),
  });
}

/** What the TV accepts — the intervals above all, since it refuses anything else. */
export function useDisplayCapabilities() {
  return useQuery({
    queryKey: queryKeys.displayCapabilities,
    queryFn: () => unwrap(api.GET("/api/v1/display/capabilities")),
    staleTime: Infinity,
  });
}

/**
 * Asks the TV itself, so it fails when the TV is asleep: only fetched on demand, never retried,
 * and the error is the answer (`tv_unreachable`).
 */
export function useDisplayStatus(targetId: string | null) {
  return useQuery({
    queryKey: queryKeys.displayStatus(targetId ?? ""),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/display/targets/{target_id}/status", {
          params: { path: { target_id: targetId as string } },
        }),
      ),
    enabled: Boolean(targetId),
    retry: false,
    staleTime: 10_000,
  });
}

/**
 * The TVs on the LAN (SSDP + a sweep of the /24): a few seconds, read-only. Only runs while the
 * Add-TV dialog is open, and again on "Scan again" (`refetch`).
 */
export function useDisplayDiscover(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.displayDiscover,
    queryFn: () => unwrap(api.GET("/api/v1/display/discover")),
    enabled,
    retry: false,
    staleTime: 0,
    gcTime: 0,
  });
}

export type DisplayPlanRequest = Schemas["DisplayPlanIn"];

/**
 * A push's dry run: what goes up, stays and leaves, and whose. `check_tv: false` answers at once
 * from the app's own map; `true` asks the TV (seconds) — the dialog shows the first while the
 * second is on its way. A TV that does not answer is not an error here: `tv_error` says so.
 */
export function useDisplayPlan(targetId: string | null, body: DisplayPlanRequest, enabled = true) {
  return useQuery({
    queryKey: queryKeys.displayPlan(targetId ?? "", body),
    queryFn: () =>
      unwrap(
        api.POST("/api/v1/display/targets/{target_id}/plan", {
          params: { path: { target_id: targetId as string } },
          body,
        }),
      ),
    enabled: enabled && Boolean(targetId),
    retry: false,
    staleTime: 5_000,
    placeholderData: keepPreviousData,
  });
}

function useDisplayMutation<TVariables, TResult>(
  mutationFn: (variables: TVariables) => Promise<TResult>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["display"] }),
  });
}

export function useDisplayActions() {
  const create = useDisplayMutation((body: Schemas["DisplayTargetIn"]) =>
    unwrap(api.POST("/api/v1/display/targets", { body })),
  );
  const update = useDisplayMutation(
    ({ id, ...body }: { id: string } & Schemas["DisplayTargetUpdateIn"]) =>
      unwrap(
        api.PATCH("/api/v1/display/targets/{target_id}", {
          params: { path: { target_id: id } },
          body,
        }),
      ),
  );
  const remove = useDisplayMutation((id: string) =>
    unwrap(
      api.DELETE("/api/v1/display/targets/{target_id}", { params: { path: { target_id: id } } }),
    ),
  );
  // Pairing waits for someone to accept a prompt on the TV: it must not look like a hang.
  const pair = useDisplayMutation((id: string) =>
    unwrap(
      api.POST("/api/v1/display/targets/{target_id}/pair", {
        params: { path: { target_id: id } },
      }),
    ),
  );
  const setSource = useDisplayMutation(({ id, ...body }: { id: string } & DisplaySource) =>
    unwrap(
      api.PUT("/api/v1/display/targets/{target_id}/source", {
        params: { path: { target_id: id } },
        body,
      }),
    ),
  );
  /** `slideshow_minutes` / `slideshow_ordered` are saved on the TV before the push is queued. */
  const push = useDisplayMutation(
    ({
      id,
      allowDeleteForeign,
      keepOurs = false,
      ...settings
    }: {
      id: string;
      allowDeleteForeign: boolean;
      /** Leave the images sent before on the TV instead of removing them (slideshow mode). */
      keepOurs?: boolean;
      slideshow_minutes?: number;
      slideshow_ordered?: boolean;
    }) =>
      unwrap(
        api.POST("/api/v1/display/targets/{target_id}/push", {
          params: { path: { target_id: id } },
          body: { allow_delete_foreign: allowDeleteForeign, keep_ours: keepOurs, ...settings },
        }),
      ),
  );
  /** A live dry run on demand (the TV page's "Send", which must know about foreign photos). */
  const plan = useMutation({
    mutationFn: ({ id, ...body }: { id: string } & DisplayPlanRequest) =>
      unwrap(
        api.POST("/api/v1/display/targets/{target_id}/plan", {
          params: { path: { target_id: id } },
          body,
        }),
      ),
  });
  return { create, update, remove, pair, setSource, push, plan };
}
