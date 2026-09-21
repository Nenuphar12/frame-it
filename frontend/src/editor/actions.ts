// What the editor UI calls: a semantic action per control, bound to the store and the operations.
// Components never touch the document directly, so every change is undoable and autosaved.
import type { Alternative } from "@/editor/core/alternatives.ts";
import {
  findSlot,
  type DocMargins,
  type DocSlot,
  type EditorDocument,
  type Placement,
} from "@/editor/core/document.ts";
import type { Orient } from "@/editor/core/geometry.ts";
import type { QualityLock } from "@/editor/core/placement.ts";
import * as ops from "@/editor/operations";
import type { Axis, Edge } from "@/editor/core/arrange.ts";
import type { Anchor } from "@/editor/core/constraints.ts";
import type { DocCaption } from "@/editor/core/document.ts";
import type { Size } from "@/editor/core/geometry.ts";
import {
  edit,
  ensurePhotoSize,
  primarySlotId,
  select,
  selectCaption,
  useEditor,
} from "@/editor/store";

/**
 * Run a slot mutation on the *primary* slot — the last one picked. Framing and cropping always
 * work on a single slot; what applies to the whole selection goes through `onSlots`.
 */
function onSlot(
  recipe: (doc: EditorDocument, slot: DocSlot) => void,
  group: string | null = null,
): void {
  const slotId = primarySlotId(useEditor.getState());
  if (!slotId) return;
  edit((doc) => {
    const slot = findSlot(doc, slotId);
    if (slot) recipe(doc, slot);
  }, group);
}

/** Run a slot mutation on every selected slot (locks and decorations apply to all of them). */
function onSlots(
  recipe: (doc: EditorDocument, slot: DocSlot) => void,
  group: string | null = null,
): void {
  const ids = useEditor.getState().selectedSlotIds;
  if (ids.length === 0) return;
  edit((doc) => {
    for (const id of ids) {
      const slot = findSlot(doc, id);
      if (slot) recipe(doc, slot);
    }
  }, group);
}

/** Run a mutation on the selected caption. */
function onCaption(recipe: (doc: EditorDocument, captionId: string) => void, group: string | null = null): void {
  const captionId = useEditor.getState().selectedCaptionId;
  if (!captionId) return;
  edit((doc) => recipe(doc, captionId), group);
}

const sizes = () => useEditor.getState().sizes;

export const setMargins = (margins: Partial<DocMargins>, group: string | null = "margins") =>
  edit((doc) => ops.setMargins(doc, margins, sizes()), group);

export const setPlacement = (placement: Placement) =>
  edit((doc) => ops.setPlacement(doc, placement, sizes()));

export const setMatColor = (color: string, group: string | null = "mat-color") =>
  edit((doc) => ops.setMatColor(doc, color), group);

export const setTexture = (id: string | null, strength: number, group: string | null = null) =>
  edit((doc) => ops.setTexture(doc, id, strength), group);

export const setLock = (lock: QualityLock) =>
  onSlots((doc, slot) => ops.setLock(doc, slot, lock, sizes()));

export const setCropRatio = (ratio: string) =>
  onSlot((doc, slot) => ops.setCropRatio(doc, slot, ratio, sizes()));

export const setOrient = (orient: Orient) =>
  onSlot((doc, slot) => ops.setOrient(doc, slot, orient, sizes()));

export const rotateSource = (turns: number) =>
  onSlot((doc, slot) => ops.rotateSource(doc, slot, turns, sizes()));

export const flipSource = () => onSlot((doc, slot) => ops.flipSource(doc, slot, sizes()));

export const setRotation = (degrees: number) =>
  onSlot((_doc, slot) => ops.setRotation(slot, degrees), "rotation");

export const panCrop = (dx: number, dy: number) =>
  onSlot((doc, slot) => ops.panCrop(doc, slot, dx, dy, sizes()), "crop-pan");

export const zoomCrop = (factor: number) =>
  onSlot((doc, slot) => ops.zoomCrop(doc, slot, factor, sizes()), "crop-zoom");

/** Absolute photo zoom (the panel's slider, §7.5); the wheel uses `zoomCrop`. */
export const setZoom = (zoom: number) =>
  onSlot((doc, slot) => ops.setPhotoZoom(doc, slot, zoom, sizes()), "crop-zoom");

export const setBands = (bands: DocSlot["bands"]) =>
  onSlots((_doc, slot) => ops.setBands(slot, bands), "bands");

export const setShadow = (shadow: DocSlot["shadow"], group: string | null = "shadow") =>
  onSlots((_doc, slot) => ops.setShadow(slot, shadow), group);

export const applyAlternative = (alternative: Alternative) =>
  onSlot((doc, slot) => ops.applyAlternative(doc, slot, alternative));

/** Nudge the photo inside its slot (arrow keys; `Shift` = 10 canvas px, §11.5). */
export function nudgeCrop(dx: number, dy: number): void {
  const state = useEditor.getState();
  const slot = state.doc ? findSlot(state.doc, primarySlotId(state)) : null;
  if (!slot) return;
  const perPixel = slot.source.crop.w / Math.max(1, slot.rect.w);
  panCrop(dx * perPixel, dy * perPixel);
}

/**
 * What the arrow keys move (§11.5): the selected caption, the selected slots of a composition,
 * or — with the crop tool, or on a single-slot artwork — the photo inside its slot.
 */
export function nudge(dx: number, dy: number): void {
  const state = useEditor.getState();
  if (state.selectedCaptionId) {
    moveCaption(dx, dy);
    return;
  }
  if (state.tool === "select" && state.doc?.placement === "manual") {
    moveSlots(dx, dy);
    return;
  }
  nudgeCrop(dx, dy);
}

// ---- composition: slots (Phase 6) --------------------------------------------------------------
/** Add a slot (empty when `photoId` is null) and select it. */
export async function addSlot(
  photoId: string | null,
  at: { x: number; y: number } | null = null,
): Promise<void> {
  if (photoId) await ensurePhotoSize(photoId); // its size decides the slot's shape and crop
  let added: string | null = null;
  edit((doc) => {
    added = ops.addSlot(doc, photoId, sizes(), at);
  });
  if (added) select(added);
}

export function removeSelectedSlots(): void {
  const ids = useEditor.getState().selectedSlotIds;
  if (ids.length === 0) return;
  edit((doc) => ops.removeSlots(doc, ids));
  select(null);
}

export async function setSlotPhoto(slotId: string, photoId: string | null): Promise<void> {
  if (photoId) await ensurePhotoSize(photoId);
  edit((doc) => {
    const slot = findSlot(doc, slotId);
    if (slot) ops.setSlotPhoto(doc, slot, photoId, sizes());
  });
}

export const swapPhotos = (firstId: string, secondId: string) =>
  edit((doc) => ops.swapPhotos(doc, firstId, secondId, sizes()));

/** Move every selected slot (canvas drag, arrow keys). */
export const moveSlots = (dx: number, dy: number, group: string | null = "slot-move") => {
  if (dx === 0 && dy === 0) return;
  onSlots((_doc, slot) => ops.moveSlot(slot, dx, dy), group);
};

export const setSlotPosition = (x: number, y: number) =>
  onSlot((_doc, slot) => ops.setSlotPosition(slot, x, y), "slot-move");

export const resizeSlot = (size: Size, anchor: Anchor, group: string | null = "slot-resize") =>
  onSlot((doc, slot) => ops.resizeSlotTo(doc, slot, size, anchor, sizes()), group);

export const fitSlotToPhoto = () =>
  onSlots((doc, slot) => ops.fitSlotToPhoto(doc, slot, sizes()));

export const fillSlotWithPhoto = () =>
  onSlots((doc, slot) => ops.fillSlotWithPhoto(doc, slot, sizes()));

/** Z-order: `delta` = +1 brings the slot one step forward (§11.5, `[` and `]`). */
export function moveInOrder(delta: number): void {
  const slotId = primarySlotId(useEditor.getState());
  if (!slotId) return;
  edit((doc) => ops.moveSlotInOrder(doc, slotId, delta));
}

export const reorderSlots = (from: number, to: number) =>
  edit((doc) => ops.reorderSlots(doc, from, to));

// ---- composition: arranging a selection --------------------------------------------------------
const selection = () => useEditor.getState().selectedSlotIds;

export const alignSlots = (edge: Edge) => edit((doc) => ops.alignSlots(doc, selection(), edge));

export const distributeSlots = (axis: Axis) =>
  edit((doc) => ops.distributeSlots(doc, selection(), axis));

export function sameSizeSlots(): void {
  const state = useEditor.getState();
  const primary = primarySlotId(state);
  if (!primary) return;
  edit((doc) => ops.sameSizeSlots(doc, state.selectedSlotIds, primary, sizes()));
}

export function applyDecorations(): void {
  const state = useEditor.getState();
  const primary = primarySlotId(state);
  if (!primary) return;
  edit((doc) => ops.applyDecorations(doc, primary, state.selectedSlotIds, sizes()));
}

// ---- composition: captions ---------------------------------------------------------------------
export function addCaption(text: string, defaults: Partial<DocCaption> = {}): void {
  let added: string | null = null;
  edit((doc) => {
    added = ops.addCaption(doc, text, defaults);
  });
  if (added) selectCaption(added);
}

export const updateCaption = (
  patch: Partial<DocCaption>,
  group: string | null = "caption",
) => onCaption((doc, id) => ops.updateCaption(doc, id, patch), group);

export const moveCaption = (dx: number, dy: number, group: string | null = "caption-move") =>
  onCaption((doc, id) => ops.moveCaption(doc, id, dx, dy), group);

export function removeCaption(): void {
  const captionId = useEditor.getState().selectedCaptionId;
  if (!captionId) return;
  edit((doc) => ops.removeCaption(doc, captionId));
  selectCaption(null);
}
