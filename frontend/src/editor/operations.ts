// Every edit the editor can make to an artwork document, as pure mutations of an Immer draft.
//
// They are the only place that knows how a change propagates: editing the margins of a
// `fit_in_mat` artwork re-places the slot, editing the crop of a `native` slot re-computes the
// margins (native linking, §7.4), switching the lock repairs the slot (§7.3). Keeping them out of
// components means the store can replay them for undo/redo and the rules stay testable.
import {
  applyCropRatio,
  applyLock,
  panCrop as panCropSolver,
  resizeCrop,
  zoomCrop as zoomCropSolver,
  type SlotState,
} from "@/editor/core/constraints.ts";
import type { Alternative } from "@/editor/core/alternatives.ts";
import type { DocMargins, DocSlot, EditorDocument, Placement } from "@/editor/core/document.ts";
import {
  orientedSize,
  parseRatio,
  reorientCrop,
  type Orient,
  type Rect,
  type Size,
} from "@/editor/core/geometry.ts";
import {
  fill,
  fitInMat,
  largestCrop,
  marginsForSlot,
  type QualityLock,
  type SlotPlacement,
} from "@/editor/core/placement.ts";

/** EXIF-oriented photo sizes, by photo id (from `GET /photos/{id}`). */
export type PhotoSizes = Record<string, Size>;

export const CROP_RATIOS = ["original", "free", "16:9", "3:2", "4:3", "1:1", "4:5"] as const;

/** Source size a slot's crop lives in: the photo after EXIF **and** the slot's own orientation. */
export function slotSource(slot: DocSlot, sizes: PhotoSizes): Size | null {
  const size = slot.photo_id ? sizes[slot.photo_id] : undefined;
  return size ? orientedSize(size, slot.source.orient) : null;
}

function state(slot: DocSlot): SlotState {
  return { rect: slot.rect, crop: slot.source.crop };
}

function write(slot: DocSlot, placement: SlotPlacement): void {
  slot.rect = placement.rect;
  slot.source.crop = placement.crop;
  slot.quality_lock = placement.quality_lock;
}

/** The single slot of a `fit_in_mat` / `fill` artwork (those placements have exactly one). */
function soleSlot(doc: EditorDocument): DocSlot | null {
  return doc.placement === "manual" ? null : (doc.slots[0] ?? null);
}

/** Re-place the slot of a non-manual artwork after the margins, crop or lock changed. */
function replace(doc: EditorDocument, sizes: PhotoSizes): void {
  const slot = soleSlot(doc);
  const source = slot ? slotSource(slot, sizes) : null;
  if (!slot || !source) return;
  if (doc.placement === "fill") {
    write(slot, fill(source, slot.quality_lock));
    return;
  }
  write(
    slot,
    fitInMat(source, slot.source.crop, slot.source.crop_ratio, doc.margins, slot.quality_lock),
  );
}

/**
 * Native linking the other way round (§7.4): under `fit_in_mat` + `native` the slot is the crop,
 * so the free space becomes the margins, keeping their previous per-side proportions.
 */
function marginsFollowSlot(doc: EditorDocument, slot: DocSlot): void {
  if (doc.placement !== "fit_in_mat" || slot.quality_lock !== "native") return;
  const next = marginsForSlot(
    { w: slot.rect.w, h: slot.rect.h },
    doc.margins,
    doc.margins.linked,
    { w: doc.canvas.width, h: doc.canvas.height },
    doc.margins.mirror_x,
    doc.margins.mirror_y,
  );
  doc.margins = { ...doc.margins, ...next };
  const area = fitInMat(
    { w: slot.source.crop.w, h: slot.source.crop.h },
    slot.source.crop,
    slot.source.crop_ratio,
    doc.margins,
    "native",
  );
  slot.rect = area.rect;
}

// ---- document-level edits ----------------------------------------------------------------------
export function setMargins(
  doc: EditorDocument,
  margins: Partial<DocMargins>,
  sizes: PhotoSizes,
): void {
  const next = { ...doc.margins, ...margins };
  if (next.linked) {
    const value = margins.top ?? margins.right ?? margins.bottom ?? margins.left ?? next.top;
    next.top = next.right = next.bottom = next.left = value;
  } else {
    // Mirrored axes: the side the user moved drives the opposite one (§7.4).
    if (next.mirror_x && (margins.left !== undefined || margins.right !== undefined)) {
      next.left = next.right = margins.left ?? margins.right ?? next.left;
    }
    if (next.mirror_y && (margins.top !== undefined || margins.bottom !== undefined)) {
      next.top = next.bottom = margins.top ?? margins.bottom ?? next.top;
    }
  }
  doc.margins = clampMargins(next, doc);
  replace(doc, sizes);
}

function clampMargins(margins: DocMargins, doc: EditorDocument): DocMargins {
  const limit = (a: number, b: number, span: number, mirrored: boolean): [number, number] => {
    if (mirrored) {
      const both = Math.max(0, Math.min(a, Math.floor((span - 1) / 2)));
      return [both, both];
    }
    const first = Math.max(0, Math.min(a, span - 1));
    return [first, Math.max(0, Math.min(b, span - 1 - first))];
  };
  const mirrorX = margins.mirror_x && !margins.linked;
  const mirrorY = margins.mirror_y && !margins.linked;
  const [left, right] = limit(margins.left, margins.right, doc.canvas.width, mirrorX);
  const [top, bottom] = limit(margins.top, margins.bottom, doc.canvas.height, mirrorY);
  return { ...margins, top, right, bottom, left };
}

export function setPlacement(
  doc: EditorDocument,
  placement: Placement,
  sizes: PhotoSizes,
): void {
  if (doc.slots.length !== 1) return; // multi-slot artworks are always `manual`
  doc.placement = placement;
  if (placement === "manual") return; // switching to manual keeps the current geometry (§7.4)
  replace(doc, sizes);
}

export function setMatColor(doc: EditorDocument, color: string): void {
  doc.mat.color = color;
}

export function setTexture(doc: EditorDocument, id: string | null, strength: number): void {
  doc.mat.texture = id === null ? null : { id, strength };
}

// ---- slot edits --------------------------------------------------------------------------------
export function setLock(
  doc: EditorDocument,
  slot: DocSlot,
  lock: QualityLock,
  sizes: PhotoSizes,
): void {
  const source = slotSource(slot, sizes);
  if (!source) return;
  if (lock === "native") slot.rotation = 0; // `native` forbids rotation (document rule)
  write(slot, applyLock(state(slot), lock, source));
  if (doc.placement === "manual") return;
  if (lock === "native") marginsFollowSlot(doc, slot);
  else replace(doc, sizes);
}

export function setCropRatio(
  doc: EditorDocument,
  slot: DocSlot,
  cropRatio: string,
  sizes: PhotoSizes,
): void {
  const source = slotSource(slot, sizes);
  if (!source) return;
  slot.source.crop_ratio = cropRatio;
  write(slot, applyCropRatio(state(slot), parseRatio(cropRatio, source), source, slot.quality_lock));
  afterCropChange(doc, slot, sizes);
}

/** 90° turns and horizontal flip: the crop follows into the new space, it is not reset (§7.1). */
export function setOrient(
  doc: EditorDocument,
  slot: DocSlot,
  orient: Orient,
  sizes: PhotoSizes,
): void {
  const photo = slot.photo_id ? sizes[slot.photo_id] : undefined;
  if (!photo) return;
  const previous = slot.source.orient;
  slot.source.crop = reorientCrop(slot.source.crop, photo, previous, orient);
  slot.source.orient = orient;
  const source = orientedSize(photo, orient);
  const turned = previous.rotate !== orient.rotate && (previous.rotate + orient.rotate) % 180 !== 0;
  if (turned) {
    // The crop swapped width and height: the slot must follow it.
    write(slot, resizeCrop({ rect: slot.rect, crop: slot.source.crop }, slot.source.crop, source,
      slot.quality_lock === "native" ? "native" : "free"));
    slot.quality_lock = slot.quality_lock === "native" ? "native" : slot.quality_lock;
  }
  afterCropChange(doc, slot, sizes);
}

export function rotateSource(doc: EditorDocument, slot: DocSlot, turns: number, sizes: PhotoSizes) {
  const rotate = (((slot.source.orient.rotate + turns * 90) % 360) + 360) % 360;
  setOrient(doc, slot, { rotate: rotate as Orient["rotate"], flip_h: slot.source.orient.flip_h },
    sizes);
}

export function flipSource(doc: EditorDocument, slot: DocSlot, sizes: PhotoSizes): void {
  setOrient(doc, slot, { ...slot.source.orient, flip_h: !slot.source.orient.flip_h }, sizes);
}

export function setRotation(slot: DocSlot, degrees: number): void {
  if (slot.quality_lock === "native" && degrees !== 0) slot.quality_lock = "no_upscale";
  slot.rotation = Math.round(Math.max(-180, Math.min(180, degrees)) * 10) / 10;
}

export function panCrop(
  _doc: EditorDocument,
  slot: DocSlot,
  dx: number,
  dy: number,
  sizes: PhotoSizes,
): void {
  const source = slotSource(slot, sizes);
  if (!source) return;
  slot.source.crop = panCropSolver(state(slot), Math.round(dx), Math.round(dy), source);
}

export function zoomCrop(
  doc: EditorDocument,
  slot: DocSlot,
  factor: number,
  sizes: PhotoSizes,
): void {
  const source = slotSource(slot, sizes);
  if (!source) return;
  write(slot, zoomCropSolver(state(slot), factor, source, slot.quality_lock));
  afterCropChange(doc, slot, sizes);
}

/**
 * Photo zoom shown by the framing panel (§7.5): `1` = the whole photo at the current crop ratio,
 * `2` = twice as big on screen (half of it visible). It is the reference the wheel zoom moves
 * along, so the slider and the wheel always agree.
 */
export const MIN_ZOOM = 1;
export const MAX_ZOOM = 8;

/** Fully zoomed-out crop: the largest crop of the current ratio inside the source. */
function zoomBase(slot: DocSlot, source: Size): Rect {
  return largestCrop(source, parseRatio(slot.source.crop_ratio, source));
}

export function photoZoom(slot: DocSlot, sizes: PhotoSizes): number | null {
  const source = slotSource(slot, sizes);
  if (!source) return null;
  const base = zoomBase(slot, source);
  return clampZoom(base.w / slot.source.crop.w);
}

export function clampZoom(zoom: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(zoom * 100) / 100));
}

/** Set the absolute zoom (slider / number field); the wheel keeps using `zoomCrop`. */
export function setPhotoZoom(
  doc: EditorDocument,
  slot: DocSlot,
  zoom: number,
  sizes: PhotoSizes,
): void {
  const source = slotSource(slot, sizes);
  if (!source) return;
  const target = zoomBase(slot, source).w / clampZoom(zoom);
  zoomCrop(doc, slot, target / slot.source.crop.w, sizes);
}

/** `fit_in_mat` re-places the slot around the new crop; `native` pushes the change to the margins. */
function afterCropChange(doc: EditorDocument, slot: DocSlot, sizes: PhotoSizes): void {
  if (doc.placement !== "fit_in_mat") return;
  if (slot.quality_lock === "native") marginsFollowSlot(doc, slot);
  else replace(doc, sizes);
}

// ---- decorations -------------------------------------------------------------------------------
export function setBands(slot: DocSlot, bands: DocSlot["bands"]): void {
  slot.bands = bands.slice(0, 3).map((band) => ({
    width: Math.max(1, Math.round(band.width)),
    color: band.color,
  }));
}

export function setShadow(slot: DocSlot, shadow: DocSlot["shadow"]): void {
  slot.shadow = shadow;
}

// ---- alternatives ------------------------------------------------------------------------------
export function applyAlternative(
  doc: EditorDocument,
  slot: DocSlot,
  alternative: Alternative,
): void {
  slot.rect = alternative.rect;
  slot.source.crop = alternative.crop;
  slot.quality_lock = alternative.quality_lock;
  if (alternative.placement) doc.placement = alternative.placement;
  if (alternative.margins) doc.margins = { ...doc.margins, ...alternative.margins };
}
