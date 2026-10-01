import { Archive, Inbox, Info, Trash2, Wand2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useNavigate } from "@tanstack/react-router";

import { useBulkTags, useInboxAction, usePhotos } from "@/api/queries";
import { useRegisterCommands, type Command } from "@/app/commands";
import { CreateArtworksDialog } from "@/features/artworks/CreateArtworksDialog";
import { PhotoDrawer } from "@/features/photos/PhotoDrawer";
import { PhotoGrid } from "@/features/photos/PhotoGrid";
import { useSelection } from "@/features/photos/useSelection";
import { TagMenu } from "@/features/tags/TagMenu";
import { TrashPhotosDialog } from "@/features/trash/TrashPhotosDialog";
import { useDeletePhotos } from "@/features/trash/useDeletePhotos";
import { useFilePickers } from "@/features/upload/useFilePickers";
import { Button } from "@/shared/ui/Button";
import { EmptyState, PageHeader, Spinner } from "@/shared/ui/Misc";

/**
 * Photos waiting for a finished artwork (docs/organization.md §6). A photo stays here while its
 * artworks are drafts — the badge opens the draft instead of inviting a second one — and leaves
 * when one of them is marked ready. Two ways out by hand, deliberately apart:
 *
 * - **Dismiss** (`d`) — keep the photo in the library, just not on this to-do list;
 * - **Delete** (`Delete`) — move it to the trash (with Undo, or the cascade dialog when an
 *   artwork uses it).
 */
export function InboxPage() {
  const { t } = useTranslation();
  const photos = usePhotos({ inbox_state: "inbox" });
  const items = useMemo(() => photos.data?.pages.flatMap((p) => p.items) ?? [], [photos.data]);
  const ids = useMemo(() => items.map((p) => p.id), [items]);
  const selection = useSelection(ids);
  const { selected, clear, selectAll, prune } = selection;
  const [detailsId, setDetailsId] = useState<string | null>(null);
  const action = useInboxAction();
  const bulkTags = useBulkTags();
  const { openFiles } = useFilePickers();
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = photos;
  const [creating, setCreating] = useState(false);
  const [tagMenuOpen, setTagMenuOpen] = useState(false);
  const navigate = useNavigate();
  const selectedInOrder = useMemo(() => ids.filter((id) => selected.has(id)), [ids, selected]);
  const selectedPhotos = useMemo(() => items.filter((p) => selected.has(p.id)), [items, selected]);
  const afterDelete = useCallback(() => {
    clear();
    setDetailsId(null);
  }, [clear]);
  const deletion = useDeletePhotos(afterDelete);

  useEffect(() => prune(new Set(ids)), [ids, prune]);

  const dismiss = useCallback(() => {
    if (selected.size === 0) return;
    action.mutate({ ids: [...selected], action: "dismiss" });
    clear();
  }, [action, clear, selected]);

  const trashSelection = useCallback(() => {
    if (selectedInOrder.length > 0) void deletion.request(selectedInOrder);
  }, [deletion, selectedInOrder]);

  const openDraft = useCallback(
    (artworkId: string) => void navigate({ to: "/editor/$artworkId", params: { artworkId } }),
    [navigate],
  );

  const commands = useMemo<Command[]>(
    () => [
      {
        id: "inbox.selectAll",
        label: "inbox.selectAll",
        group: "commands.groups.inbox",
        shortcut: "$mod+a",
        run: selectAll,
      },
      {
        id: "inbox.clear",
        label: "inbox.clearSelection",
        group: "commands.groups.inbox",
        shortcut: "Escape",
        run: clear,
      },
      {
        id: "inbox.dismiss",
        label: "inbox.dismiss",
        group: "commands.groups.inbox",
        shortcut: "d",
        run: dismiss,
      },
      {
        id: "inbox.trash",
        label: "inbox.delete",
        group: "commands.groups.inbox",
        shortcut: "Delete",
        run: trashSelection,
      },
      {
        id: "inbox.tag",
        label: "tags.tagSelection",
        group: "commands.groups.inbox",
        shortcut: "t",
        run: () => {
          if (selectedInOrder.length > 0) setTagMenuOpen(true);
        },
      },
      {
        id: "inbox.createArtworks",
        label: "inbox.createArtworks",
        group: "commands.groups.inbox",
        shortcut: "n",
        run: () => selected.size > 0 && setCreating(true),
      },
      {
        id: "inbox.details",
        label: "inbox.toggleDetails",
        group: "commands.groups.inbox",
        shortcut: "i",
        run: () => setDetailsId((current) => (current ? null : ([...selected][0] ?? null))),
      },
    ],
    [clear, dismiss, selectAll, selected, selectedInOrder, trashSelection],
  );
  useRegisterCommands(commands);

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <PageHeader
          title={t("nav.inbox")}
          subtitle={
            selected.size > 0
              ? t("inbox.selected", { count: selected.size })
              : t("inbox.subtitle", { count: items.length })
          }
          actions={
            <>
              <Button
                variant="primary"
                disabled={selected.size === 0}
                title={t("inbox.createArtworksHint")}
                onClick={() => setCreating(true)}
              >
                <Wand2 size={16} /> {t("inbox.createArtworks")}
              </Button>
              <TagMenu
                itemTags={selectedPhotos.map((p) => p.tags ?? [])}
                open={tagMenuOpen}
                onOpenChange={setTagMenuOpen}
                onChange={(change) =>
                  bulkTags.photos.mutate({ photo_ids: selectedInOrder, ...change })
                }
              />
              <Button
                variant="secondary"
                disabled={selected.size === 0}
                onClick={dismiss}
                title={t("inbox.dismissHint")}
              >
                <Archive size={16} /> {t("inbox.dismiss")}
              </Button>
              <Button
                variant="ghost"
                disabled={selected.size === 0}
                onClick={trashSelection}
                aria-label={t("inbox.delete")}
                title={t("inbox.deleteHint")}
              >
                <Trash2 size={16} />
              </Button>
              <Button
                variant="ghost"
                disabled={selected.size === 0 && !detailsId}
                onClick={() => setDetailsId(detailsId ? null : ([...selected][0] ?? null))}
                aria-label={t("inbox.toggleDetails")}
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
              icon={<Inbox size={40} />}
              title={t("inbox.emptyTitle")}
              description={t("inbox.emptyDescription")}
              action={
                <Button variant="primary" onClick={openFiles}>
                  {t("upload.addPhotos")}
                </Button>
              }
            />
          ) : (
            <PhotoGrid
              photos={items}
              selected={selected}
              onTileClick={(photo, index, event) => {
                selection.click(photo.id, index, event);
                if (detailsId) setDetailsId(photo.id);
              }}
              onTileDoubleClick={(photo) => setDetailsId(photo.id)}
              onEndReached={() => {
                if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
              }}
              onOpenDraft={openDraft}
            />
          )}
        </div>
      </div>
      {detailsId && <PhotoDrawer photoId={detailsId} onClose={() => setDetailsId(null)} />}
      <TrashPhotosDialog {...deletion.dialog} />
      <CreateArtworksDialog
        photoIds={selectedInOrder}
        open={creating}
        onOpenChange={setCreating}
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
