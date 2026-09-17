import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api, unwrap, type Artwork, type Photo } from "./client";

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

export interface CreateArtworksInput {
  /** One artwork per group, photos in slot order. */
  groups: string[][];
  style_id: string;
  layout_id: string;
  placement: "fit_in_mat" | "fill" | null;
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
