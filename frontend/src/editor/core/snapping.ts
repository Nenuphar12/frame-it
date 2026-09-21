// Snapping candidates for the editor. Spec: docs/geometry-and-quality.md §7.5.
//
// Client-only (the tolerance is in screen pixels, so it depends on the stage scale) but pure:
// candidates are computed from the document, `snap` picks the best one by priority then distance.
import { CANVAS, type Margins, type Rect, type Size } from "./geometry.ts";

export const TOLERANCE_PX = 8;
/** Priority order of §7.5 — a closer candidate of a lower priority never wins. */
export const PRIORITY = ["quality", "canvas", "slot", "gap", "margin"] as const;
export type SnapKind = (typeof PRIORITY)[number];

export interface SnapCandidate {
  value: number;
  kind: SnapKind;
  /** i18n key explaining the guide, e.g. `editor.snap.native`. */
  label: string;
}

export interface SnapResult {
  value: number;
  hit: SnapCandidate | null;
}

/**
 * Snap `value` to the best candidate within `tolerance` (document px: pass
 * `TOLERANCE_PX / stageScale`). Holding Alt should skip the call entirely.
 */
export function snap(value: number, candidates: SnapCandidate[], tolerance: number): SnapResult {
  let best: SnapCandidate | null = null;
  let bestRank: number = PRIORITY.length;
  let bestDistance = Infinity;
  for (const candidate of candidates) {
    const distance = Math.abs(candidate.value - value);
    if (distance > tolerance) continue;
    const rank = PRIORITY.indexOf(candidate.kind);
    if (rank < bestRank || (rank === bestRank && distance < bestDistance)) {
      best = candidate;
      bestRank = rank;
      bestDistance = distance;
    }
  }
  return { value: best ? best.value : value, hit: best };
}

export type Side = "top" | "right" | "bottom" | "left";

const HORIZONTAL: Side[] = ["left", "right"];

/**
 * Candidates for one margin of a `fit_in_mat` artwork, the three other sides being fixed.
 *
 * * `quality` — the value that makes the available area exactly as wide (or tall) as the crop, so
 *   the photo is shown at scale 1: the "quality point" of §7.5, the most useful stop of all.
 * * `canvas` — the value that centres the photo (same margin as the opposite side).
 * * `margin` — the other three margins, so sides can be aligned by eye.
 */
export function marginCandidates(
  side: Side,
  margins: Margins,
  crop: Size,
  canvas: Size = CANVAS,
): SnapCandidate[] {
  const horizontal = HORIZONTAL.includes(side);
  const opposite = horizontal
    ? side === "left"
      ? margins.right
      : margins.left
    : side === "top"
      ? margins.bottom
      : margins.top;
  const span = horizontal ? canvas.w : canvas.h;
  const cropSpan = horizontal ? crop.w : crop.h;
  const candidates: SnapCandidate[] = [
    { value: opposite, kind: "canvas", label: "editor.snap.centered" },
  ];
  const nativePoint = span - opposite - cropSpan;
  if (nativePoint >= 0) {
    candidates.push({ value: nativePoint, kind: "quality", label: "editor.snap.native" });
  }
  for (const other of ["top", "right", "bottom", "left"] as Side[]) {
    if (other !== side) {
      candidates.push({ value: margins[other], kind: "margin", label: `editor.sides.${other}` });
    }
  }
  return candidates.filter((c) => c.value >= 0 && c.value < span);
}

/** Edges and centres of the canvas and of the other slots (§7.5), for a dragged slot edge. */
export function slotCandidates(
  others: Rect[],
  axis: "x" | "y",
  canvas: Size = CANVAS,
): SnapCandidate[] {
  const span = axis === "x" ? canvas.w : canvas.h;
  const candidates: SnapCandidate[] = [
    { value: 0, kind: "canvas", label: "editor.snap.canvasEdge" },
    { value: span, kind: "canvas", label: "editor.snap.canvasEdge" },
    { value: span / 2, kind: "canvas", label: "editor.snap.canvasCenter" },
  ];
  for (const rect of others) {
    const start = axis === "x" ? rect.x : rect.y;
    const size = axis === "x" ? rect.w : rect.h;
    candidates.push(
      { value: start, kind: "slot", label: "editor.snap.slotEdge" },
      { value: start + size, kind: "slot", label: "editor.snap.slotEdge" },
      { value: start + size / 2, kind: "slot", label: "editor.snap.slotCenter" },
    );
  }
  return candidates;
}

/**
 * Positions where the dragged rect would repeat a gap that already exists between two other
 * slots — the "equal gaps" stop of §7.5. Candidates are *start* coordinates of the moving rect
 * (its left or top edge); the caller adds them to `slotCandidates` for the same axis.
 *
 * Only the gaps between consecutive slots along the axis are considered: those are the ones the
 * eye compares. A gap of 0 (two slots touching) makes the dragged slot touch its neighbour too.
 */
export function gapCandidates(others: Rect[], axis: "x" | "y", moving: Size): SnapCandidate[] {
  const start = (rect: Rect) => (axis === "x" ? rect.x : rect.y);
  const size = (rect: Rect) => (axis === "x" ? rect.w : rect.h);
  const span = axis === "x" ? moving.w : moving.h;
  const sorted = [...others].sort((a, b) => start(a) - start(b));
  const gaps = new Set<number>();
  for (let index = 1; index < sorted.length; index++) {
    const previous = sorted[index - 1]!;
    const current = sorted[index]!;
    gaps.add(Math.round(start(current) - (start(previous) + size(previous))));
  }
  const candidates: SnapCandidate[] = [];
  for (const gap of gaps) {
    for (const rect of others) {
      candidates.push(
        { value: start(rect) + size(rect) + gap, kind: "gap", label: "editor.snap.equalGap" },
        { value: start(rect) - gap - span, kind: "gap", label: "editor.snap.equalGap" },
      );
    }
  }
  return candidates;
}

/** Candidates for one edge of a dragged or resized slot: canvas, other slots and equal gaps. */
export function compositionCandidates(
  others: Rect[],
  axis: "x" | "y",
  moving: Size | null,
  canvas: Size = CANVAS,
): SnapCandidate[] {
  const candidates = slotCandidates(others, axis, canvas);
  return moving ? [...candidates, ...gapCandidates(others, axis, moving)] : candidates;
}

export interface RectSnap {
  /** The rect after snapping (same size, moved by at most `tolerance` on each axis). */
  rect: Rect;
  /** Document coordinates of the guides to draw, `null` when that axis did not snap. */
  guides: { x: number | null; y: number | null };
}

/**
 * Snap a dragged slot: its left edge, centre and right edge are all candidates for a stop, and
 * the closest hit wins (same for the vertical axis). Returns the corrected rect and where to
 * draw the magenta guides (§7.5).
 */
export function snapRect(
  rect: Rect,
  others: Rect[],
  tolerance: number,
  canvas: Size = CANVAS,
): RectSnap {
  const size = { w: rect.w, h: rect.h };
  const axis = (value: number, span: number, which: "x" | "y") => {
    const candidates = compositionCandidates(others, which, size, canvas);
    // The three probes are expressed as the rect's start, so their offsets cancel out.
    const probes: [number, number][] = [
      [value, 0],
      [value + span / 2, span / 2],
      [value + span, span],
    ];
    let best: { value: number; guide: number; distance: number } | null = null;
    for (const [probe, offset] of probes) {
      const shifted = candidates.map((candidate) => ({
        ...candidate,
        value: candidate.value - offset,
      }));
      const result = snap(probe - offset, shifted, tolerance);
      if (!result.hit) continue;
      const distance = Math.abs(result.value - (probe - offset));
      if (!best || distance < best.distance) {
        best = { value: result.value, guide: result.value + offset, distance };
      }
    }
    return best;
  };
  const horizontal = axis(rect.x, rect.w, "x");
  const vertical = axis(rect.y, rect.h, "y");
  return {
    rect: {
      x: horizontal ? Math.round(horizontal.value) : rect.x,
      y: vertical ? Math.round(vertical.value) : rect.y,
      w: rect.w,
      h: rect.h,
    },
    guides: { x: horizontal?.guide ?? null, y: vertical?.guide ?? null },
  };
}
