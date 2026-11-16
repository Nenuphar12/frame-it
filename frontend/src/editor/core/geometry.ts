// Pure integer geometry — mirror of backend/src/frame_it/domain/geometry.py.
// Spec: docs/geometry-and-quality.md §7.1. Parity: conformance/geometry/*.json (`pnpm conformance`).
// Relative imports keep the `.ts` extension so Node can run this code without a bundler.

export const CANVAS_WIDTH = 3840;
export const CANVAS_HEIGHT = 2160;

export interface Size {
  w: number;
  h: number;
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Margins {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

export interface Orient {
  /** 0, 90, 180 or 270 (clockwise), applied after EXIF orientation. */
  rotate: number;
  /** Applied after `rotate`. */
  flip_h: boolean;
}

export const CANVAS: Size = { w: CANVAS_WIDTH, h: CANVAS_HEIGHT };

/** Round to the nearest integer, ties to even (same algorithm in Python). */
export function roundHalfEven(value: number): number {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (diff > 0.5) return floor + 1;
  if (diff < 0.5) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
}

export function orientedSize(source: Size, orient: Orient): Size {
  return orient.rotate === 90 || orient.rotate === 270 ? { w: source.h, h: source.w } : source;
}

function rotateCw(rect: Rect, space: Size): [Rect, Size] {
  return [
    { x: space.h - rect.y - rect.h, y: rect.x, w: rect.h, h: rect.w },
    { w: space.h, h: space.w },
  ];
}

function flipH(rect: Rect, space: Size): Rect {
  return { x: space.w - rect.x - rect.w, y: rect.y, w: rect.w, h: rect.h };
}

/** Map a rect from the (EXIF-oriented) source space into the `orient` space. */
export function rectToOriented(rect: Rect, source: Size, orient: Orient): Rect {
  let current = rect;
  let space = source;
  for (let i = 0; i < orient.rotate / 90; i++) [current, space] = rotateCw(current, space);
  return orient.flip_h ? flipH(current, space) : current;
}

export function rectFromOriented(rect: Rect, source: Size, orient: Orient): Rect {
  let space = orientedSize(source, orient);
  let current = orient.flip_h ? flipH(rect, space) : rect;
  const turns = ((360 - orient.rotate) % 360) / 90;
  for (let i = 0; i < turns; i++) [current, space] = rotateCw(current, space);
  return current;
}

/** Changing `orient` transforms the existing crop into the new space (not a reset). */
export function reorientCrop(crop: Rect, source: Size, from: Orient, to: Orient): Rect {
  return rectToOriented(rectFromOriented(crop, source, from), source, to);
}

export function cropWithin(crop: Rect, bounds: Size): boolean {
  return (
    crop.x >= 0 &&
    crop.y >= 0 &&
    crop.w >= 1 &&
    crop.h >= 1 &&
    crop.x + crop.w <= bounds.w &&
    crop.y + crop.h <= bounds.h
  );
}

/** Same aspect ratio up to integer rounding: |rw·ch − rh·cw| ≤ (rw + rh + cw + ch) / 2. */
export function aspectConsistent(rectW: number, rectH: number, cropW: number, cropH: number) {
  return 2 * Math.abs(rectW * cropH - rectH * cropW) <= rectW + rectH + cropW + cropH;
}

/** Aspect ratio (w/h) imposed by `cropRatio`; null for `free`. */
export function parseRatio(cropRatio: string, source: Size): number | null {
  if (cropRatio === "free") return null;
  if (cropRatio === "original") return source.w / source.h;
  const [w, h] = cropRatio.split(":");
  return Number(w) / Number(h);
}

/** Integer bounding box of a `w×h` box at (x, y) rotated around its centre. */
export function rotatedBounds(x: number, y: number, w: number, h: number, degrees: number): Rect {
  const cx = x + w / 2;
  const cy = y + h / 2;
  const radians = (degrees * Math.PI) / 180;
  const cos = Math.abs(Math.cos(radians));
  const sin = Math.abs(Math.sin(radians));
  const halfW = (w * cos + h * sin) / 2;
  const halfH = (w * sin + h * cos) / 2;
  const left = Math.floor(cx - halfW + 1e-9);
  const top = Math.floor(cy - halfH + 1e-9);
  const right = Math.ceil(cx + halfW - 1e-9);
  const bottom = Math.ceil(cy + halfH - 1e-9);
  return { x: left, y: top, w: right - left, h: bottom - top };
}

/** A straightening angle beyond this is a quarter turn's job (`Orient.rotate`). */
export const MAX_STRAIGHTEN = 45;

/**
 * The space a straightened photo's crop lives in (§7.1): the photo turned by `degrees`
 * (clockwise) and cut back to the largest centred rectangle with its own aspect that holds no
 * corner of the background. Every crop rule then works on it as on a plain photo. Floored; `0`
 * is the photo itself.
 */
export function straightenedSize(source: Size, degrees: number): Size {
  if (degrees === 0) return source;
  const radians = (degrees * Math.PI) / 180;
  const cos = Math.abs(Math.cos(radians));
  const sin = Math.abs(Math.sin(radians));
  const { w, h } = source;
  const k = Math.min(w / (w * cos + h * sin), h / (w * sin + h * cos));
  return {
    w: Math.max(1, Math.floor(w * k + 1e-9)),
    h: Math.max(1, Math.floor(h * k + 1e-9)),
  };
}

/** Where the straightened space starts inside the turned photo's own frame (centred). */
export function straightenOffset(source: Size, degrees: number): [number, number] {
  const inner = straightenedSize(source, degrees);
  return [(source.w - inner.w) / 2, (source.h - inner.h) / 2];
}

/**
 * A crop of the `old` straightened space, carried into the `new` one: same centre on the photo,
 * same size when it still fits, otherwise the largest of its aspect that does, kept inside.
 */
export function restraightenCrop(crop: Rect, source: Size, old: number, next: number): Rect {
  if (old === next) return crop;
  const [ox0, oy0] = straightenOffset(source, old);
  const [ox1, oy1] = straightenOffset(source, next);
  const bounds = straightenedSize(source, next);
  const cx = crop.x + crop.w / 2 + ox0 - ox1;
  const cy = crop.y + crop.h / 2 + oy0 - oy1;
  let { w, h } = crop;
  if (w > bounds.w || h > bounds.h) {
    const scale = Math.min(bounds.w / w, bounds.h / h);
    w = Math.max(1, Math.min(bounds.w, roundHalfEven(w * scale)));
    h = Math.max(1, Math.min(bounds.h, roundHalfEven(h * scale)));
  }
  const x = Math.min(Math.max(0, roundHalfEven(cx - w / 2)), bounds.w - w);
  const y = Math.min(Math.max(0, roundHalfEven(cy - h / 2)), bounds.h - h);
  return { x, y, w, h };
}

/**
 * The space a slot's crop lives in: the photo (EXIF-oriented `photo`) after the slot's quarter
 * turns and flip, then its straightening. Mirror of `SourceSpec.bounds`.
 */
export function sourceBounds(photo: Size, orient: Orient, straighten: number = 0): Size {
  return straightenedSize(orientedSize(photo, orient), straighten);
}
