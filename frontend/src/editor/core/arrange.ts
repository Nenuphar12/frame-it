// Arranging several slots — mirror of backend/src/frame_it/domain/arrange.py.
// Spec: docs/geometry-and-quality.md §7.7. Parity: conformance/geometry/arrange.json.
//
// These functions only move and resize rects: they never touch a crop, so the caller runs the
// result through the constraint solver (§7.3) when a size changes. The input order is preserved.
import { roundHalfEven, type Rect, type Size } from "./geometry.ts";

export type Edge = "left" | "h_center" | "right" | "top" | "v_center" | "bottom";
export type Axis = "x" | "y";

export const EDGES: Edge[] = ["left", "h_center", "right", "top", "v_center", "bottom"];
export const HORIZONTAL_EDGES: Edge[] = ["left", "h_center", "right"];

export const NEW_SLOT_FRACTION = 0.45;
export const NEW_SLOT_STEP = 96;

/** Smallest rect containing them all (1×1 at the origin for an empty list). */
export function boundingBox(rects: Rect[]): Rect {
  if (rects.length === 0) return { x: 0, y: 0, w: 1, h: 1 };
  const left = Math.min(...rects.map((r) => r.x));
  const top = Math.min(...rects.map((r) => r.y));
  const right = Math.max(...rects.map((r) => r.x + r.w));
  const bottom = Math.max(...rects.map((r) => r.y + r.h));
  return { x: left, y: top, w: Math.max(1, right - left), h: Math.max(1, bottom - top) };
}

/** Move every rect onto one edge (or centre line) of the group's bounding box. */
export function align(rects: Rect[], edge: Edge): Rect[] {
  const box = boundingBox(rects);
  return rects.map((rect) => {
    let { x, y } = rect;
    if (edge === "left") x = box.x;
    else if (edge === "right") x = box.x + box.w - rect.w;
    else if (edge === "h_center") x = box.x + roundHalfEven((box.w - rect.w) / 2);
    else if (edge === "top") y = box.y;
    else if (edge === "bottom") y = box.y + box.h - rect.h;
    else y = box.y + roundHalfEven((box.h - rect.h) / 2);
    return { x, y, w: rect.w, h: rect.h };
  });
}

/**
 * Equal gaps along `axis`, the two extreme rects staying where they are. Fewer than three rects
 * have no gap to equalise. Rects are ordered by position, the result keeps the input order.
 */
export function distribute(rects: Rect[], axis: Axis): Rect[] {
  if (rects.length < 3) return [...rects];
  const start = (r: Rect) => (axis === "x" ? r.x : r.y);
  const size = (r: Rect) => (axis === "x" ? r.w : r.h);
  const order = rects
    .map((_, index) => index)
    .sort((a, b) => start(rects[a]!) - start(rects[b]!) || a - b);
  const first = rects[order[0]!]!;
  const last = rects[order[order.length - 1]!]!;
  const span = start(last) + size(last) - start(first);
  const total = order.reduce((sum, index) => sum + size(rects[index]!), 0);
  const gap = (span - total) / (rects.length - 1);
  const result = [...rects];
  let cursor = start(first);
  order.forEach((index, position) => {
    const rect = rects[index]!;
    if (position === 0 || position === order.length - 1) {
      cursor = start(rect) + size(rect) + gap;
      return;
    }
    const value = roundHalfEven(cursor);
    result[index] =
      axis === "x"
        ? { x: value, y: rect.y, w: rect.w, h: rect.h }
        : { x: rect.x, y: value, w: rect.w, h: rect.h };
    cursor += size(rect) + gap;
  });
  return result;
}

/** Give every rect the size of `rects[reference]`, keeping each one centred where it is. */
export function sameSize(rects: Rect[], reference: number): Rect[] {
  if (rects.length === 0) return [];
  const model = rects[Math.max(0, Math.min(reference, rects.length - 1))]!;
  return rects.map((rect) => ({
    x: roundHalfEven(rect.x + rect.w / 2 - model.w / 2),
    y: roundHalfEven(rect.y + rect.h / 2 - model.h / 2),
    w: model.w,
    h: model.h,
  }));
}

/** Size of a slot the user adds: a fraction of `area`, at the photo's aspect when known. */
export function newSlotSize(area: Rect, source: Size | null = null): Size {
  const w = Math.max(1, Math.min(area.w, roundHalfEven(area.w * NEW_SLOT_FRACTION)));
  const h = Math.max(1, Math.min(area.h, roundHalfEven(area.h * NEW_SLOT_FRACTION)));
  if (source === null) return { w, h };
  const scale = Math.min(w / source.w, h / source.h);
  return {
    w: Math.max(1, roundHalfEven(source.w * scale)),
    h: Math.max(1, roundHalfEven(source.h * scale)),
  };
}

/** Where a slot of `size` lands: centred in `area`, cascaded off the slots already there. */
export function newSlotRect(existing: Rect[], area: Rect, size: Size): Rect {
  const w = Math.max(1, size.w);
  const h = Math.max(1, size.h);
  let x = area.x + roundHalfEven((area.w - w) / 2);
  let y = area.y + roundHalfEven((area.h - h) / 2);
  const taken = new Set(existing.map((rect) => `${rect.x},${rect.y}`));
  for (let i = 0; i < existing.length; i++) {
    if (!taken.has(`${x},${y}`)) break;
    x += NEW_SLOT_STEP;
    y += NEW_SLOT_STEP;
  }
  if (w <= area.w) x = Math.min(Math.max(area.x, x), area.x + area.w - w);
  if (h <= area.h) y = Math.min(Math.max(area.y, y), area.y + area.h - h);
  return { x, y, w, h };
}
