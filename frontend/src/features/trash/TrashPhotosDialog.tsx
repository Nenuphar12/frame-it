import { AlertTriangle } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { TrashCascade } from "@/api/client";
import { useTrashActions, useTrashPreview } from "@/api/queries";
import { cn } from "@/shared/cn";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { Spinner } from "@/shared/ui/Misc";

interface TrashPhotosDialogProps {
  photoIds: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDone?: () => void;
}

/**
 * Deleting photos an artwork uses is a decision, not a confirmation (docs/organization.md §5):
 * the server lists the affected artworks first, then the cascade says whether they follow the
 * photo into the trash or keep their place with an empty slot.
 */
export function TrashPhotosDialog({
  photoIds,
  open,
  onOpenChange,
  onDone,
}: TrashPhotosDialogProps) {
  const { t } = useTranslation();
  const preview = useTrashPreview(open ? photoIds : []);
  const { photos } = useTrashActions();
  const [cascade, setCascade] = useState<TrashCascade>("trash_artworks");
  const affected = preview.data?.artworks ?? [];

  const options: { value: TrashCascade; label: string; hint: string }[] = [
    {
      value: "trash_artworks",
      label: t("trash.cascade.trash_artworks"),
      hint: t("trash.cascade.trashHint"),
    },
    {
      value: "empty_slots",
      label: t("trash.cascade.empty_slots"),
      hint: t("trash.cascade.emptyHint"),
    },
  ];

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("trash.deletePhotos", { count: photoIds.length })}
      description={t("trash.deletePhotosHint")}
    >
      <div className="space-y-3">
        {preview.isLoading ? (
          <Spinner />
        ) : affected.length === 0 ? (
          <p className="text-sm text-muted">{t("trash.noArtworksAffected")}</p>
        ) : (
          <>
            <div className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 p-2.5 text-sm">
              <AlertTriangle size={15} className="mt-0.5 shrink-0 text-warning" />
              <div className="min-w-0">
                <p>{t("trash.affected", { count: affected.length })}</p>
                <ul className="mt-1 max-h-32 space-y-0.5 overflow-y-auto text-xs text-muted">
                  {affected.map((artwork) => (
                    <li key={artwork.artwork_id} className="truncate">
                      {artwork.title || t("artworks.untitled")} —{" "}
                      {t("trash.slotsUsed", {
                        used: artwork.slot_count,
                        total: artwork.photo_count,
                      })}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            <div className="space-y-1.5">
              {options.map((option) => (
                <label
                  key={option.value}
                  className={cn(
                    "flex cursor-pointer gap-2 rounded-md border p-2.5 text-sm",
                    cascade === option.value ? "border-accent bg-accent/10" : "border-border",
                  )}
                >
                  <input
                    type="radio"
                    name="cascade"
                    className="mt-0.5"
                    checked={cascade === option.value}
                    onChange={() => setCascade(option.value)}
                  />
                  <span>
                    <span className="block font-medium">{option.label}</span>
                    <span className="block text-xs text-muted">{option.hint}</span>
                  </span>
                </label>
              ))}
            </div>
          </>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="danger"
            disabled={photos.isPending}
            onClick={() => {
              photos.mutate({ photo_ids: photoIds, cascade });
              onOpenChange(false);
              onDone?.();
            }}
          >
            {t("trash.moveToTrash")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
