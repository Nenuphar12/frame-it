// Slider bounds for the Simple panel (docs/simple-editor.md §3.6, §6.2).
//
// CLIENT-ONLY, like `snapping.ts`: the server never needs it, because the solver is total — a
// value that leaves no room is relaxed down the ladder rather than rejected. The panel bounds each
// slider instead, so the user cannot reach a state where the numbers shown and the picture drawn
// describe different parameters.
//
// The predicate is `solveStrict`, not `solve`: the ladder would answer "roomy" for an
// over-constrained value by quietly laying the block out with *other* gutters.
import { roomy, solveStrict, type Composition, type Recipe } from "./composition.ts";
import type { Size } from "./geometry.ts";

/** Every parameter the panel can drag, with the document model's own maximum (§2). */
export const SLIDER_LIMITS: Record<SliderKey, number> = {
  "outer.x": 800,
  "outer.y": 450,
  "gutter.x": 400,
  "gutter.y": 400,
  border: 200,
};

export type SliderKey = "outer.x" | "outer.y" | "gutter.x" | "gutter.y" | "border";

/** `composition` with one slider set to `value` — the shape the bisection probes. */
export function withValue(composition: Composition, key: SliderKey, value: number): Composition {
  switch (key) {
    case "outer.x":
      return { ...composition, outer: { ...composition.outer, x: value } };
    case "outer.y":
      return { ...composition, outer: { ...composition.outer, y: value } };
    case "gutter.x":
      return { ...composition, gutter: { ...composition.gutter, x: value } };
    case "gutter.y":
      return { ...composition, gutter: { ...composition.gutter, y: value } };
    case "border":
      return {
        ...composition,
        border: value <= 0 ? null : { width: value, color: composition.border?.color ?? "#FFFFFF" },
      };
  }
}

export function valueOf(composition: Composition, key: SliderKey): number {
  switch (key) {
    case "outer.x":
      return composition.outer.x;
    case "outer.y":
      return composition.outer.y;
    case "gutter.x":
      return composition.gutter.x;
    case "gutter.y":
      return composition.gutter.y;
    case "border":
      return composition.border?.width ?? 0;
  }
}

/**
 * Largest value of `key` that still leaves every cell at least `MIN_CELL` px (§3.6).
 *
 * Growing any of these shrinks the cells monotonically, so a plain bisection is exact. The whole
 * search is ~9 solves of at most 16 cells — cheap enough to run while a slider moves.
 */
export function sliderMax(
  key: SliderKey,
  recipe: Recipe,
  composition: Composition,
  photoSizes: (Size | null)[],
  captionSize: number,
): number {
  const limit = SLIDER_LIMITS[key];
  const fits = (value: number): boolean =>
    roomy(solveStrict(recipe, withValue(composition, key, value), photoSizes, captionSize));
  if (fits(limit)) return limit;
  let low = 0;
  let high = limit;
  while (high - low > 1) {
    const mid = Math.floor((low + high) / 2);
    if (fits(mid)) low = mid;
    else high = mid;
  }
  // `low` can still be too much when even 0 leaves slivers (a huge border, say): say so, and the
  // panel disables the slider rather than pretending it has room.
  return fits(low) ? low : 0;
}
