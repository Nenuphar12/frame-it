import { useTranslation } from "react-i18next";

import type { TrashCascade } from "@/api/client";
import { useTrashActions } from "@/api/queries";
import { toast, useToasts } from "@/shared/toast";

/** Long enough to read the toast and reach for the button; the trash keeps everything anyway. */
const UNDO_MS = 10_000;

/**
 * Moving to the trash is reversible, so it never asks first (docs/organization.md §5): it acts,
 * then offers **Undo** — which restores exactly the batch that gesture created, nothing else.
 *
 * The one place a question remains is deleting photos that artworks use: that is a decision, not
 * a confirmation, and `TrashPhotosDialog` asks it before calling `trashPhotos` here.
 *
 * Promises rather than per-call callbacks: the toast must appear even when the component that
 * started it (a viewer moving on, a dialog closing) is gone by the time the server answers.
 * Failures are the global `MutationCache`'s to report (invariant 14).
 */
export function useTrashWithUndo() {
  const { t } = useTranslation();
  const { photos, artworks, restore } = useTrashActions();

  const announce = (result: {
    batch_id: string;
    photos: number;
    artworks: number;
    emptied: number;
  }) => {
    if (result.photos + result.artworks + result.emptied === 0) return;
    const detail = [
      result.photos > 0 ? t("trash.photoCount", { count: result.photos }) : null,
      result.artworks > 0 ? t("trash.artworkCount", { count: result.artworks }) : null,
      result.emptied > 0 ? t("trash.emptiedCount", { count: result.emptied }) : null,
    ]
      .filter(Boolean)
      .join(" · ");
    // Restoring the batch brings the photos back but cannot refill the slots it emptied (each
    // artwork's history can, `pre_trash`): an Undo that only half-undoes is not offered.
    const undo =
      result.emptied > 0
        ? undefined
        : {
            label: "trash.undo",
            run: () =>
              void restore
                .mutateAsync({ batch_ids: [result.batch_id] })
                .then(() => toast.success("trash.restoredToast"))
                .catch(() => undefined),
          };
    useToasts.getState().push({
      tone: "info",
      title: "trash.moved",
      detail: result.emptied > 0 ? `${detail}. ${t("trash.emptiedHint")}` : detail,
      timeout: UNDO_MS,
      action: undo,
    });
  };

  const trashArtworks = (ids: string[]): Promise<void> =>
    ids.length === 0
      ? Promise.resolve()
      : artworks
          .mutateAsync(ids)
          .then(announce)
          .catch(() => undefined);

  const trashPhotos = (ids: string[], cascade: TrashCascade = "trash_artworks"): Promise<void> =>
    ids.length === 0
      ? Promise.resolve()
      : photos
          .mutateAsync({ photo_ids: ids, cascade })
          .then(announce)
          .catch(() => undefined);

  return { trashArtworks, trashPhotos, isPending: photos.isPending || artworks.isPending };
}
