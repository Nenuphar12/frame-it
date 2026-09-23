import { Frame, Images, Trash2, Undo2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { artworkThumbUrl, photoThumbUrl } from "@/api/client";
import { useTrash, useTrashActions } from "@/api/queries";
import { formatBytes } from "@/shared/format";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { EmptyState, PageHeader, Spinner } from "@/shared/ui/Misc";

/**
 * The trash (docs/organization.md §5): what was soft-deleted, when, and two ways out — restore
 * (by item or by the batch a single gesture created) or purge, which is what frees disk.
 */
export function TrashPage() {
  const { t } = useTranslation();
  const trash = useTrash();
  const { restore, purge } = useTrashActions();
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [confirmEmpty, setConfirmEmpty] = useState(false);
  const [freed, setFreed] = useState<number | null>(null);
  const data = trash.data;
  const empty = (data?.photo_total ?? 0) === 0 && (data?.artwork_total ?? 0) === 0;

  const toggle = (key: string) =>
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const selection = useMemo(() => {
    const photo_ids: string[] = [];
    const artwork_ids: string[] = [];
    for (const key of picked) {
      const [kind, id] = key.split(":", 2) as [string, string];
      if (kind === "photo") photo_ids.push(id);
      else artwork_ids.push(id);
    }
    return { photo_ids, artwork_ids };
  }, [picked]);

  const restoreSelection = () => {
    restore.mutate(selection);
    setPicked(new Set());
  };

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title={t("nav.trash")}
        subtitle={
          data
            ? t("trash.summary", {
                photos: data.photo_total,
                artworks: data.artwork_total,
                days: data.retention_days,
              })
            : undefined
        }
        actions={
          <>
            {picked.size > 0 && (
              <Button size="sm" variant="ghost" onClick={restoreSelection}>
                <Undo2 size={14} /> {t("trash.restoreSelected", { count: picked.size })}
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              disabled={empty}
              onClick={() => {
                void purge.mutateAsync(false).then((result) => setFreed(result.bytes_freed));
              }}
              title={t("trash.purgeExpiredHint", { days: data?.retention_days ?? 30 })}
            >
              {t("trash.purgeExpired")}
            </Button>
            <Button size="sm" variant="danger" disabled={empty} onClick={() => setConfirmEmpty(true)}>
              <Trash2 size={14} /> {t("trash.empty")}
            </Button>
          </>
        }
      />
      {freed !== null && (
        <p className="px-5 pt-2 text-xs text-muted">
          {t("trash.freed", { size: formatBytes(freed) })}
        </p>
      )}
      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-4">
        {trash.isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Spinner size={20} />
          </div>
        ) : empty ? (
          <EmptyState
            icon={<Trash2 size={40} />}
            title={t("trash.emptyTitle")}
            description={t("trash.emptyDescription", { days: data?.retention_days ?? 30 })}
          />
        ) : (
          <>
            {(data?.artworks.length ?? 0) > 0 && (
              <section className="space-y-2">
                <h2 className="flex items-center gap-1.5 text-sm font-semibold">
                  <Frame size={14} /> {t("nav.artworks")}
                </h2>
                <div className="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-3">
                  {data?.artworks.map((artwork) => (
                    <label
                      key={artwork.id}
                      className="flex cursor-pointer items-center gap-2 rounded-md border border-border bg-panel p-2"
                    >
                      <input
                        type="checkbox"
                        checked={picked.has(`artwork:${artwork.id}`)}
                        onChange={() => toggle(`artwork:${artwork.id}`)}
                      />
                      <img
                        src={artworkThumbUrl(
                          { ...artwork, document_version: 0 },
                          256,
                        )}
                        alt=""
                        loading="lazy"
                        className="h-10 w-16 rounded object-cover"
                      />
                      <span className="min-w-0 flex-1 truncate text-sm">
                        {artwork.title || t("artworks.untitled")}
                      </span>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={t("trash.restore")}
                        onClick={(event) => {
                          event.preventDefault();
                          restore.mutate({ batch_ids: artwork.trash_batch_id ? [artwork.trash_batch_id] : [], artwork_ids: [artwork.id] });
                        }}
                      >
                        <Undo2 size={14} />
                      </Button>
                    </label>
                  ))}
                </div>
              </section>
            )}
            {(data?.photos.length ?? 0) > 0 && (
              <section className="space-y-2">
                <h2 className="flex items-center gap-1.5 text-sm font-semibold">
                  <Images size={14} /> {t("nav.photos")}
                </h2>
                <div className="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-3">
                  {data?.photos.map((photo) => (
                    <label
                      key={photo.id}
                      className="flex cursor-pointer items-center gap-2 rounded-md border border-border bg-panel p-2"
                    >
                      <input
                        type="checkbox"
                        checked={picked.has(`photo:${photo.id}`)}
                        onChange={() => toggle(`photo:${photo.id}`)}
                      />
                      <img
                        src={photoThumbUrl(photo.id, 256)}
                        alt=""
                        loading="lazy"
                        className="h-10 w-10 rounded object-cover"
                      />
                      <span className="min-w-0 flex-1 truncate text-sm">
                        {photo.original_filename}
                      </span>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={t("trash.restore")}
                        onClick={(event) => {
                          event.preventDefault();
                          // The batch brings back what was deleted together: the photo *and* the
                          // artworks that went with it (docs/organization.md §5).
                          restore.mutate({
                            photo_ids: [photo.id],
                            batch_ids: photo.trash_batch_id ? [photo.trash_batch_id] : [],
                          });
                        }}
                      >
                        <Undo2 size={14} />
                      </Button>
                    </label>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>

      <Dialog
        open={confirmEmpty}
        onOpenChange={setConfirmEmpty}
        title={t("trash.emptyConfirmTitle")}
        description={t("trash.emptyConfirmHint")}
      >
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirmEmpty(false)}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              void purge.mutateAsync(true).then((result) => setFreed(result.bytes_freed));
              setConfirmEmpty(false);
            }}
          >
            {t("trash.empty")}
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
