import { useCallback, useRef, useState } from "react";

import { useDeletePhotos } from "@/features/trash/useDeletePhotos";

/** The id of the photo tile that has the keyboard focus, if any (`PhotoGrid` marks its tiles). */
function focusedTileId(): string | null {
  const active = document.activeElement;
  return active instanceof HTMLElement ? (active.dataset.photoId ?? null) : null;
}

/**
 * The full-screen photo viewer of a grid (Photos, Inbox): which photo it shows, and what happens
 * when that photo leaves the list — trashed or dismissed from the viewer, it shows the next one
 * (else the previous one, else it closes), so sorting a burst is one key per photo.
 *
 * Render `<TrashPhotosDialog {...viewer.deletion.dialog} />` beside the grid: a photo an artwork
 * uses still asks what becomes of that artwork, over the viewer.
 */
export function usePhotoViewer(ids: string[]) {
  const [viewingId, setViewingId] = useState<string | null>(null);

  /** The photos in `gone` left the list: if one is on screen, show its nearest neighbour. */
  const moveOnFrom = useCallback(
    (gone: string[]) =>
      setViewingId((current) => {
        if (current === null || !gone.includes(current)) return current;
        const at = ids.indexOf(current);
        const staying = (id: string) => !gone.includes(id);
        return (
          ids.slice(at + 1).find(staying) ??
          ids.slice(0, Math.max(0, at)).reverse().find(staying) ??
          null
        );
      }),
    [ids],
  );

  const deletion = useDeletePhotos(moveOnFrom);
  // One request per photo: `Delete` pressed twice before the server answered must not trash the
  // photo twice (the second would fail) nor move on twice.
  const trashing = useRef(new Set<string>());
  const { request } = deletion;
  const trash = useCallback(
    (id: string) => {
      if (trashing.current.has(id)) return;
      trashing.current.add(id);
      void request([id]).finally(() => trashing.current.delete(id));
    },
    [request],
  );

  /**
   * Open on the photo a keyboard "view" means: the focused tile, else `preferred` (the one last
   * clicked), else the first.
   */
  const viewCurrent = useCallback(
    (preferred: string | null) => {
      const focused = focusedTileId();
      const id =
        (focused && ids.includes(focused) ? focused : null) ??
        (preferred && ids.includes(preferred) ? preferred : null) ??
        ids[0];
      if (id) setViewingId(id);
    },
    [ids],
  );

  return {
    /** Gone from the list some other way (another tab, a filter): nothing to show. */
    viewingId: viewingId !== null && ids.includes(viewingId) ? viewingId : null,
    view: setViewingId,
    viewCurrent,
    close: useCallback(() => setViewingId(null), []),
    moveOnFrom,
    trash,
    deletion,
  };
}
