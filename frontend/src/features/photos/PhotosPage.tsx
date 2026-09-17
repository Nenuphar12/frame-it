import { Images, Search } from "lucide-react";
import { useCallback, useDeferredValue, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { usePhotos } from "@/api/queries";
import { useFilePickers } from "@/features/upload/useFilePickers";
import { Button } from "@/shared/ui/Button";
import { EmptyState, PageHeader, Spinner } from "@/shared/ui/Misc";

import { PhotoDrawer } from "./PhotoDrawer";
import { PhotoGrid } from "./PhotoGrid";

export function PhotosPage() {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query.trim());
  const photos = usePhotos(deferredQuery ? { q: deferredQuery } : {});
  const items = useMemo(() => photos.data?.pages.flatMap((p) => p.items) ?? [], [photos.data]);
  const [openId, setOpenId] = useState<string | null>(null);
  const { openFiles } = useFilePickers();
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = photos;
  const loadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <PageHeader
          title={t("nav.photos")}
          subtitle={photos.data ? t("photos.count", { count: items.length }) : undefined}
          actions={
            <label className="flex items-center gap-2 rounded-md border border-border bg-bg px-2.5 py-1.5">
              <Search size={14} className="text-muted" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("photos.searchPlaceholder")}
                className="w-56 bg-transparent text-sm outline-none placeholder:text-muted"
              />
            </label>
          }
        />
        <div className="min-h-0 flex-1">
          {photos.isLoading ? (
            <div className="flex h-full items-center justify-center">
              <Spinner size={20} />
            </div>
          ) : items.length === 0 ? (
            <EmptyState
              icon={<Images size={40} />}
              title={deferredQuery ? t("photos.noResults") : t("photos.emptyTitle")}
              description={deferredQuery ? undefined : t("photos.emptyDescription")}
              action={
                !deferredQuery && (
                  <Button variant="primary" onClick={openFiles}>
                    {t("upload.addPhotos")}
                  </Button>
                )
              }
            />
          ) : (
            <PhotoGrid
              photos={items}
              focusedId={openId}
              onTileClick={(photo) => setOpenId(photo.id)}
              onEndReached={loadMore}
            />
          )}
        </div>
      </div>
      {openId && <PhotoDrawer photoId={openId} onClose={() => setOpenId(null)} />}
    </div>
  );
}
