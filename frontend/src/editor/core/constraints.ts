// Editor constraint solver — mirror of backend/src/frame_it/domain/constraints.py.
// Spec: docs/geometry-and-quality.md §7.3. Parity: conformance/geometry/constraints.json.
//
// Two invariants are never broken, whatever the user drags: `rect` and `crop` keep the same
// aspect ratio, and the quality lock holds (`native` ⇒ same size, `no_upscale` ⇒ rect ≤ crop).
import { aspectConsistent, roundHalfEven, type Rect, type Size } from "./geometry.ts";
import { cropCenter, largestCrop, type QualityLock, type SlotPlacement } from "./placement.ts";

export const MIN_SIZE = 1;
export const CENTER: Anchor = [0.5, 0.5];

/** Point of the rect that stays fixed while it is resized (0,0 = top-left, 0.5,0.5 = centre). */
export type Anchor = [number, number];

export interface SlotState {
  rect: Rect;
  crop: Rect;
}

export function slotScale(state: SlotState): number {
  return Math.max(state.rect.w / state.crop.w, state.rect.h / state.crop.h);
}

function anchored(rect: Rect, size: Size, anchor: Anchor): Rect {
  return {
    x: roundHalfEven(rect.x + anchor[0] * (rect.w - size.w)),
    y: roundHalfEven(rect.y + anchor[1] * (rect.h - size.h)),
    w: size.w,
    h: size.h,
  };
}

/** Smallest size with `content`'s aspect that covers `requested`. */
function cover(requested: Size, content: Size): Size {
  const scale = Math.max(requested.w / content.w, requested.h / content.h);
  return {
    w: Math.max(MIN_SIZE, roundHalfEven(content.w * scale)),
    h: Math.max(MIN_SIZE, roundHalfEven(content.h * scale)),
  };
}

/** Crop of (at most) `size`, centred on `around`'s centre and kept inside the source. */
function cropOfSize(size: Size, source: Size, around: Rect): Rect {
  const w = Math.max(MIN_SIZE, Math.min(size.w, source.w));
  const h = Math.max(MIN_SIZE, Math.min(size.h, source.h));
  const [cx, cy] = cropCenter(around);
  return {
    x: Math.min(Math.max(0, roundHalfEven(cx - w / 2)), source.w - w),
    y: Math.min(Math.max(0, roundHalfEven(cy - h / 2)), source.h - h),
    w,
    h,
  };
}

/** Crop kept inside the source, at least 1×1 (the size is reduced before the position moves). */
export function clampCrop(crop: Rect, source: Size): Rect {
  const w = Math.max(MIN_SIZE, Math.min(crop.w, source.w));
  const h = Math.max(MIN_SIZE, Math.min(crop.h, source.h));
  return {
    x: Math.min(Math.max(0, crop.x), source.w - w),
    y: Math.min(Math.max(0, crop.y), source.h - h),
    w,
    h,
  };
}

/** Resolve a slot resize (drag of a slot handle) under `lock`. */
export function resizeSlot(
  state: SlotState,
  requested: Size,
  source: Size,
  lock: QualityLock,
  anchor: Anchor = CENTER,
): SlotPlacement {
  let crop = state.crop;
  let wanted = cover(requested, { w: crop.w, h: crop.h });
  if (lock === "native") {
    crop = cropOfSize(wanted, source, crop);
    return {
      rect: anchored(state.rect, { w: crop.w, h: crop.h }, anchor),
      crop,
      quality_lock: lock,
    };
  }
  if (lock === "no_upscale" && (wanted.w > crop.w || wanted.h > crop.h)) {
    const grown = largestCrop(
      { w: Math.min(wanted.w, source.w), h: Math.min(wanted.h, source.h) },
      crop.w / crop.h,
    );
    crop = cropOfSize({ w: grown.w, h: grown.h }, source, crop);
    wanted = { w: Math.min(wanted.w, crop.w), h: Math.min(wanted.h, crop.h) };
  }
  return { rect: anchored(state.rect, wanted, anchor), crop, quality_lock: lock };
}

/** Resolve a crop change (crop handles, pan, zoom) under `lock`. */
export function resizeCrop(
  state: SlotState,
  requested: Rect,
  source: Size,
  lock: QualityLock,
): SlotPlacement {
  let crop = clampCrop(requested, source);
  if (lock === "native") {
    return {
      rect: anchored(state.rect, { w: crop.w, h: crop.h }, CENTER),
      crop,
      quality_lock: lock,
    };
  }
  if (lock === "no_upscale" && (crop.w < state.rect.w || crop.h < state.rect.h)) {
    const wanted = cover({ w: state.rect.w, h: state.rect.h }, { w: crop.w, h: crop.h });
    crop = cropOfSize(wanted, source, crop);
    if (crop.w < state.rect.w || crop.h < state.rect.h) {
      return {
        rect: anchored(state.rect, { w: crop.w, h: crop.h }, CENTER),
        crop,
        quality_lock: lock,
      };
    }
    return { rect: state.rect, crop, quality_lock: lock };
  }
  if (aspectConsistent(state.rect.w, state.rect.h, crop.w, crop.h)) {
    return { rect: state.rect, crop, quality_lock: lock };
  }
  const scale = slotScale(state);
  const size = {
    w: Math.max(MIN_SIZE, roundHalfEven(crop.w * scale)),
    h: Math.max(MIN_SIZE, roundHalfEven(crop.h * scale)),
  };
  return { rect: anchored(state.rect, size, CENTER), crop, quality_lock: lock };
}

/** Move the crop inside the source (the slot never moves): the photo pans inside the slot. */
export function panCrop(state: SlotState, dx: number, dy: number, source: Size): Rect {
  const { x, y, w, h } = state.crop;
  return clampCrop({ x: x + dx, y: y + dy, w, h }, source);
}

/**
 * Zoom the photo inside the slot: `factor > 1` shows more of it, `< 1` crops tighter.
 *
 * The crop keeps the **rect's** aspect, whatever the factor: the width is scaled and the height
 * derived from it. Rounding the two sides on their own drifts, and so does re-deriving the aspect
 * from the rounded crop at every step — the rect is the one reference that does not move. A crop
 * whose aspect has drifted away from its rect's makes `resizeCrop` resize the *slot* to match,
 * which is the "zoom out and the frame changes size" bug. The bound is `largestCrop`, the widest
 * crop of that aspect inside the photo, so zooming out lands exactly on the whole photo instead of
 * clamping each axis against an edge.
 *
 * A zoom always moves by at least one pixel when it can: `roundHalfEven(8 * 1.06) === 8` left a
 * crop that had been zoomed in far enough stuck at its size for ever, with no way back out.
 */
export function zoomCrop(
  state: SlotState,
  factor: number,
  source: Size,
  lock: QualityLock,
): SlotPlacement {
  const ratio = state.rect.w / state.rect.h;
  const full = largestCrop(source, ratio);
  let width = Math.max(MIN_SIZE, Math.min(full.w, roundHalfEven(state.crop.w * factor)));
  if (width === state.crop.w && factor > 1) width = Math.min(full.w, width + 1);
  else if (width === state.crop.w && factor < 1) width = Math.max(MIN_SIZE, width - 1);
  const height = Math.max(MIN_SIZE, Math.min(full.h, roundHalfEven(width / ratio)));
  const [cx, cy] = cropCenter(state.crop);
  const requested = {
    x: Math.min(Math.max(0, roundHalfEven(cx - width / 2)), source.w - width),
    y: Math.min(Math.max(0, roundHalfEven(cy - height / 2)), source.h - height),
    w: width,
    h: height,
  };
  return resizeCrop(state, requested, source, lock);
}

/** Repair a slot after the user switched its quality lock, preserving the framing. */
export function applyLock(state: SlotState, lock: QualityLock, source: Size): SlotPlacement {
  if (lock === "native") {
    const crop = cropOfSize({ w: state.rect.w, h: state.rect.h }, source, state.crop);
    return {
      rect: anchored(state.rect, { w: crop.w, h: crop.h }, CENTER),
      crop,
      quality_lock: lock,
    };
  }
  if (lock === "no_upscale" && (state.rect.w > state.crop.w || state.rect.h > state.crop.h)) {
    const size = { w: state.crop.w, h: state.crop.h };
    return { rect: anchored(state.rect, size, CENTER), crop: state.crop, quality_lock: lock };
  }
  return { rect: state.rect, crop: state.crop, quality_lock: lock };
}

/** Re-crop to a new ratio (`ratio` = w/h, `null` for `free`), centred on the current crop. */
export function applyCropRatio(
  state: SlotState,
  ratio: number | null,
  source: Size,
  lock: QualityLock,
): SlotPlacement {
  if (ratio === null) return { rect: state.rect, crop: state.crop, quality_lock: lock };
  const size = largestCrop({ w: state.crop.w, h: state.crop.h }, ratio);
  const crop = cropOfSize({ w: size.w, h: size.h }, source, state.crop);
  return resizeCrop(state, crop, source, lock);
}
