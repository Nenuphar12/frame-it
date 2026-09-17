import { Archive, Inbox, Info, Wand2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useNavigate } from "@tanstack/react-router";

import { usePhotos, useInboxAction } from "@/api/queries";
import { useRegisterCommands, type Command } from "@/app/commands";
import { CreateArtworksDialog } from "@/features/artworks/CreateArtworksDialog";
import { PhotoDrawer } from "@/features/photos/PhotoDrawer";
import { PhotoGrid } from "@/features/photos/PhotoGrid";
import { useSelection } from "@/features/photos/useSelection";
import { useFilePickers } from "@/features/upload/useFilePickers";
import { Button } from "@/shared/ui/Button";
import { EmptyState, PageHeader, Spinner } from "@/shared/ui/Misc";

export function InboxPage() {
  const { t } = useTranslation();
  const photos = usePhotos({ inbox_state: "inbox" });
  const items = useMemo(() => photos.data?.pages.flatMap((p) => p.items) ?? [], [photos.data]);
  const ids = useMemo(() => items.map((p) => p.id), [items]);
  const selection = useSelection(ids);
  const { selected, clear, selectAll, prune } = selection;
  const [detailsId, setDetailsId] = useState<string | null>(null);
  const action = useInboxAction();
  const { openFiles } = useFilePickers();
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = photos;
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();
  const selectedInOrder = useMemo(() => ids.filter((id) => selected.has(id)), [ids, selected]);

  useEffect(() => prune(new Set(ids)), [ids, prune]);

  const dismiss = useCallback(() => {
    if (selected.size === 0) return;
    action.mutate({ ids: [...selected], action: "dismiss" });
    clear();
  }, [action, clear, selected]);

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
    [clear, dismiss, selectAll, selected],
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
              <Button variant="secondary" disabled={selected.size === 0} onClick={dismiss}>
                <Archive size={16} /> {t("inbox.dismiss")}
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
            />
          )}
        </div>
      </div>
      {detailsId && <PhotoDrawer photoId={detailsId} onClose={() => setDetailsId(null)} />}
      <CreateArtworksDialog
        photoIds={selectedInOrder}
        open={creating}
        onOpenChange={setCreating}
        onCreated={() => {
          clear();
          void navigate({ to: "/artworks" });
        }}
      />
    </div>
  );
}
