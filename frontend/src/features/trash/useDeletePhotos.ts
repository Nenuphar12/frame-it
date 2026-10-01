import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { api, unwrap } from "@/api/client";

import { useTrashWithUndo } from "./useTrashWithUndo";

/**
 * Deleting photos, from any grid (Photos, Inbox): ask the server which artworks use them first.
 *
 * - **none** — there is nothing to decide: they go to the trash now, with Undo;
 * - **some** — the cascade dialog asks whether those artworks follow them or keep their place
 *   with an empty slot (docs/organization.md §5). The dialog reads the same cached preview.
 *
 * Render `<TrashPhotosDialog {...dialog} />` beside the grid.
 */
export function useDeletePhotos(onDone?: () => void) {
  const qc = useQueryClient();
  const { trashPhotos } = useTrashWithUndo();
  const [asking, setAsking] = useState<string[] | null>(null);

  const request = useCallback(
    async (photoIds: string[]) => {
      if (photoIds.length === 0) return;
      const preview = await qc
        .fetchQuery({
          queryKey: ["trash", "preview", photoIds],
          queryFn: () =>
            unwrap(api.POST("/api/v1/trash/preview", { body: { photo_ids: photoIds } })),
        })
        .catch(() => null);
      if (preview && preview.artworks.length === 0) {
        onDone?.();
        await trashPhotos(photoIds);
        return;
      }
      setAsking(photoIds); // affected artworks — or the preview failed: let the dialog say so
    },
    [onDone, qc, trashPhotos],
  );

  return {
    request,
    dialog: {
      photoIds: asking ?? [],
      open: asking !== null,
      onOpenChange: (open: boolean) => {
        if (!open) setAsking(null);
      },
      onDone,
    },
  };
}
