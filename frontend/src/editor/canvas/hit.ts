// Pointer maths for the composition gestures: hit-testing, transform handles, rotation.
//
// Client-only (it works in screen/document coordinates and has no server counterpart), but pure:
// the document mutations themselves live in `editor/operations.ts`. Slots are rotated around the
// centre of their rect (§7.1), so every test and every drag converts the pointer into the slot's
// own frame first.
import type { Anchor } from "@/editor/core/constraints.ts";
import type { Rect, Size } from "@/editor/core/geometry.ts";

export interface Point {
  x: number;
  y: number;
}

/** The eight resize handles plus the rotation knob, named after the edge they sit on. */
export const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"] as const;
export type Handle = (typeof HANDLES)[number];

export const rectCenter = (rect: Rect): Point => ({ x: rect.x + rect.w / 2, y: rect.y + rect.h / 2 });

/** Rotate `point` by `degrees` around `origin` (clockwise, canvas axes). */
export function rotatePoint(point: Point, origin: Point, degrees: number): Point {
  const radians = (degrees * Math.PI) / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  const dx = point.x - origin.x;
  const dy = point.y - origin.y;
  return { x: origin.x + dx * cos - dy * sin, y: origin.y + dx * sin + dy * cos };
}

/**
 * Document point expressed in the box's own (unrotated) frame. `pivot` is what the rotation
 * turns around: the centre for a slot, the anchor point for a caption (§8.1 step 4).
 */
export function toLocal(point: Point, rect: Rect, rotation: number, pivot?: Point): Point {
  return rotatePoint(point, pivot ?? rectCenter(rect), -rotation);
}

/** Is the point inside the box, rotation included? */
export function hitsRect(
  point: Point,
  rect: Rect,
  rotation: number,
  pad = 0,
  pivot?: Point,
): boolean {
  const local = toLocal(point, rect, rotation, pivot);
  return (
    local.x >= rect.x - pad &&
    local.x <= rect.x + rect.w + pad &&
    local.y >= rect.y - pad &&
    local.y <= rect.y + rect.h + pad
  );
}

/** Front-most slot under the point (the array order is the z-order, last is on top). */
export function slotAt<T extends { rect: Rect; rotation: number }>(
  slots: readonly T[],
  point: Point,
): T | null {
  for (let index = slots.length - 1; index >= 0; index--) {
    const slot = slots[index]!;
    if (hitsRect(point, slot.rect, slot.rotation)) return slot;
  }
  return null;
}

/** Where a handle sits on the rect, as a fraction of its size (0 = left/top, 1 = right/bottom). */
export function handleFraction(handle: Handle): [number, number] {
  const x = handle.includes("w") ? 0 : handle.includes("e") ? 1 : 0.5;
  const y = handle.includes("n") ? 0 : handle.includes("s") ? 1 : 0.5;
  return [x, y];
}

/** The point that must stay fixed while `handle` is dragged: the opposite one. */
export function handleAnchor(handle: Handle): Anchor {
  const [x, y] = handleFraction(handle);
  return [1 - x, 1 - y];
}

/** Position of a handle in document coordinates (rotation included). */
export function handlePoint(rect: Rect, rotation: number, handle: Handle): Point {
  const [fx, fy] = handleFraction(handle);
  return rotatePoint(
    { x: rect.x + fx * rect.w, y: rect.y + fy * rect.h },
    rectCenter(rect),
    rotation,
  );
}

/**
 * Size requested by dragging `handle` by (dx, dy) *document* pixels: the drag is converted into
 * the slot's frame, and a handle that only owns one axis leaves the other one alone. The lock
 * and the aspect ratio are then resolved by the constraint solver (§7.3).
 */
export function resizedSize(rect: Rect, rotation: number, handle: Handle, delta: Point): Size {
  const local = rotatePoint(delta, { x: 0, y: 0 }, -rotation);
  const [fx, fy] = handleFraction(handle);
  const signX = fx === 0.5 ? 0 : fx === 0 ? -1 : 1;
  const signY = fy === 0.5 ? 0 : fy === 0 ? -1 : 1;
  return {
    w: Math.max(1, rect.w + signX * local.x),
    h: Math.max(1, rect.h + signY * local.y),
  };
}

/** Angle (degrees, clockwise, −180…180) of `point` seen from the centre of `rect`. */
export function angleTo(rect: Rect, point: Point): number {
  const center = rectCenter(rect);
  const degrees = (Math.atan2(point.y - center.y, point.x - center.x) * 180) / Math.PI;
  return degrees;
}

/** Rotation snapped to 15° steps (holding Shift), rounded to the document's 0.1°. */
export function snapAngle(degrees: number, step: number | null): number {
  const value = step ? Math.round(degrees / step) * step : degrees;
  const wrapped = ((((value + 180) % 360) + 360) % 360) - 180;
  return Math.round(wrapped * 10) / 10;
}
