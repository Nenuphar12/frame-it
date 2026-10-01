// Every edit the editor can make to an artwork document, as pure mutations of an Immer draft.
//
// They are the only place that knows how a change propagates: editing the margins of a
// `fit_in_mat` artwork re-places the slot, editing the crop of a `native` slot re-computes the
// margins (native linking, §7.4), switching the lock repairs the slot (§7.3). Keeping them out of
// components means the store can replay them for undo/redo and the rules stay testable.
import { current } from "immer";

import type { FrameStyle, Layout } from "@/api/client";
import {
  CENTER,
  applyCropRatio,
  applyLock,
  panCrop as panCropSolver,
  resizeCrop,
  resizeSlot,
  zoomCrop as zoomCropSolver,
  type Anchor,
  type SlotState,
} from "@/editor/core/constraints.ts";
import type { Alternative } from "@/editor/core/alternatives.ts";
import {
  applyComposition,
  captionStyleOf,
  roomy,
  solveStrict,
  splits,
  type Composition,
  type Recipe,
} from "@/editor/core/composition.ts";
import {
  relayout,
  restyle,
  type LayoutDocument as CoreLayout,
  type StyleDocument as CoreStyle,
} from "@/editor/core/templates.ts";
import {
  align,
  distribute,
  newSlotRect,
  newSlotSize,
  type Axis,
  type Edge,
} from "@/editor/core/arrange.ts";
import type {
  DocCaption,
  DocMargins,
  DocSlot,
  EditorDocument,
  Placement,
} from "@/editor/core/document.ts";
import {
  orientedSize,
  parseRatio,
  reorientCrop,
  type Orient,
  type Rect,
  type Size,
} from "@/editor/core/geometry.ts";
import {
  availableArea,
  fill,
  fillSlot,
  fitInMat,
  fitSlot,
  largestCrop,
  marginsForSlot,
  ratioLabel,
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

export function setPlacement(doc: EditorDocument, placement: Placement, sizes: PhotoSizes): void {
  if (doc.slots.length !== 1) return; // multi-slot artworks are always `manual`
  doc.placement = placement;
  if (placement === "manual") return; // switching to manual keeps the current geometry (§7.4)
  replace(doc, sizes);
}

/** A frame style's document, as `GET /frame-styles` sends it (every field optional in OpenAPI). */
export type StyleDocument = FrameStyle["document"];
/** A layout's document: a recipe and its parameters (`GET /layouts`, docs/templates.md §2). */
export type LayoutApiDocument = Layout["document"];

export function setMatColor(doc: EditorDocument, color: string): void {
  doc.mat.color = color;
}

export function setTexture(doc: EditorDocument, id: string | null, strength: number): void {
  doc.mat.texture = id === null ? null : { id, strength };
}

/** The frame's shadow on the artwork; `null` removes it. Never a free-form edit (§3.7). */
export function setEdgeShadow(doc: EditorDocument, shadow: EditorDocument["edge_shadow"]): void {
  doc.edge_shadow = shadow;
}

/** Fill in a style document's optional fields, falling back to the artwork's own look. */
function normalizeStyle(style: StyleDocument, doc: EditorDocument): CoreStyle {
  const mat = style.mat;
  const defaults = style.slot_defaults;
  const typography = style.caption_defaults;
  const caption = captionStyleOf(doc);
  return {
    mat: {
      color: mat?.color ?? doc.mat.color,
      texture: mat?.texture ? { ...mat.texture } : null,
    },
    margins: style.margins ?? doc.margins,
    slot_defaults: {
      bands: (defaults?.bands ?? []).map((band) => ({ ...band, bevel: band.bevel ?? false })),
      shadow: defaults?.shadow ? { ...defaults.shadow } : null,
      quality_lock: defaults?.quality_lock ?? "no_upscale",
    },
    edge_shadow: style.edge_shadow ? { ...style.edge_shadow } : null,
    caption_defaults: {
      font: typography?.font ?? caption.font,
      weight: typography?.weight ?? caption.weight,
      size: typography?.size ?? caption.size,
      color: typography?.color ?? caption.color,
      letter_spacing: typography?.letter_spacing ?? caption.letter_spacing,
    },
  };
}

/** Fill in a layout document's optional fields (same reason as `normalizeStyle`). */
function normalizeLayout(layout: LayoutApiDocument): CoreLayout {
  return {
    recipe: layout.recipe,
    balance: layout.balance ?? null,
    weights: (layout.weights ?? []).map((entry) => (entry ? [...entry] : null)),
    outer: { x: layout.outer?.x ?? 120, y: layout.outer?.y ?? 120 },
    gutter: { x: layout.gutter?.x ?? 80, y: layout.gutter?.y ?? 80 },
    format: layout.format ?? "fill",
    cell_formats: [...(layout.cell_formats ?? [])],
    border: layout.border ? { ...layout.border, bevel: layout.border.bevel ?? false } : null,
    caption_place: layout.caption_place ?? "none",
    caption_align: layout.caption_align ?? "center",
  };
}

/** Write a whole document back into the draft (the template helpers are pure functions). */
function replaceDocument(doc: EditorDocument, next: EditorDocument): void {
  doc.mat = next.mat;
  doc.placement = next.placement;
  doc.margins = next.margins;
  doc.composition = next.composition;
  doc.slots = next.slots;
  doc.captions = next.captions;
  doc.edge_shadow = next.edge_shadow;
}

/**
 * Re-dress the artwork in a frame style (Gallery recessed, Linen, …) without touching its layout.
 *
 * The rule lives in `editor/core/templates.ts`, mirrored by `domain/templates.py`: the editor and
 * a server-side push update must dress an artwork identically (docs/templates.md §5).
 */
export function applyStyle(
  doc: EditorDocument,
  style: StyleDocument,
  recipes: readonly Recipe[],
  sizes: PhotoSizes,
): void {
  const snapshot = current(doc);
  replaceDocument(
    doc,
    restyle(snapshot, normalizeStyle(style, snapshot), attachedRecipe(doc, recipes), sizes),
  );
}

/**
 * Apply a saved layout: its recipe and parameters become the artwork's block, then it re-solves.
 *
 * A detached artwork is re-attached — picking a layout is an explicit "lay this out for me", the
 * same move as §5's Re-apply layout with someone else's parameters.
 */
export function applyLayout(
  doc: EditorDocument,
  layout: LayoutApiDocument,
  recipes: readonly Recipe[],
  sizes: PhotoSizes,
): void {
  const recipe = recipes.find((entry) => entry.id === layout.recipe);
  if (!recipe) return;
  replaceDocument(doc, relayout(current(doc), normalizeLayout(layout), recipe, sizes));
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
  write(
    slot,
    applyCropRatio(state(slot), parseRatio(cropRatio, source), source, slot.quality_lock),
  );
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
    write(
      slot,
      resizeCrop(
        { rect: slot.rect, crop: slot.source.crop },
        slot.source.crop,
        source,
        slot.quality_lock === "native" ? "native" : "free",
      ),
    );
    slot.quality_lock = slot.quality_lock === "native" ? "native" : slot.quality_lock;
  }
  afterCropChange(doc, slot, sizes);
}

export function rotateSource(doc: EditorDocument, slot: DocSlot, turns: number, sizes: PhotoSizes) {
  const rotate = (((slot.source.orient.rotate + turns * 90) % 360) + 360) % 360;
  setOrient(
    doc,
    slot,
    { rotate: rotate as Orient["rotate"], flip_h: slot.source.orient.flip_h },
    sizes,
  );
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

/**
 * Zoom the photo inside its slot by `factor` (> 1 shows more of it) — the wheel and `+` / `-`.
 *
 * It goes through the **same bounded scale as the slider** (`MIN_ZOOM`…`MAX_ZOOM`): an unbounded
 * wheel used to shrink the crop a few pixels wide, where rounding destroys its aspect and the slot
 * follows it (remarks.md #2). Scrolling can no longer take the document anywhere the slider cannot.
 */
export function zoomCrop(
  doc: EditorDocument,
  slot: DocSlot,
  factor: number,
  sizes: PhotoSizes,
): void {
  const source = slotSource(slot, sizes);
  if (!source) return;
  setPhotoZoom(doc, slot, zoomBase(slot, source).w / slot.source.crop.w / factor, sizes);
}

/** Apply a zoom factor to the crop, with the lock the current mode calls for. */
function applyZoom(
  doc: EditorDocument,
  slot: DocSlot,
  factor: number,
  source: Size,
  sizes: PhotoSizes,
): void {
  // Under an attached block the cell owns the rect: zoom with the lock off so the constraint
  // solver cannot shrink the slot, then put the §3.7 lock back (`relock`).
  const parametric = cellOwnsRect(doc);
  const lock = parametric ? "free" : slot.quality_lock;
  write(slot, zoomCropSolver(state(slot), factor, source, lock));
  if (parametric) relock(slot);
  else afterCropChange(doc, slot, sizes);
}

/** True while a composition — not the slots — decides the geometry (§5). */
export function cellOwnsRect(doc: EditorDocument): boolean {
  return doc.composition !== null && !doc.composition.detached;
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

/**
 * Zoom at which the photo is shown pixel-for-pixel (scale 1, §7.2) — `null` when the cell is
 * bigger than the photo, where "native" simply does not exist without upscaling.
 */
export function nativeZoom(slot: DocSlot, sizes: PhotoSizes): number | null {
  const source = slotSource(slot, sizes);
  if (!source) return null;
  const zoom = zoomBase(slot, source).w / slot.rect.w;
  return zoom >= MIN_ZOOM && zoom <= MAX_ZOOM ? Math.round(zoom * 100) / 100 : null;
}

/**
 * Frame the photo pixel-for-pixel inside its cell: the crop becomes exactly the rect, centred on
 * the current one. Going through the zoom slider instead lands a pixel off (the zoom is rounded
 * to 1/100), which shows up as "Downscaled 100 %" — the one tier the badge must get right.
 *
 * A photo too small to fill the cell cannot be native: the caller offers the action only when
 * `nativeZoom` says it exists.
 */
export function setNativeFraming(doc: EditorDocument, slot: DocSlot, sizes: PhotoSizes): void {
  const source = slotSource(slot, sizes);
  if (!source || source.w < slot.rect.w || source.h < slot.rect.h) return;
  write(slot, applyLock(state(slot), "native", source));
  if (cellOwnsRect(doc)) relock(slot); // the cell keeps the rect; `native` is a framing, not a lock
}

export function clampZoom(zoom: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(zoom * 100) / 100));
}

/** Set the absolute zoom — the one door to the crop's size, for the slider and the wheel alike. */
export function setPhotoZoom(
  doc: EditorDocument,
  slot: DocSlot,
  zoom: number,
  sizes: PhotoSizes,
): void {
  const source = slotSource(slot, sizes);
  if (!source) return;
  const target = zoomBase(slot, source).w / clampZoom(zoom);
  applyZoom(doc, slot, target / slot.source.crop.w, source, sizes);
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
    bevel: band.bevel,
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

// ---- multi-slot compositions (Phase 6) ---------------------------------------------------------
/** Hard limits of the document schema (`domain/document.py`). */
export const MAX_SLOTS = 32;
export const MAX_CAPTIONS = 32;
/** Canvas coordinates and sizes are bounded (`MAX_COORD`): the editor never writes past them. */
export const MAX_COORD = 20_000;

const coord = (value: number) => Math.max(-MAX_COORD, Math.min(MAX_COORD, Math.round(value)));
const length = (value: number) => Math.max(1, Math.min(MAX_COORD, Math.round(value)));

/** Next free `s_N` / `c_N` id (document ids are `[A-Za-z0-9_-]{1,64}`). */
function nextId(prefix: string, taken: readonly string[]): string {
  let n = taken.length + 1;
  while (taken.includes(`${prefix}${n}`)) n += 1;
  return `${prefix}${n}`;
}

/** A composition needs `manual` placement (a document rule): switching keeps the geometry. */
function goManual(doc: EditorDocument): void {
  doc.placement = "manual";
}

/** Where new slots are dropped and where "fit in the area" works from. */
function area(doc: EditorDocument): Rect {
  return availableArea(doc.margins, { w: doc.canvas.width, h: doc.canvas.height });
}

/**
 * Add a slot showing `photoId` (or an empty one). The document becomes `manual` as soon as it
 * holds more than one slot; decorations are inherited from the front-most slot so a new photo
 * matches the others.
 */
export function addSlot(
  doc: EditorDocument,
  photoId: string | null,
  sizes: PhotoSizes,
  at: { x: number; y: number } | null = null,
): string | null {
  if (doc.slots.length >= MAX_SLOTS) return null;
  if (doc.slots.length >= 1) goManual(doc);
  const source = photoId ? (sizes[photoId] ?? null) : null;
  const target = area(doc);
  const size = newSlotSize(target, source);
  // A photo dropped on the canvas lands where it was dropped; the panel's "add" cascades.
  const rect = at
    ? { x: coord(at.x - size.w / 2), y: coord(at.y - size.h / 2), w: size.w, h: size.h }
    : newSlotRect(
        doc.slots.map((slot) => slot.rect),
        target,
        size,
      );
  const model = doc.slots[doc.slots.length - 1];
  const placed = source
    ? fitSlot(rect, source, "no_upscale")
    : { rect, crop: { x: 0, y: 0, w: rect.w, h: rect.h }, quality_lock: "free" as QualityLock };
  const slot: DocSlot = {
    id: nextId(
      "s_",
      doc.slots.map((s) => s.id),
    ),
    photo_id: photoId,
    rect: placed.rect,
    rotation: 0,
    source: {
      orient: { rotate: 0, flip_h: false },
      crop: placed.crop,
      crop_ratio: source ? "original" : "free",
    },
    quality_lock: placed.quality_lock,
    bands: model ? model.bands.map((band) => ({ ...band })) : [],
    shadow: model?.shadow ? { ...model.shadow } : null,
  };
  doc.slots.push(slot); // last = front-most (array order is the z-order)
  return slot.id;
}

export function removeSlots(doc: EditorDocument, slotIds: readonly string[]): void {
  doc.slots = doc.slots.filter((slot) => !slotIds.includes(slot.id));
  if (doc.slots.length !== 1 && doc.placement !== "manual") goManual(doc);
}

/** Put a photo in a slot (or empty it with `null`), re-framing it the way the placement implies. */
export function setSlotPhoto(
  doc: EditorDocument,
  slot: DocSlot,
  photoId: string | null,
  sizes: PhotoSizes,
): void {
  // A slot without a photo carries a `free` lock (nothing constrains a placeholder): a slot
  // being filled takes the default lock back, and `fill_slot` relaxes it if the photo is small.
  const wasEmpty = slot.photo_id === null;
  slot.photo_id = photoId;
  slot.source.orient = { rotate: 0, flip_h: false };
  if (wasEmpty && photoId) slot.quality_lock = "no_upscale";
  const source = photoId ? (sizes[photoId] ?? null) : null;
  if (!source) {
    slot.source.crop = { x: 0, y: 0, w: slot.rect.w, h: slot.rect.h };
    slot.source.crop_ratio = "free";
    slot.quality_lock = "free";
    return;
  }
  if (doc.placement !== "manual") {
    // Single-slot artwork: the whole photo, re-placed inside the margins (§7.4).
    slot.source.crop = { x: 0, y: 0, w: source.w, h: source.h };
    slot.source.crop_ratio = "original";
    replace(doc, sizes);
    return;
  }
  // Composition: the slot keeps its shape, the photo is cropped to it.
  write(slot, fillSlot(slot.rect, source, slot.quality_lock));
  slot.source.crop_ratio = ratioLabel(slot.rect.w, slot.rect.h);
}

/** Exchange the photos of two slots; each one is re-cropped to the shape it lands in. */
export function swapPhotos(
  doc: EditorDocument,
  firstId: string,
  secondId: string,
  sizes: PhotoSizes,
): void {
  const first = doc.slots.find((slot) => slot.id === firstId);
  const second = doc.slots.find((slot) => slot.id === secondId);
  if (!first || !second || first === second) return;
  const photo = first.photo_id;
  const orient = { ...first.source.orient };
  setSlotPhoto(doc, first, second.photo_id, sizes);
  first.source.orient = { ...second.source.orient };
  setSlotPhoto(doc, second, photo, sizes);
  second.source.orient = orient;
}

// ---- free-form geometry (manual placement) -----------------------------------------------------
/**
 * `size` placed so that the anchor point of `rect` does not move — in the slot's own frame, so a
 * rotated slot pivots around the handle the user is holding.
 */
function anchored(rect: Rect, size: Size, anchor: Anchor, rotation: number): Rect {
  const radians = (rotation * Math.PI) / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  const rotate = (x: number, y: number) => ({ x: x * cos - y * sin, y: x * sin + y * cos });
  const center = { x: rect.x + rect.w / 2, y: rect.y + rect.h / 2 };
  const before = rotate((anchor[0] - 0.5) * rect.w, (anchor[1] - 0.5) * rect.h);
  const after = rotate((anchor[0] - 0.5) * size.w, (anchor[1] - 0.5) * size.h);
  return {
    x: coord(center.x + before.x - after.x - size.w / 2),
    y: coord(center.y + before.y - after.y - size.h / 2),
    w: size.w,
    h: size.h,
  };
}

export function moveSlot(slot: DocSlot, dx: number, dy: number): void {
  slot.rect = { ...slot.rect, x: coord(slot.rect.x + dx), y: coord(slot.rect.y + dy) };
}

export function setSlotPosition(slot: DocSlot, x: number, y: number): void {
  slot.rect = { ...slot.rect, x: coord(x), y: coord(y) };
}

/**
 * Resize a slot (transform handles or the size fields). The constraint solver decides what the
 * crop does (§7.3) and `anchor` is the point of the current rect the drag keeps fixed, so the
 * opposite edge is the one that follows the pointer.
 */
export function resizeSlotTo(
  doc: EditorDocument,
  slot: DocSlot,
  requested: Size,
  anchor: Anchor,
  sizes: PhotoSizes,
): void {
  const size = { w: length(requested.w), h: length(requested.h) };
  const before = slot.rect;
  const source = slotSource(slot, sizes);
  if (!source) {
    // Empty slot: nothing to keep consistent, the crop is only a placeholder of the same shape.
    slot.rect = { ...anchored(before, size, anchor, slot.rotation) };
    slot.source.crop = { x: 0, y: 0, w: slot.rect.w, h: slot.rect.h };
    return;
  }
  const placed = resizeSlot(state(slot), size, source, slot.quality_lock, anchor);
  write(slot, placed);
  // The solver anchors an axis-aligned rect; a rotated slot must keep its *rotated* anchor point
  // where it is, or dragging a corner walks the slot across the canvas.
  slot.rect = anchored(before, { w: placed.rect.w, h: placed.rect.h }, anchor, slot.rotation);
  if (doc.placement !== "manual") marginsFollowSlot(doc, slot);
}

/** Slot shrunk to the photo's shape inside its current rect ("fit slot to photo"). */
export function fitSlotToPhoto(doc: EditorDocument, slot: DocSlot, sizes: PhotoSizes): void {
  const source = slotSource(slot, sizes);
  if (!source) return;
  write(slot, fitSlot(slot.rect, source, slot.quality_lock));
  slot.source.crop_ratio = "original";
  if (doc.placement !== "manual") marginsFollowSlot(doc, slot);
}

/** Photo cropped to the slot's shape ("fill slot"). */
export function fillSlotWithPhoto(doc: EditorDocument, slot: DocSlot, sizes: PhotoSizes): void {
  const source = slotSource(slot, sizes);
  if (!source) return;
  write(slot, fillSlot(slot.rect, source, slot.quality_lock));
  slot.source.crop_ratio = ratioLabel(slot.rect.w, slot.rect.h);
  if (doc.placement !== "manual") marginsFollowSlot(doc, slot);
}

// ---- z-order (array order, first = back-most) --------------------------------------------------
export function moveSlotInOrder(doc: EditorDocument, slotId: string, delta: number): void {
  const from = doc.slots.findIndex((slot) => slot.id === slotId);
  if (from < 0) return;
  const to = Math.max(0, Math.min(doc.slots.length - 1, from + delta));
  if (to === from) return;
  const [slot] = doc.slots.splice(from, 1);
  if (slot) doc.slots.splice(to, 0, slot);
}

/** List drag & drop: move the slot at `from` to index `to` (both in document order). */
export function reorderSlots(doc: EditorDocument, from: number, to: number): void {
  if (from === to || from < 0 || from >= doc.slots.length) return;
  const [slot] = doc.slots.splice(from, 1);
  if (slot) doc.slots.splice(Math.max(0, Math.min(doc.slots.length, to)), 0, slot);
}

// ---- arranging a selection ---------------------------------------------------------------------
function selectedSlots(doc: EditorDocument, ids: readonly string[]): DocSlot[] {
  return doc.slots.filter((slot) => ids.includes(slot.id));
}

export function alignSlots(doc: EditorDocument, ids: readonly string[], edge: Edge): void {
  const slots = selectedSlots(doc, ids);
  if (slots.length < 2) return;
  const rects = align(
    slots.map((slot) => slot.rect),
    edge,
  );
  slots.forEach((slot, index) => {
    const rect = rects[index];
    if (rect) slot.rect = { ...slot.rect, x: coord(rect.x), y: coord(rect.y) };
  });
}

export function distributeSlots(doc: EditorDocument, ids: readonly string[], axis: Axis): void {
  const slots = selectedSlots(doc, ids);
  if (slots.length < 3) return;
  const rects = distribute(
    slots.map((slot) => slot.rect),
    axis,
  );
  slots.forEach((slot, index) => {
    const rect = rects[index];
    if (rect) slot.rect = { ...slot.rect, x: coord(rect.x), y: coord(rect.y) };
  });
}

/**
 * Give every selected slot the size of the primary one (the last picked).
 *
 * A slot's shape is tied to its crop, so most of them cannot take the reference size exactly:
 * each one takes the largest size *inside* the reference box instead. Asking the solver for the
 * reference size directly would use its cover semantics (§7.3) and make slots **larger** than
 * the reference, which is the opposite of what the command promises.
 */
export function sameSizeSlots(
  doc: EditorDocument,
  ids: readonly string[],
  primaryId: string,
  sizes: PhotoSizes,
): void {
  const slots = selectedSlots(doc, ids);
  const model = slots.find((slot) => slot.id === primaryId);
  if (slots.length < 2 || !model) return;
  const box = { w: model.rect.w, h: model.rect.h };
  for (const slot of slots) {
    if (slot === model) continue;
    const scale = Math.min(box.w / slot.rect.w, box.h / slot.rect.h);
    resizeSlotTo(
      doc,
      slot,
      { w: Math.max(1, slot.rect.w * scale), h: Math.max(1, slot.rect.h * scale) },
      CENTER,
      sizes,
    );
  }
}

/** Copy the bands, the shadow and the quality lock of one slot onto the others. */
export function applyDecorations(
  doc: EditorDocument,
  sourceId: string,
  ids: readonly string[],
  sizes: PhotoSizes,
): void {
  const model = doc.slots.find((slot) => slot.id === sourceId);
  if (!model) return;
  for (const slot of selectedSlots(doc, ids)) {
    if (slot === model) continue;
    slot.bands = model.bands.map((band) => ({ ...band }));
    slot.shadow = model.shadow ? { ...model.shadow } : null;
    setLock(doc, slot, model.quality_lock, sizes);
  }
}

// ---- captions ----------------------------------------------------------------------------------
export const CAPTION_DEFAULTS = {
  font: "cormorant-garamond",
  weight: 500,
  size: 64,
  color: "#3A3A3A",
  letter_spacing: 0.02,
  anchor: "middle" as const,
  rotation: 0,
};

/** New caption, centred in the bottom margin of the canvas (where a mount caption goes). */
export function addCaption(
  doc: EditorDocument,
  text: string,
  defaults: Partial<DocCaption> = {},
): string | null {
  if (doc.captions.length >= MAX_CAPTIONS) return null;
  const bottom = doc.margins.bottom;
  const caption: DocCaption = {
    ...CAPTION_DEFAULTS,
    ...defaults,
    id: nextId(
      "c_",
      doc.captions.map((c) => c.id),
    ),
    text,
    x: Math.round(doc.canvas.width / 2),
    y: doc.canvas.height - Math.round(bottom > 120 ? bottom / 2 : 96),
  };
  doc.captions.push(caption);
  return caption.id;
}

export function updateCaption(
  doc: EditorDocument,
  captionId: string,
  patch: Partial<DocCaption>,
): void {
  const caption = doc.captions.find((item) => item.id === captionId);
  if (!caption) return;
  Object.assign(caption, patch);
  caption.x = coord(caption.x);
  caption.y = coord(caption.y);
  caption.size = Math.max(4, Math.min(1000, Math.round(caption.size)));
  caption.rotation = Math.round(Math.max(-180, Math.min(180, caption.rotation)) * 10) / 10;
}

export function moveCaption(doc: EditorDocument, captionId: string, dx: number, dy: number): void {
  const caption = doc.captions.find((item) => item.id === captionId);
  if (!caption) return;
  caption.x = coord(caption.x + dx);
  caption.y = coord(caption.y + dy);
}

export function removeCaption(doc: EditorDocument, captionId: string): void {
  doc.captions = doc.captions.filter((caption) => caption.id !== captionId);
}

// ---- parametric compositions (Phase 7) ---------------------------------------------------------
/**
 * The recipe of an **attached** block: the cells own the geometry then, so any operation that
 * would move a slot has to go through `resolveComposition` instead of writing a rect.
 */
export function attachedRecipe(doc: EditorDocument, recipes: readonly Recipe[]): Recipe | null {
  const block = doc.composition;
  if (!block || block.detached) return null;
  return recipes.find((recipe) => recipe.id === block.recipe) ?? null;
}

/**
 * The balance to keep when the recipe changes: recipes declare **different** ranges (`hero-left`
 * is 0.40–0.75, `hero-right` 0.25–0.60), so carrying the value over unclamped would build a
 * document the server rejects with `balance_out_of_range` (invariant 11).
 */
export function balanceFor(recipe: Recipe, balance: number | null): number | null {
  if (!recipe.balance || balance === null) return null;
  return Math.min(recipe.balance.max, Math.max(recipe.balance.min, balance));
}

/**
 * Re-solve the block and write §3.7's table into the draft — the client half of the server
 * authority: the editor previews exactly what `PUT document` will store (same function, mirrored).
 */
export function resolveComposition(
  doc: EditorDocument,
  recipes: readonly Recipe[],
  sizes: PhotoSizes,
): void {
  const recipe = attachedRecipe(doc, recipes);
  if (!recipe) return;
  const next = applyComposition(current(doc), recipe, sizes);
  doc.placement = next.placement;
  doc.margins = next.margins;
  doc.slots = next.slots;
  doc.captions = next.captions;
}

/** Merge a patch into the block (the panel's controls) and re-solve. */
export function setComposition(
  doc: EditorDocument,
  patch: Partial<Composition>,
  recipes: readonly Recipe[],
  sizes: PhotoSizes,
): void {
  if (!doc.composition) return;
  doc.composition = { ...doc.composition, ...patch };
  resolveComposition(doc, recipes, sizes);
}

/**
 * Give a hand-built artwork a composition (§6.1: an artwork without a block shows the picker).
 *
 * The mat, the photos and their order are kept; everything the block owns is re-derived. A single
 * photo starts on `original` — the whole photo in the mat, today's `fit_in_mat` — and several on
 * `fill`, the same defaults `POST /artworks` applies server-side (§7).
 */
export function attachComposition(
  doc: EditorDocument,
  recipe: Recipe,
  recipes: readonly Recipe[],
  sizes: PhotoSizes,
): void {
  const previous = doc.composition;
  // The block owns the captions from now on (§3.7), so a caption the artwork already had has to
  // move into it — dropping the user's text on the way in would be the worst kind of surprise.
  const existing = doc.captions[0];
  doc.composition = {
    recipe: recipe.id,
    balance: previous?.balance ?? null,
    // Indexed by the recipe's splits: another recipe's entries would describe other divisions.
    weights: previous?.recipe === recipe.id ? previous.weights : [],
    outer: previous ? { ...previous.outer } : { x: 120, y: 120 },
    gutter: previous ? { ...previous.gutter } : { x: 80, y: 80 },
    format: previous?.format ?? (recipe.count === 1 ? "original" : "fill"),
    cell_formats: previous ? previous.cell_formats.slice(0, recipe.count) : [],
    border: previous?.border ? { ...previous.border } : null,
    caption: previous
      ? { ...previous.caption }
      : { text: existing?.text ?? "", place: existing ? "below" : "none", align: "center" },
    detached: false,
  };
  doc.composition.balance = balanceFor(recipe, previous?.balance ?? null);
  resolveComposition(doc, recipes, sizes);
}

/**
 * Keep the block valid when the number of photos changes (§4.4).
 *
 * The count comes from the photos, so a slot added or removed in the Advanced editor has to pick a
 * recipe again: the same family when one exists for the new count, else that count's first entry.
 * Beyond the catalogue (7 photos and up) the slots become the truth — the block is memory (§5),
 * which is also what keeps the server from rejecting the save with `recipe_slot_count`.
 */
export function recipeFollowsPhotoCount(
  doc: EditorDocument,
  recipes: readonly Recipe[],
  sizes: PhotoSizes,
): void {
  const block = doc.composition;
  if (!block || block.detached) return;
  const count = doc.slots.length;
  const active = recipes.find((recipe) => recipe.id === block.recipe);
  if (active && active.count === count) return;
  const family = active ? active.id.split("-").slice(1).join("-") : "";
  const sameCount = recipes.filter((recipe) => recipe.count === count);
  const next = sameCount.find((recipe) => recipe.id.split("-").slice(1).join("-") === family);
  const chosen = next ?? sameCount[0];
  if (!chosen) {
    block.detached = true;
    return;
  }
  block.recipe = chosen.id;
  block.balance = balanceFor(chosen, block.balance);
  block.weights = []; // they are indexed by the old recipe's splits
  // The per-cell overrides are positional: a shorter recipe drops the ones that no longer exist.
  block.cell_formats = block.cell_formats.slice(0, count);
  resolveComposition(doc, recipes, sizes);
}

/**
 * Set how one division of a Fill layout shares its span out (§6.5); `null` gives it back to the
 * recipe.
 *
 * `split` is the depth-first index `composition.weights` uses. The root of a recipe that declares
 * a balance is written as `balance`, clamped to the recipe's range — one division, one name, and
 * the only value the server accepts there. A change that would leave a cell under `MIN_CELL` is
 * dropped: the solver would otherwise relax the gutters (§3.6) and the picture would stop
 * matching the sliders.
 */
export function setSplitShares(
  doc: EditorDocument,
  split: number,
  shares: readonly number[] | null,
  recipes: readonly Recipe[],
  sizes: PhotoSizes,
): void {
  const recipe = attachedRecipe(doc, recipes);
  const block = doc.composition;
  if (!recipe || !block) return;
  const node = splits(recipe.tree)[split];
  if (!node || (shares !== null && shares.length !== node.children.length)) return;
  const patch: Partial<Composition> = {};
  if (split === 0 && recipe.balance) {
    const total = shares ? shares.reduce((sum, share) => sum + share, 0) : 0;
    patch.balance =
      shares === null || total <= 0
        ? null
        : balanceFor(recipe, Math.round(((shares[0] ?? 0) / total) * 1000) / 1000);
  } else {
    const next: (number[] | null)[] = block.weights.map((entry) => (entry ? [...entry] : null));
    while (next.length <= split) next.push(null);
    next[split] = shares === null ? null : [...shares];
    while (next.length > 0 && next[next.length - 1] === null) next.pop();
    patch.weights = next;
  }
  const candidate = { ...current(block), ...patch };
  const photoSizes = doc.slots.map((slot) =>
    slot.photo_id ? (sizes[slot.photo_id] ?? null) : null,
  );
  const captionSize = captionStyleOf(current(doc)).size;
  const fits = (composition: Composition) =>
    roomy(solveStrict(recipe, composition, photoSizes, captionSize));
  if (shares !== null && !fits(candidate) && fits(current(block))) return;
  setComposition(doc, patch, recipes, sizes);
}

/**
 * A free-form edit just happened: the slots become the truth and the block is kept as memory (§5).
 *
 * The rule for calling this is mechanical — **an edit detaches exactly when `apply` would
 * overwrite it**. Moving, resizing or rotating a slot, its bands, lock, crop ratio, the margins,
 * the placement and the captions' geometry are all re-derived by §3.7, so a hand-made version of
 * them would silently disappear on the next save. A shadow, the mat and a caption's typography are
 * *not* touched by `apply`, so they round-trip and must not cost the user their layout link.
 */
export function detach(doc: EditorDocument): void {
  if (doc.composition && !doc.composition.detached) doc.composition.detached = true;
}

/**
 * "Re-apply layout" (§5): re-solve from the remembered parameters and clear the flag.
 *
 * One `store.edit()` patch like any other, so `⌘Z` brings the hand-made geometry straight back —
 * which is what makes the action safe to offer as a single button.
 */
export function reapplyLayout(
  doc: EditorDocument,
  recipes: readonly Recipe[],
  sizes: PhotoSizes,
): void {
  if (!doc.composition) return;
  doc.composition.detached = false;
  recipeFollowsPhotoCount(doc, recipes, sizes);
  resolveComposition(doc, recipes, sizes);
}

/**
 * The lock of a slot whose rect belongs to a cell: `no_upscale` unless the framing upscales — the
 * §3.7 rule. A reframe must never drag the rect, and under `no_upscale` the constraint solver
 * shrinks the slot as soon as the crop gets smaller than it (§7.3), so Simple reframes with the
 * lock off and restores it here.
 */
export function relock(slot: DocSlot): void {
  slot.quality_lock =
    slot.rect.w > slot.source.crop.w || slot.rect.h > slot.source.crop.h ? "free" : "no_upscale";
}
