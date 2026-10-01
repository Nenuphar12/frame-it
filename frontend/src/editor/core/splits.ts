// The divisions of a Fill layout, as the editor lets you move them (docs/simple-editor.md §6.5).
//
// CLIENT-ONLY, like `snapping.ts` and `bounds.ts`: the server only ever sees the result, a
// `composition.weights` entry (or `balance`) that the mirrored solver lays out. What lives here is
// the gesture's arithmetic — where the gaps are, what a drag of one means in shares, which shares a
// slider may reach — so the canvas and the panel agree on it and neither re-implements the solver.
//
// A layout is nested rows and columns, so "this photo's width" is really "this division": the
// photos sharing the column move with it. Everything below is therefore keyed by a split (its
// depth-first index, the one `composition.weights` uses) and never by a photo alone.
import type { Recipe, RecipeCell, RecipeNode } from "./composition.ts";
import type { Rect } from "./geometry.ts";

/** Smallest share a drag or a slider leaves one side of a division. */
export const MIN_SHARE = 0.1;
/** Shares a dragged division snaps to, as a fraction of the two parts it separates. */
export const SNAP_FRACTIONS = [1 / 3, 0.381966, 0.5, 0.618034, 2 / 3] as const;

export type SplitAxis = "x" | "y";

/** The gap between two neighbouring parts of a split. */
export interface Divider {
  /** Depth-first index of the split — the index of its `composition.weights` entry. */
  split: number;
  /** The gap sits between child `gap` and child `gap + 1`. */
  gap: number;
  /** `x`: a row's vertical gap, dragged left/right. `y`: a column's, dragged up/down. */
  axis: SplitAxis;
  /** The gutter band itself, in document px (zero thick when the gutter is 0). */
  rect: Rect;
  /** Extent of every child of the split along the axis, printed edge to printed edge. */
  sizes: number[];
}

const isCell = (node: RecipeNode): node is RecipeCell => "cell" in node;

function union(boxes: Rect[]): Rect {
  const x = Math.min(...boxes.map((box) => box.x));
  const y = Math.min(...boxes.map((box) => box.y));
  const right = Math.max(...boxes.map((box) => box.x + box.w));
  const bottom = Math.max(...boxes.map((box) => box.y + box.h));
  return { x, y, w: right - x, h: bottom - y };
}

/**
 * Every gap of the layout, read off the solved geometry.
 *
 * `footprints` are the cells as printed (photo rect grown by its border), in slot order. Reading
 * the gaps off them rather than re-walking the solver means a divider is exactly where the eye
 * sees it, whatever the solver had to relax (§3.6).
 */
export function dividers(recipe: Recipe, footprints: Rect[]): Divider[] {
  const out: Divider[] = [];
  const cursor = { leaf: 0, split: 0 };
  const walk = (node: RecipeNode): Rect | null => {
    if (isCell(node)) return footprints[cursor.leaf++] ?? null;
    const split = cursor.split++;
    const boxes: Rect[] = [];
    for (const child of node.children) {
      const box = walk(child);
      if (box) boxes.push(box);
    }
    if (boxes.length !== node.children.length) return boxes.length > 0 ? union(boxes) : null;
    const whole = union(boxes);
    const row = node.split === "row";
    const sizes = boxes.map((box) => (row ? box.w : box.h));
    for (let gap = 0; gap < boxes.length - 1; gap++) {
      const before = boxes[gap]!;
      const after = boxes[gap + 1]!;
      const rect = row
        ? { x: before.x + before.w, y: whole.y, w: after.x - before.x - before.w, h: whole.h }
        : { x: whole.x, y: before.y + before.h, w: whole.w, h: after.y - before.y - before.h };
      out.push({ split, gap, axis: row ? "x" : "y", rect, sizes });
    }
    return whole;
  };
  walk(recipe.tree);
  return out;
}

/** Shares of a split's children, summing to 1 (the solver only reads proportions). */
export function normalized(weights: readonly number[]): number[] {
  const total = weights.reduce((sum, weight) => sum + weight, 0);
  return total > 0 ? weights.map((weight) => weight / total) : weights.map(() => 0);
}

const tidy = (share: number) => Math.round(share * 10000) / 10000;

/**
 * The shares a split has once `divider` has been dragged by `delta` document px.
 *
 * Only the two parts on either side of the gap change — the other children of a 3- or 4-part split
 * stay as they are, which is what dragging one line between two photos looks like. `tolerance`
 * (document px, `null` = no snapping) pulls the line onto equal parts, thirds and the golden
 * section of those two parts; `guide` is then where the line ended up, for the magenta guide.
 */
export function dragShares(
  divider: Divider,
  delta: number,
  tolerance: number | null,
): { shares: number[]; guide: number | null } {
  const { sizes, gap, rect, axis } = divider;
  const total = sizes.reduce((sum, size) => sum + size, 0);
  const before = sizes[gap] ?? 0;
  const pair = before + (sizes[gap + 1] ?? 0);
  const floor = Math.min(MIN_SHARE * total, pair / 2);
  let moved = Math.max(floor, Math.min(pair - floor, before + delta));
  let snapped = false;
  if (tolerance !== null) {
    for (const fraction of SNAP_FRACTIONS) {
      const target = fraction * pair;
      if (target >= floor && target <= pair - floor && Math.abs(moved - target) <= tolerance) {
        moved = target;
        snapped = true;
        break;
      }
    }
  }
  const next = sizes.map((size, index) =>
    index === gap ? moved : index === gap + 1 ? pair - moved : size,
  );
  const origin = axis === "x" ? rect.x : rect.y;
  const thickness = axis === "x" ? rect.w : rect.h;
  return {
    shares: next.map((size) => tidy(size / total)),
    guide: snapped ? origin - before + moved + thickness / 2 : null,
  };
}

/** `shares` with child `child` set to `value`, the others keeping their own proportions. */
export function withShare(shares: readonly number[], child: number, value: number): number[] {
  const current = normalized(shares);
  const rest = 1 - (current[child] ?? 0);
  return current.map((share, index) =>
    tidy(index === child ? value : rest > 0 ? (share * (1 - value)) / rest : 0),
  );
}

/**
 * The shares `child` may take: every part of the split keeps at least `MIN_SHARE`.
 *
 * The others shrink in proportion, so the limit is set by the smallest of them. Where the recipe
 * declares a balance the root follows *its* range instead — that is what the server accepts.
 */
export function shareRange(
  recipe: Recipe,
  split: number,
  child: number,
  shares: readonly number[],
): [number, number] {
  if (split === 0 && recipe.balance) {
    const { min, max } = recipe.balance;
    return child === 0 ? [min, max] : [tidy(1 - max), tidy(1 - min)];
  }
  const current = normalized(shares);
  const mine = current[child] ?? 0;
  const others = current.filter((_, index) => index !== child);
  const smallest = Math.min(...others);
  const rest = 1 - mine;
  // Scaling the others by (1 − v) / rest keeps the smallest at MIN_SHARE when v is this:
  const max = smallest > 0 ? 1 - (MIN_SHARE * rest) / smallest : mine;
  return [Math.min(MIN_SHARE, mine), Math.max(mine, Math.min(1 - MIN_SHARE, max))];
}

/** Where one cell's size is decided: the split and the child it descends through. */
export interface CellSplit {
  split: number;
  child: number;
}

/**
 * The divisions that set the width (`x`) and the height (`y`) of cell `index`.
 *
 * The nearest row above a cell shares the width out, the nearest column the height; a cell with no
 * row above it spans the whole block and has no width to give (`null`).
 */
export function cellSplits(
  recipe: Recipe,
  index: number,
): { x: CellSplit | null; y: CellSplit | null } {
  const cursor = { leaf: 0, split: 0 };
  let found: { x: CellSplit | null; y: CellSplit | null } = { x: null, y: null };
  const walk = (node: RecipeNode, x: CellSplit | null, y: CellSplit | null): void => {
    if (isCell(node)) {
      if (cursor.leaf++ === index) found = { x, y };
      return;
    }
    const split = cursor.split++;
    node.children.forEach((child, position) => {
      const here = { split, child: position };
      if (node.split === "row") walk(child, here, y);
      else walk(child, x, here);
    });
  };
  walk(recipe.tree, null, null);
  return found;
}
