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
import { edit, useEditor } from "@/editor/store";

/** Run a slot mutation on the selected slot (no-op when nothing is selected). */
function onSlot(
  recipe: (doc: EditorDocument, slot: DocSlot) => void,
  group: string | null = null,
): void {
  const slotId = useEditor.getState().selectedSlotId;
  if (!slotId) return;
  edit((doc) => {
    const slot = findSlot(doc, slotId);
    if (slot) recipe(doc, slot);
  }, group);
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
  onSlot((doc, slot) => ops.setLock(doc, slot, lock, sizes()));

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
  onSlot((_doc, slot) => ops.setBands(slot, bands), "bands");

export const setShadow = (shadow: DocSlot["shadow"], group: string | null = "shadow") =>
  onSlot((_doc, slot) => ops.setShadow(slot, shadow), group);

export const applyAlternative = (alternative: Alternative) =>
  onSlot((doc, slot) => ops.applyAlternative(doc, slot, alternative));

/** Nudge the photo inside its slot (arrow keys; `Shift` = 10 canvas px, §11.5). */
export function nudgeCrop(dx: number, dy: number): void {
  const { doc, selectedSlotId } = useEditor.getState();
  const slot = doc ? findSlot(doc, selectedSlotId) : null;
  if (!slot) return;
  const perPixel = slot.source.crop.w / Math.max(1, slot.rect.w);
  panCrop(dx * perPixel, dy * perPixel);
}
