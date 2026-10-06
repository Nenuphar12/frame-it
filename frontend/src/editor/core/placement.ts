// Placement modes and native linking — mirror of backend/src/frame_it/domain/placement.py.
// Spec: docs/geometry-and-quality.md §7.4.
import {
  CANVAS,
  parseRatio,
  roundHalfEven,
  type Margins,
  type Rect,
  type Size,
} from "./geometry.ts";

export type QualityLock = "native" | "no_upscale" | "free";

export interface SlotPlacement {
  rect: Rect;
  crop: Rect;
  /** May be relaxed to `free` when the requested lock cannot be honoured. */
  quality_lock: QualityLock;
}

/** Canvas minus margins (at least 1×1). */
export function availableArea(margins: Margins, canvas: Size = CANVAS): Rect {
  return {
    x: margins.left,
    y: margins.top,
    w: Math.max(1, canvas.w - margins.left - margins.right),
    h: Math.max(1, canvas.h - margins.top - margins.bottom),
  };
}

/** Largest rect with `content`'s aspect inside `area`, limited by the lock, centred in `area`. */
export function fitRect(area: Rect, content: Size, lock: QualityLock): Rect {
  let scale = Math.min(area.w / content.w, area.h / content.h);
  if (lock === "no_upscale") scale = Math.min(scale, 1);
  else if (lock === "native") scale = 1;
  const w = scale === 1 ? content.w : Math.max(1, roundHalfEven(content.w * scale));
  const h = scale === 1 ? content.h : Math.max(1, roundHalfEven(content.h * scale));
  return {
    x: area.x + roundHalfEven((area.w - w) / 2),
    y: area.y + roundHalfEven((area.h - h) / 2),
    w,
    h,
  };
}

/** Largest crop with `ratio` (w/h; null = any) inside `bounds`, centred on `center` and clamped. */
export function largestCrop(
  bounds: Size,
  ratio: number | null,
  center: [number, number] | null = null,
): Rect {
  let w: number;
  let h: number;
  if (ratio === null) {
    w = bounds.w;
    h = bounds.h;
  } else if (bounds.w / bounds.h > ratio) {
    h = bounds.h;
    w = Math.min(bounds.w, Math.max(1, roundHalfEven(h * ratio)));
  } else {
    w = bounds.w;
    h = Math.min(bounds.h, Math.max(1, roundHalfEven(w / ratio)));
  }
  const [cx, cy] = center ?? [bounds.w / 2, bounds.h / 2];
  const x = Math.min(Math.max(0, roundHalfEven(cx - w / 2)), bounds.w - w);
  const y = Math.min(Math.max(0, roundHalfEven(cy - h / 2)), bounds.h - h);
  return { x, y, w, h };
}

export function cropCenter(crop: Rect): [number, number] {
  return [crop.x + crop.w / 2, crop.y + crop.h / 2];
}

/** Native linking, margins edited: the crop takes the available area's size (see Python). */
export function nativeCropForArea(
  area: Size,
  source: Size,
  cropRatio: string,
  previous: Rect,
): Rect {
  const bounds = { w: Math.min(area.w, source.w), h: Math.min(area.h, source.h) };
  const size = largestCrop(bounds, parseRatio(cropRatio, source));
  const [cx, cy] = cropCenter(previous);
  const x = Math.min(Math.max(0, roundHalfEven(cx - size.w / 2)), source.w - size.w);
  const y = Math.min(Math.max(0, roundHalfEven(cy - size.h / 2)), source.h - size.h);
  return { x, y, w: size.w, h: size.h };
}

function share(extra: number, first: number, second: number): number {
  const total = first + second;
  return total === 0 ? roundHalfEven(extra / 2) : roundHalfEven((extra * first) / total);
}

/**
 * Native linking, crop edited: redistribute the free space around a slot (see Python).
 * `mirrorX` / `mirrorY` split their axis evenly so the two sides stay equal.
 */
export function marginsForSlot(
  slot: Size,
  previous: Margins,
  linked: boolean,
  canvas: Size = CANVAS,
  mirrorX = false,
  mirrorY = false,
): Margins {
  const extraX = Math.max(0, canvas.w - slot.w);
  const extraY = Math.max(0, canvas.h - slot.h);
  if (linked) {
    const uniform = Math.floor(Math.min(extraX, extraY) / 2);
    return { top: uniform, right: uniform, bottom: uniform, left: uniform };
  }
  const left = mirrorX ? Math.floor(extraX / 2) : share(extraX, previous.left, previous.right);
  const top = mirrorY ? Math.floor(extraY / 2) : share(extraY, previous.top, previous.bottom);
  return {
    top,
    right: mirrorX ? left : extraX - left,
    bottom: mirrorY ? top : extraY - top,
    left,
  };
}

/**
 * `fit_in_mat` placement for a single slot (margins are minimums).
 *
 * `native`: the slot is the crop size, so the crop always takes the available area's size (native
 * linking, §7.4) — it shrinks when the margins grow and grows back when they shrink.
 */
export function fitInMat(
  source: Size,
  crop: Rect,
  cropRatio: string,
  margins: Margins,
  lock: QualityLock,
): SlotPlacement {
  const area = availableArea(margins);
  if (lock === "native") {
    const current = nativeCropForArea({ w: area.w, h: area.h }, source, cropRatio, crop);
    return {
      rect: fitRect(area, { w: current.w, h: current.h }, "native"),
      crop: current,
      quality_lock: "native",
    };
  }
  return { rect: fitRect(area, { w: crop.w, h: crop.h }, lock), crop, quality_lock: lock };
}

/** Crop of exactly `size` centred in `source` (caller ensures it fits). */
export function centeredCrop(source: Size, size: Size): Rect {
  return {
    x: roundHalfEven((source.w - size.w) / 2),
    y: roundHalfEven((source.h - size.h) / 2),
    w: size.w,
    h: size.h,
  };
}

/** `fill` placement: slot = canvas, crop = largest centred crop with the canvas ratio. */
export function fill(source: Size, lock: QualityLock, canvas: Size = CANVAS): SlotPlacement {
  return fillSlot({ x: 0, y: 0, w: canvas.w, h: canvas.h }, source, lock);
}

/** Slot kept as is, photo cropped to the slot ratio (centred). Used by `fill` and layouts. */
export function fillSlot(rect: Rect, source: Size, lock: QualityLock): SlotPlacement {
  if (lock === "native" && source.w >= rect.w && source.h >= rect.h) {
    return { rect, crop: centeredCrop(source, { w: rect.w, h: rect.h }), quality_lock: "native" };
  }
  const crop = largestCrop(source, rect.w / rect.h);
  const upscaled = rect.w > crop.w || rect.h > crop.h;
  if (lock === "native" || (lock === "no_upscale" && upscaled)) {
    return { rect, crop, quality_lock: "free" };
  }
  return { rect, crop, quality_lock: lock };
}

/** Layout slot in `fit` mode: whole photo, slot shrunk to the photo ratio inside the layout rect. */
export function fitSlot(rect: Rect, source: Size, lock: QualityLock): SlotPlacement {
  const crop = { x: 0, y: 0, w: source.w, h: source.h };
  const effective: QualityLock =
    lock === "native" && (source.w > rect.w || source.h > rect.h) ? "no_upscale" : lock;
  return { rect: fitRect(rect, source, effective), crop, quality_lock: effective };
}

/** `w:h` reduced by their greatest common divisor (crop ratio of a slot with a fixed shape). */
export function ratioLabel(w: number, h: number): string {
  const gcd = (a: number, b: number): number => (b === 0 ? a : gcd(b, a % b));
  const divisor = gcd(Math.abs(w), Math.abs(h)) || 1;
  return `${Math.round(w / divisor)}:${Math.round(h / divisor)}`;
}
