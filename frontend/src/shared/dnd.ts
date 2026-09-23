// HTML drag and drop inside the app: the MIME types our own drags carry.
//
// They exist to be *recognised*, not just read. Dragging a photo chip means dragging an `<img>`,
// and Chrome offers such a drag to the page as a file (it could be dropped on the desktop), so the
// window-wide upload zone lit up — "Drop photos or a folder" across the whole screen — for a drag
// that only ever meant "swap these two cells" (remarks.md #1). Every internal drag stamps itself,
// and `hasFiles` ignores a drag that is stamped.
export const PHOTO_MIME = "text/x-the-frame-photo";
export const SLOT_MIME = "text/x-the-frame-slot";
/** An artwork dragged from a grid onto a collection (Phase 9); the value is a comma-joined list. */
export const ARTWORK_MIME = "text/x-the-frame-artwork";
/** A collection dragged in the tree to be re-parented or reordered. */
export const COLLECTION_MIME = "text/x-the-frame-collection";

const INTERNAL = [PHOTO_MIME, SLOT_MIME, ARTWORK_MIME, COLLECTION_MIME];

/** Mark a drag as ours. Call it in `onDragStart`, with the payload the drop target needs. */
export function startInternalDrag(
  dataTransfer: DataTransfer,
  mime: string,
  value: string,
  effect: DataTransfer["effectAllowed"] = "move",
): void {
  dataTransfer.setData(mime, value);
  dataTransfer.effectAllowed = effect;
}

/** True when the drag comes from inside the app (so it is not a file being dropped on us). */
export function isInternalDrag(types: readonly string[]): boolean {
  return INTERNAL.some((mime) => types.includes(mime));
}
