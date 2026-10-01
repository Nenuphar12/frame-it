import { Tag as TagIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useBulkTags, usePhotosByIds } from "@/api/queries";
import { TagMenu } from "@/features/tags/TagMenu";
import { Button } from "@/shared/ui/Button";

/**
 * "Tag these N photos…" on a batch that just arrived (docs/organization.md §1): whatever the
 * route — the window's drop zone, the file pickers, LocalSend — and duplicates included, since a
 * photo the library already had is still part of what the user just sent.
 *
 * The photos' current tags are only fetched once the menu opens: a tray can hold hundreds of
 * items, and the tri-state is only needed while choosing.
 */
export function TagBatchMenu({ photoIds }: { photoIds: string[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const bulk = useBulkTags();
  const { photos } = usePhotosByIds(open ? photoIds : []);
  const itemTags = useMemo(() => {
    const byId = new Map(photos.map((photo) => [photo.id, photo.tags ?? []]));
    return photoIds.map((id) => byId.get(id) ?? []);
  }, [photoIds, photos]);
  if (photoIds.length === 0) return null;
  return (
    <TagMenu
      itemTags={itemTags}
      open={open}
      onOpenChange={setOpen}
      onChange={(change) => bulk.photos.mutate({ photo_ids: photoIds, ...change })}
      trigger={
        <Button size="sm" variant="ghost" title={t("upload.tagBatchHint")}>
          <TagIcon size={14} /> {t("upload.tagBatch", { count: photoIds.length })}
        </Button>
      }
    />
  );
}
