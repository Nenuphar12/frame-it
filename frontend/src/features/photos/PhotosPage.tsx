import { Images, Info, Search, Wand2 } from "lucide-react";
import { useCallback, useDeferredValue, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useNavigate } from "@tanstack/react-router";

import { usePhotos } from "@/api/queries";
import { useRegisterCommands, type Command } from "@/app/commands";
import { CreateArtworksDialog } from "@/features/artworks/CreateArtworksDialog";
import { useFilePickers } from "@/features/upload/useFilePickers";
import { Button } from "@/shared/ui/Button";
import { EmptyState, PageHeader, Spinner } from "@/shared/ui/Misc";

import { PhotoDrawer } from "./PhotoDrawer";
import { PhotoGrid } from "./PhotoGrid";
import { useSelection } from "./useSelection";

export function PhotosPage() {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query.trim());
  const photos = usePhotos(deferredQuery ? { q: deferredQuery } : {});
  const items = useMemo(() => photos.data?.pages.flatMap((p) => p.items) ?? [], [photos.data]);
  const ids = useMemo(() => items.map((p) => p.id), [items]);
  const selection = useSelection(ids);
  const { selected, clear, selectAll, prune } = selection;
  const selectedInOrder = useMemo(() => ids.filter((id) => selected.has(id)), [ids, selected]);
  const [openId, setOpenId] = useState<string | null>(null);
  /** Photos given to the create dialog (the selection, or the photo shown in the drawer). */
  const [creatingIds, setCreatingIds] = useState<string[] | null>(null);
  const navigate = useNavigate();
  const { openFiles } = useFilePickers();
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = photos;
  const loadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  useEffect(() => prune(new Set(ids)), [ids, prune]);

  const createFromSelection = useCallback(() => {
    if (selectedInOrder.length > 0) setCreatingIds(selectedInOrder);
  }, [selectedInOrder]);

  const commands = useMemo<Command[]>(
    () => [
      {
        id: "photos.selectAll",
        label: "photos.selectAll",
        group: "commands.groups.library",
        shortcut: "$mod+a",
        run: selectAll,
      },
      {
        id: "photos.clear",
        label: "photos.clearSelection",
        group: "commands.groups.library",
        shortcut: "Escape",
        run: clear,
      },
      {
        id: "photos.createArtworks",
        label: "photos.createArtworks",
        group: "commands.groups.library",
        shortcut: "n",
        run: createFromSelection,
      },
      {
        id: "photos.details",
        label: "photos.toggleDetails",
        group: "commands.groups.library",
        shortcut: "i",
        run: () => setOpenId((current) => (current ? null : (selectedInOrder[0] ?? null))),
      },
    ],
    [clear, createFromSelection, selectAll, selectedInOrder],
  );
  useRegisterCommands(commands);

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <PageHeader
          title={t("nav.photos")}
          subtitle={
            selected.size > 0
              ? t("photos.selected", { count: selected.size })
              : photos.data
                ? t("photos.count", { count: items.length })
                : undefined
          }
          actions={
            <>
              <label className="flex items-center gap-2 rounded-md border border-border bg-bg px-2.5 py-1.5">
                <Search size={14} className="text-muted" />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={t("photos.searchPlaceholder")}
                  className="w-56 bg-transparent text-sm outline-none placeholder:text-muted"
                />
              </label>
              <Button
                variant="primary"
                disabled={selected.size === 0}
                title={t("photos.createArtworksHint")}
                onClick={createFromSelection}
              >
                <Wand2 size={16} /> {t("photos.createArtworks")}
              </Button>
              <Button
                variant="ghost"
                disabled={selected.size === 0 && !openId}
                onClick={() => setOpenId(openId ? null : (selectedInOrder[0] ?? null))}
                aria-label={t("photos.toggleDetails")}
              >
                <Info size={16} />
              </Button>
            </>
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
              selected={selected}
              focusedId={openId}
              onTileClick={(photo, index, event) => {
                selection.click(photo.id, index, event);
                if (openId) setOpenId(photo.id);
              }}
              onTileDoubleClick={(photo) => setOpenId(photo.id)}
              onEndReached={loadMore}
            />
          )}
        </div>
      </div>
      {openId && (
        <PhotoDrawer
          photoId={openId}
          onClose={() => setOpenId(null)}
          onCreateArtwork={(id) => setCreatingIds([id])}
        />
      )}
      <CreateArtworksDialog
        photoIds={creatingIds ?? []}
        open={creatingIds !== null}
        onOpenChange={(open) => !open && setCreatingIds(null)}
        onCreated={(ids) => {
          clear();
          const first = ids[0];
          if (first) {
            // Straight into the review queue: validate & next until the batch is done.
            void navigate({
              to: "/editor/$artworkId",
              params: { artworkId: first },
              search: { queue: ids.join(",") },
            });
          } else {
            void navigate({ to: "/artworks" });
          }
        }}
      />
    </div>
  );
}
