// Parametric compositions — mirror of backend/src/frame_it/domain/composition.py.
// Spec: docs/simple-editor.md §3–§4. Parity: conformance/geometry/composition.json.
// Relative imports keep the `.ts` extension so Node can run this code without a bundler.
import type { Band, CaptionAnchor, DocCaption, DocSlot, EditorDocument } from "./document.ts";
import {
  CANVAS,
  type Margins,
  type Rect,
  type Size,
  orientedSize,
  roundHalfEven,
} from "./geometry.ts";
import { cropCenter, largestCrop, type QualityLock, ratioLabel } from "./placement.ts";

/** Smallest acceptable photo rect on either axis; below it the solver relaxes (§3.6). */
export const MIN_CELL = 40;
/** Height reserved for a caption, in multiples of its font size (docs/simple-editor.md §10). */
export const CAPTION_BAND_FACTOR = 1.5;
/** Matches `templates.CaptionDefaults.size`; the caller passes the style's own value. */
export const DEFAULT_CAPTION_SIZE = 48;
/** Ladder used to recover from an over-constrained document (§3.6): fixed, hence mirrorable. */
export const RELAXATION_STEPS = 10;
/**
 * Baseline of the derived caption inside its line, in multiples of the font size (§3.7).
 * `CAPTION_BAND_FACTOR − 1` of leading shared above and below, plus a ~0.8 em ascent: a pure
 * number, like the band itself, so both solvers place the caption identically without metrics.
 */
export const CAPTION_BASELINE_FACTOR = 1.05;
/** Id of the caption a composition derives; an existing caption keeps its own id. */
export const DERIVED_CAPTION_ID = "caption";

export type CellKind = "landscape" | "portrait" | "square" | "auto";
export type CaptionPlace = "none" | "above" | "below";
export type CaptionAlign = "left" | "center" | "right";

/** A leaf: one cell. `auto` takes the photo's own orientation (1-cell recipes). */
export interface RecipeCell {
  cell: CellKind;
}

/** `row`: children left→right, separated by `gutter.x`. `col`: top→bottom, `gutter.y`. */
export interface RecipeSplit {
  split: "row" | "col";
  weights: number[];
  children: RecipeNode[];
}

export type RecipeNode = RecipeCell | RecipeSplit;

export interface BalanceRange {
  min: number;
  max: number;
  default: number;
}

export interface Recipe {
  id: string;
  count: number;
  name_key: string;
  /** Replaces the root split's weights by `[b, 1−b]`; only a 2-child root may declare it. */
  balance?: BalanceRange | null;
  tree: RecipeNode;
}

export interface CompositionBorder {
  width: number;
  color: string;
  /** The border is a mat bevel rather than a flat band (`Band.bevel`). */
  bevel: boolean;
}

export interface CompositionCaption {
  text: string;
  place: CaptionPlace;
  /** Centred on the canvas, or flush with the block's left / right printed edge (§3.7). */
  align: CaptionAlign;
}

/** The document's `composition` block (docs/simple-editor.md §2). */
export interface Composition {
  recipe: string;
  /** Share of the root split's first child; `null` = the recipe's default. Fill format only. */
  balance: number | null;
  /**
   * Per-split override of the recipe's `weights`, splits in depth-first order; `null` inherits.
   * Fill format only, and `balance` stays the root's share wherever the recipe declares one (§3.4).
   */
  weights: (number[] | null)[];
  /** Minimum margin around the block, per axis. */
  outer: { x: number; y: number };
  /** Exact gap between two printed edges, per axis. */
  gutter: { x: number; y: number };
  format: string;
  /** Per-cell override of `format`, in slot order; `null` inherits. Ignored under `fill` (§3.5). */
  cell_formats: (string | null)[];
  border: CompositionBorder | null;
  caption: CompositionCaption;
  /** The slots have been hand-edited: they are the truth and this block is memory only (§5). */
  detached: boolean;
}

export interface Cell {
  id: string;
  /** The photo rect: the cell's footprint deflated by the border width. */
  rect: Rect;
  /** `w:h` of `rect`, reduced — the slot's `crop_ratio`. */
  ratio_label: string;
}

/** A float rect during the walk; only the final edges become integers. */
interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** `w = α·h + β` between a node's footprint dimensions under a ratio format (§3.5). */
interface Affine {
  alpha: number;
  beta: number;
}

/** The affine relations of a whole subtree, shaped like it (walked in lockstep with the tree). */
interface Relation {
  affine: Affine;
  children: Relation[];
}

const isCell = (node: RecipeNode): node is RecipeCell => "cell" in node;

/** Cells in depth-first order — the reading order, and the slot order (§3.1). */
export function leaves(node: RecipeNode): RecipeCell[] {
  if (isCell(node)) return [node];
  return node.children.flatMap(leaves);
}

/** Split nodes in depth-first order, the root first — how `composition.weights` is indexed. */
export function splits(node: RecipeNode): RecipeSplit[] {
  if (isCell(node)) return [];
  return [node, ...node.children.flatMap(splits)];
}

export const cellId = (index: number): string => `c${index + 1}`;

/**
 * Aspect a ratio format asks for, **as written**; `null` for `fill` and `original`.
 *
 * `4:3` and `3:4` are different formats: the one the user picked is the one the cells take (§3.5).
 * Only an `auto` leaf still turns the ratio the photo's way, through `landscapeRatio`.
 */
export function formatRatio(compositionFormat: string): number | null {
  if (!compositionFormat.includes(":")) return null;
  const [width, height] = compositionFormat.split(":");
  return Number(width) / Number(height);
}

/** `r ≥ 1` form of an aspect — what an `auto` leaf turns the photo's way. */
export const landscapeRatio = (ratio: number): number => (ratio >= 1 ? ratio : 1 / ratio);

/** Height reserved on the caption's side, before solving (§3.3) — no font metrics involved. */
export function captionBand(captionSize: number, gutterY: number): number {
  return roundHalfEven(captionSize * CAPTION_BAND_FACTOR) + gutterY;
}

/** `A`: the canvas minus `outer` on each side, minus the caption band (§3.3). */
export function blockArea(
  composition: Composition,
  captionSize: number = DEFAULT_CAPTION_SIZE,
  canvas: Size = CANVAS,
): Rect {
  return areaFor(composition, composition.outer.x, composition.outer.y, captionSize, canvas);
}

function areaFor(
  composition: Composition,
  outerX: number,
  outerY: number,
  captionSize: number,
  canvas: Size,
): Rect {
  const area = {
    x: outerX,
    y: outerY,
    w: Math.max(1, canvas.w - 2 * outerX),
    h: Math.max(1, canvas.h - 2 * outerY),
  };
  const place = composition.caption.place;
  if (place === "none") return area;
  const band = Math.min(area.h - 1, captionBand(captionSize, composition.gutter.y));
  return {
    x: area.x,
    y: place === "above" ? area.y + band : area.y,
    w: area.w,
    h: Math.max(1, area.h - band),
  };
}

/**
 * Cells of `recipe` laid out for `composition`, in reading order (= slot order).
 *
 * Total: an over-constrained document (import, hand-edited JSON) is retried with the gutters
 * scaled down, then `outer`, and finally clamped — it never throws (§3.6).
 */
export function solve(
  recipe: Recipe,
  composition: Composition,
  photoSizes: (Size | null)[] = [],
  captionSize: number = DEFAULT_CAPTION_SIZE,
  canvas: Size = CANVAS,
): Cell[] {
  let attempt = solveOnce(recipe, composition, photoSizes, captionSize, canvas, 1, 1);
  if (roomy(attempt)) return attempt;
  for (let step = 1; step <= RELAXATION_STEPS; step++) {
    const scale = (RELAXATION_STEPS - step) / RELAXATION_STEPS;
    attempt = solveOnce(recipe, composition, photoSizes, captionSize, canvas, scale, 1);
    if (roomy(attempt)) return attempt;
  }
  for (let step = 1; step <= RELAXATION_STEPS; step++) {
    const scale = (RELAXATION_STEPS - step) / RELAXATION_STEPS;
    attempt = solveOnce(recipe, composition, photoSizes, captionSize, canvas, 0, scale);
    if (roomy(attempt)) return attempt;
  }
  return attempt;
}

/**
 * One attempt at the parameters as given — no relaxation ladder (§3.6).
 *
 * What the panel bisects on to bound its sliders: `solve` would hide an over-constrained value
 * behind the ladder and report cells that honour *other* parameters.
 */
export function solveStrict(
  recipe: Recipe,
  composition: Composition,
  photoSizes: (Size | null)[] = [],
  captionSize: number = DEFAULT_CAPTION_SIZE,
  canvas: Size = CANVAS,
): Cell[] {
  return solveOnce(recipe, composition, photoSizes, captionSize, canvas, 1, 1);
}

/** Every cell clears `MIN_CELL` on both axes — the ladder's stopping rule (§3.6). */
export const roomy = (cells: Cell[]): boolean =>
  cells.every((cell) => cell.rect.w >= MIN_CELL && cell.rect.h >= MIN_CELL);

function solveOnce(
  recipe: Recipe,
  composition: Composition,
  photoSizes: (Size | null)[],
  captionSize: number,
  canvas: Size,
  gutterScale: number,
  outerScale: number,
): Cell[] {
  const gutterX = roundHalfEven(composition.gutter.x * gutterScale);
  const gutterY = roundHalfEven(composition.gutter.y * gutterScale);
  const outerX = roundHalfEven(composition.outer.x * outerScale);
  const outerY = roundHalfEven(composition.outer.y * outerScale);
  const area = areaFor(composition, outerX, outerY, captionSize, canvas);
  const border = composition.border ? composition.border.width : 0;

  const box: Box = { x: area.x, y: area.y, w: area.w, h: area.h };
  const boxes: Box[] = [];
  if (composition.format === "fill") {
    walkFill(recipe.tree, box, splitWeights(recipe, composition), 0, gutterX, gutterY, boxes);
  } else {
    const aspects = leaves(recipe.tree).map((cell, index) =>
      leafAspect(cell, cellFormat(composition, index), photoSizes[index] ?? null, area),
    );
    const [relation] = relate(recipe.tree, aspects, 0, border, gutterX, gutterY);
    walkRatio(recipe.tree, relation, fitBlock(relation.affine, box), gutterX, gutterY, boxes);
  }
  return boxes.map((footprint, index) => toCell(index, footprint, border));
}

/**
 * Target aspect (w/h) of a leaf's **photo** under a ratio format (§3.5).
 *
 * `original` follows the photo; an unknown photo falls back to the available area's own aspect,
 * which makes a single empty cell fill the mat exactly (today's `fit_in_mat`). An `auto` leaf
 * takes the *format* turned the photo's way — otherwise picking `1:1` for a single photo would do
 * nothing at all (§3.3 "the photo's own orientation").
 *
 * Every other leaf takes the format exactly as written, orientation included: `4:3` and `3:4` are
 * different pictures, and reading them as the same one is what made half the chips inert.
 */
/**
 * The format cell `index` is laid out with: its own override, else the block's (§3.5).
 *
 * Overrides are per-cell aspects, so they only mean something under a ratio format — `fill` is a
 * property of the whole block (the cells tile the area exactly) and ignores them.
 */
export function cellFormat(composition: Composition, index: number): string {
  if (composition.format === "fill") return "fill";
  return composition.cell_formats[index] || composition.format;
}

function leafAspect(cell: RecipeCell, format: string, photo: Size | null, area: Rect): number {
  if (format === "original") return photo ? photo.w / photo.h : area.w / area.h;
  const ratio = formatRatio(format);
  if (ratio === null) return area.w / area.h;
  if (cell.cell === "auto") {
    const upright = landscapeRatio(ratio);
    return photo !== null && photo.h > photo.w ? 1 / upright : upright;
  }
  // `landscape` and `portrait` leaves both take the format as written: the chip the user picked is
  // the shape they expect to see, and a per-cell override (§3.5) is how one cell differs.
  return cell.cell === "square" ? 1 : ratio;
}

/**
 * The weights every split is laid out with under `fill`, in depth-first order (§3.4).
 *
 * A split takes its entry of `composition.weights` when there is one **of its own shape**, else
 * the recipe's. Where the recipe declares a `balance`, the root is `[b, 1−b]` whatever the block
 * says: `balance` stays the one name of that division. An entry of the wrong length is ignored
 * rather than thrown on — the solver is total (§3.6), the server's reference check reports it.
 */
export function splitWeights(recipe: Recipe, composition: Composition): number[][] {
  return splits(recipe.tree).map((node, index) => {
    const override = composition.weights[index] ?? null;
    if (index === 0 && recipe.balance) {
      const share = composition.balance ?? recipe.balance.default;
      return [share, 1 - share];
    }
    if (override !== null && override.length === node.children.length) return [...override];
    return [...node.weights];
  });
}

/** Round a footprint's float edges, then deflate it by the border to get the photo rect. */
function toCell(index: number, footprint: Box, border: number): Cell {
  const left = roundHalfEven(footprint.x) + border;
  const top = roundHalfEven(footprint.y) + border;
  const right = roundHalfEven(footprint.x + footprint.w) - border;
  const bottom = roundHalfEven(footprint.y + footprint.h) - border;
  const w = Math.max(1, right - left);
  const h = Math.max(1, bottom - top);
  return { id: cellId(index), rect: { x: left, y: top, w, h }, ratio_label: ratioLabel(w, h) };
}

// ---- fill format (§3.4) ------------------------------------------------------------------------
/**
 * Weighted split filling `box` exactly; gutters stay exact, the last child snaps to the edge.
 *
 * `split` is this node's index in `weightsOf` if it is a split; returns the next free index.
 */
function walkFill(
  node: RecipeNode,
  box: Box,
  weightsOf: number[][],
  split: number,
  gutterX: number,
  gutterY: number,
  out: Box[],
): number {
  if (isCell(node)) {
    out.push(box);
    return split;
  }
  const weights = weightsOf[split]!;
  let following = split + 1;
  const total = weights.reduce((sum, weight) => sum + weight, 0);
  const count = node.children.length;
  const row = node.split === "row";
  const gutter = row ? gutterX : gutterY;
  const span = (row ? box.w : box.h) - (count - 1) * gutter;
  const origin = row ? box.x : box.y;
  let accumulated = 0;
  let start = origin;
  for (let index = 0; index < count; index++) {
    accumulated += (span * weights[index]!) / total;
    let end = origin + accumulated + index * gutter;
    if (index === count - 1) end = origin + (row ? box.w : box.h);
    const childBox: Box = row
      ? { x: start, y: box.y, w: Math.max(0, end - start), h: box.h }
      : { x: box.x, y: start, w: box.w, h: Math.max(0, end - start) };
    following = walkFill(
      node.children[index]!,
      childBox,
      weightsOf,
      following,
      gutterX,
      gutterY,
      out,
    );
    start = end + gutter;
  }
  return following;
}

// ---- ratio format (§3.5) -----------------------------------------------------------------------
/** Bottom-up `w = α·h + β` on footprints; returns the subtree and the next leaf index. */
function relate(
  node: RecipeNode,
  aspects: number[],
  start: number,
  border: number,
  gutterX: number,
  gutterY: number,
): [Relation, number] {
  if (isCell(node)) {
    const aspect = aspects[start]!;
    return [
      { affine: { alpha: aspect, beta: 2 * border * (1 - aspect) }, children: [] },
      start + 1,
    ];
  }
  const children: Relation[] = [];
  let index = start;
  for (const child of node.children) {
    const [relation, next] = relate(child, aspects, index, border, gutterX, gutterY);
    children.push(relation);
    index = next;
  }
  const parts = children.map((child) => child.affine);
  const gaps = parts.length - 1;
  let alpha: number;
  let beta: number;
  if (node.split === "row") {
    alpha = parts.reduce((sum, part) => sum + part.alpha, 0);
    beta = parts.reduce((sum, part) => sum + part.beta, 0) + gaps * gutterX;
  } else {
    // Children share the width: hᵢ = (w − βᵢ)/αᵢ and h = Σhᵢ + gaps·gutterY; invert.
    alpha = 1 / parts.reduce((sum, part) => sum + 1 / part.alpha, 0);
    beta = alpha * (parts.reduce((sum, part) => sum + part.beta / part.alpha, 0) - gaps * gutterY);
  }
  return [{ affine: { alpha, beta }, children }, index];
}

/** Largest block honouring `affine` inside `area`, centred — `outer` is a minimum (§3.5). */
function fitBlock(affine: Affine, area: Box): Box {
  let height = area.h;
  let width = affine.alpha * height + affine.beta;
  if (width > area.w) {
    width = area.w;
    height = (area.w - affine.beta) / affine.alpha;
  }
  width = Math.max(1, width);
  height = Math.max(1, height);
  return {
    x: area.x + (area.w - width) / 2,
    y: area.y + (area.h - height) / 2,
    w: width,
    h: height,
  };
}

/** Top-down: child sizes come from the affine relations, edges still accumulate as floats. */
function walkRatio(
  node: RecipeNode,
  relation: Relation,
  box: Box,
  gutterX: number,
  gutterY: number,
  out: Box[],
): void {
  if (isCell(node)) {
    out.push(box);
    return;
  }
  const row = node.split === "row";
  const gutter = row ? gutterX : gutterY;
  const count = node.children.length;
  const origin = row ? box.x : box.y;
  let accumulated = 0;
  let start = origin;
  for (let index = 0; index < count; index++) {
    const affine = relation.children[index]!.affine;
    accumulated += row ? affine.alpha * box.h + affine.beta : (box.w - affine.beta) / affine.alpha;
    let end = origin + accumulated + index * gutter;
    if (index === count - 1) end = origin + (row ? box.w : box.h);
    const childBox: Box = row
      ? { x: start, y: box.y, w: Math.max(0, end - start), h: box.h }
      : { x: box.x, y: start, w: box.w, h: Math.max(0, end - start) };
    walkRatio(node.children[index]!, relation.children[index]!, childBox, gutterX, gutterY, out);
    start = end + gutter;
  }
}

// ---- what the solver writes back (§3.7, §4.1) ---------------------------------------------------
/**
 * Effective insets of the block's footprint bounding box — written back to `margins` (§3.7).
 * Keeps the Advanced panels and every existing helper reading a truthful document.
 */
export function blockMargins(cells: Cell[], border: number, canvas: Size = CANVAS): Margins {
  if (cells.length === 0) return { top: 0, right: 0, bottom: 0, left: 0 };
  const left = Math.min(...cells.map((cell) => cell.rect.x)) - border;
  const top = Math.min(...cells.map((cell) => cell.rect.y)) - border;
  const right = Math.max(...cells.map((cell) => cell.rect.x + cell.rect.w)) + border;
  const bottom = Math.max(...cells.map((cell) => cell.rect.y + cell.rect.h)) + border;
  return {
    top: Math.max(0, Math.min(top, canvas.h - 1)),
    right: Math.max(0, Math.min(canvas.w - right, canvas.w - 1)),
    bottom: Math.max(0, Math.min(canvas.h - bottom, canvas.h - 1)),
    left: Math.max(0, Math.min(left, canvas.w - 1)),
  };
}

/**
 * Crop for a cell that moved: previous centre and zoom kept, new aspect imposed (§4.1).
 *
 * Zoom is `previous.w` relative to the largest crop at the new ratio, so reframing a photo
 * survives a margin drag — the invariant users notice first. No previous crop ⇒ centred cover.
 *
 * The height comes from the **width and the ratio**, never from scaling `full.h`: rounding two
 * independent sides can leave the crop just outside `aspectConsistent`, and a document the server
 * would reject is exactly what invariant 11 forbids.
 */
export function refitCrop(previous: Rect | null, source: Size, ratio: number | null): Rect {
  const full = largestCrop(source, ratio);
  if (previous === null) return full;
  const zoom = Math.min(1, Math.max(0, previous.w / full.w));
  const w = Math.max(1, Math.min(full.w, roundHalfEven(full.w * zoom)));
  const h =
    ratio === null
      ? Math.max(1, Math.min(full.h, roundHalfEven(full.h * zoom)))
      : Math.max(1, Math.min(full.h, roundHalfEven(w / ratio)));
  const [centerX, centerY] = cropCenter(previous);
  return {
    x: Math.min(Math.max(0, roundHalfEven(centerX - w / 2)), source.w - w),
    y: Math.min(Math.max(0, roundHalfEven(centerY - h / 2)), source.h - h),
    w,
    h,
  };
}

/** Typography of the derived caption — the style's `caption_defaults` (§3.7). */
export interface CaptionStyle {
  font: string;
  weight: number;
  size: number;
  color: string;
  letter_spacing: number;
}

export const DEFAULT_CAPTION_STYLE: CaptionStyle = {
  font: "cormorant-garamond",
  weight: 500,
  size: DEFAULT_CAPTION_SIZE,
  color: "#3A3A3A",
  letter_spacing: 0.02,
};

/**
 * The document's own caption typography, else the built-in defaults.
 *
 * A composition carries the caption *text and side*, never its font: re-solving must keep the
 * typography the style gave the artwork at creation (and anything the user changed since).
 */
export function captionStyleOf(doc: EditorDocument): CaptionStyle {
  const caption = doc.captions[0];
  if (!caption) return { ...DEFAULT_CAPTION_STYLE };
  return {
    font: caption.font,
    weight: caption.weight,
    size: caption.size,
    color: caption.color,
    letter_spacing: caption.letter_spacing,
  };
}

/**
 * Baseline `y` of the derived caption, inside the band `blockArea` reserved (§3.3).
 *
 * The band holds a line of `CAPTION_BAND_FACTOR × size` against the outer margin and the gutter on
 * the block's side; the baseline sits `CAPTION_BASELINE_FACTOR × size` below the line's top. Uses
 * the nominal `outer`, so an over-constrained document that made the solver relax (§3.6) keeps its
 * caption where the parameters asked — the block moved, the text did not.
 */
export function captionBaseline(
  composition: Composition,
  captionSize: number,
  canvas: Size = CANVAS,
): number {
  const offset = roundHalfEven(captionSize * CAPTION_BASELINE_FACTOR);
  if (composition.caption.place === "above") return composition.outer.y + offset;
  const line = roundHalfEven(captionSize * CAPTION_BAND_FACTOR);
  return canvas.h - composition.outer.y - line + offset;
}

/**
 * One slot rewritten from its cell (§3.7): rect, crop, ratio, lock and the border band.
 *
 * `photo_id`, `orient`, `shadow` and the crop's framing (centre + zoom) come from the slot. An
 * empty slot is a placeholder: crop = the cell, `free` lock — filling it takes `no_upscale` back,
 * or an emptied slot would silently allow upscaling afterwards.
 */
function solvedSlot(slot: DocSlot, cell: Cell, source: Size | null, border: Band | null): DocSlot {
  const rect = cell.rect;
  let crop: Rect = { x: 0, y: 0, w: rect.w, h: rect.h };
  let ratio = "free";
  let lock: QualityLock = "free";
  if (source !== null) {
    const bounds = orientedSize(source, slot.source.orient);
    crop = refitCrop(slot.source.crop, bounds, rect.w / rect.h);
    ratio = cell.ratio_label;
    lock = rect.w > crop.w || rect.h > crop.h ? "free" : "no_upscale";
  }
  return {
    id: slot.id,
    photo_id: slot.photo_id,
    rect: { ...rect },
    rotation: 0,
    source: { orient: { ...slot.source.orient }, crop, crop_ratio: ratio },
    quality_lock: lock,
    bands: border ? [{ ...border }] : [],
    shadow: slot.shadow ? { ...slot.shadow } : null,
  };
}

/**
 * The one caption a composition owns (§3.7); none when it is off or has no text yet.
 *
 * `align` puts it on the canvas' centre line or flush with the block's printed edge — `margins`
 * are the block's effective insets, so the text lines up with what the eye sees, border included.
 */
function derivedCaption(
  doc: EditorDocument,
  composition: Composition,
  style: CaptionStyle,
  margins: Margins,
  canvas: Size,
): DocCaption[] {
  const text = composition.caption.text.trim();
  if (composition.caption.place === "none" || text === "") return [];
  const previous = doc.captions[0];
  let anchor: CaptionAnchor = "middle";
  let x = Math.floor(canvas.w / 2);
  if (composition.caption.align === "left") {
    anchor = "start";
    x = margins.left;
  } else if (composition.caption.align === "right") {
    anchor = "end";
    x = canvas.w - margins.right;
  }
  return [
    {
      id: previous ? previous.id : DERIVED_CAPTION_ID,
      text,
      font: style.font,
      weight: style.weight,
      size: style.size,
      color: style.color,
      letter_spacing: style.letter_spacing,
      x,
      y: captionBaseline(composition, style.size, canvas),
      anchor,
      rotation: 0,
    },
  ];
}

/**
 * `doc` with its geometry re-derived from its `composition` block — §3.7's table.
 *
 * The composition is the source of truth while `detached` is false, so this is what the server
 * stores and what the editor previews (same function, both languages). Everything the block does
 * not describe is carried over from `doc`: mat, orient, shadows, photo ids.
 *
 * A document without a composition, or a detached one, is returned unchanged: the slots are then
 * the truth (§5). `photoSizes` maps photo ids to their **unoriented** size; a photo missing from
 * it is treated as an empty slot, which is also what the server's reference check will report.
 */
export function applyComposition(
  doc: EditorDocument,
  recipe: Recipe,
  photoSizes: Record<string, Size>,
  caption: CaptionStyle | null = null,
  canvas: Size = CANVAS,
): EditorDocument {
  const composition = doc.composition;
  if (composition === null || composition.detached) return doc;
  const style = caption ?? captionStyleOf(doc);
  const sizeOf = (slot: DocSlot): Size | null =>
    slot.photo_id === null ? null : (photoSizes[slot.photo_id] ?? null);
  const cells = solve(recipe, composition, doc.slots.map(sizeOf), style.size, canvas);
  const border: Band | null = composition.border
    ? {
        width: composition.border.width,
        color: composition.border.color,
        bevel: composition.border.bevel,
      }
    : null;
  const slots = doc.slots
    .map((slot, index) => {
      const cell = cells[index];
      return cell ? solvedSlot(slot, cell, sizeOf(slot), border) : slot;
    })
    .slice(0, doc.slots.length);
  const margins = blockMargins(cells, composition.border ? composition.border.width : 0, canvas);
  return {
    ...doc,
    placement: "manual",
    margins: { ...margins, linked: false, mirror_x: false, mirror_y: false },
    slots,
    captions: derivedCaption(doc, composition, style, margins, canvas),
  };
}
