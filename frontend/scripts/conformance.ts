// Checks the TypeScript geometry (src/editor/core) against the shared fixtures in
// conformance/geometry/*.json (the Python side runs in pytest). Plain script, run by Node's
// type stripping: `pnpm conformance`. Spec: docs/PLAN.md §13.3.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import * as alternatives from "../src/editor/core/alternatives.ts";
import * as arrange from "../src/editor/core/arrange.ts";
import * as composition from "../src/editor/core/composition.ts";
import * as constraints from "../src/editor/core/constraints.ts";
import * as geometry from "../src/editor/core/geometry.ts";
import * as placement from "../src/editor/core/placement.ts";
import * as quality from "../src/editor/core/quality.ts";
import * as coreTemplates from "../src/editor/core/templates.ts";

type Args = Record<string, unknown>;
type Fn = (args: Args) => unknown;

const a = <T>(args: Args, key: string) => args[key] as T;

// Recipes come from the backend's bundled catalogue — one source for both solvers (§7).
const CATALOG = JSON.parse(
  readFileSync(
    join(import.meta.dirname, "../../backend/src/the_frame_v2/assets/presets/recipes.json"),
    "utf8",
  ),
) as { recipes: composition.Recipe[] };

function recipe(id: string): composition.Recipe {
  const found = CATALOG.recipes.find((r) => r.id === id);
  if (!found) throw new Error(`unknown recipe ${id}`);
  return found;
}

const FUNCTIONS: Record<string, Fn> = {
  round_half_even: (x) => geometry.roundHalfEven(a(x, "value")),
  oriented_size: (x) => geometry.orientedSize(a(x, "source"), a(x, "orient")),
  rect_to_oriented: (x) => geometry.rectToOriented(a(x, "rect"), a(x, "source"), a(x, "orient")),
  rect_from_oriented: (x) =>
    geometry.rectFromOriented(a(x, "rect"), a(x, "source"), a(x, "orient")),
  reorient_crop: (x) =>
    geometry.reorientCrop(a(x, "crop"), a(x, "source"), a(x, "old"), a(x, "new")),
  crop_within: (x) => geometry.cropWithin(a(x, "crop"), a(x, "bounds")),
  aspect_consistent: (x) =>
    geometry.aspectConsistent(a(x, "rect_w"), a(x, "rect_h"), a(x, "crop_w"), a(x, "crop_h")),
  parse_ratio: (x) => geometry.parseRatio(a(x, "crop_ratio"), a(x, "source")),
  rotated_bounds: (x) =>
    geometry.rotatedBounds(a(x, "rect_x"), a(x, "rect_y"), a(x, "w"), a(x, "h"), a(x, "degrees")),
  slot_quality: (x) => quality.slotQuality(a(x, "slot")),
  artwork_quality: (x) => quality.artworkQuality(a(x, "slots")),
  available_area: (x) => placement.availableArea(a(x, "margins")),
  fit_rect: (x) => placement.fitRect(a(x, "area"), a(x, "content"), a(x, "lock")),
  largest_crop: (x) => placement.largestCrop(a(x, "bounds"), a(x, "ratio"), a(x, "center")),
  native_crop_for_area: (x) =>
    placement.nativeCropForArea(a(x, "area"), a(x, "source"), a(x, "crop_ratio"), a(x, "previous")),
  margins_for_slot: (x) =>
    placement.marginsForSlot(
      a(x, "slot"),
      a(x, "previous"),
      a(x, "linked"),
      geometry.CANVAS,
      a(x, "mirror_x"),
      a(x, "mirror_y"),
    ),
  fit_in_mat: (x) =>
    placement.fitInMat(
      a(x, "source"),
      a(x, "crop"),
      a(x, "crop_ratio"),
      a(x, "margins"),
      a(x, "lock"),
    ),
  fill: (x) => placement.fill(a(x, "source"), a(x, "lock")),
  fill_slot: (x) => placement.fillSlot(a(x, "rect"), a(x, "source"), a(x, "lock")),
  fit_slot: (x) => placement.fitSlot(a(x, "rect"), a(x, "source"), a(x, "lock")),
  ratio_label: (x) => placement.ratioLabel(a(x, "w"), a(x, "h")),
  resize_slot: (x) =>
    constraints.resizeSlot(
      a(x, "state"),
      a(x, "requested"),
      a(x, "source"),
      a(x, "lock"),
      a(x, "anchor"),
    ),
  resize_crop: (x) =>
    constraints.resizeCrop(a(x, "state"), a(x, "requested"), a(x, "source"), a(x, "lock")),
  pan_crop: (x) => constraints.panCrop(a(x, "state"), a(x, "dx"), a(x, "dy"), a(x, "source")),
  zoom_crop: (x) =>
    constraints.zoomCrop(a(x, "state"), a(x, "factor"), a(x, "source"), a(x, "lock")),
  apply_lock: (x) => constraints.applyLock(a(x, "state"), a(x, "lock"), a(x, "source")),
  apply_crop_ratio: (x) =>
    constraints.applyCropRatio(a(x, "state"), a(x, "ratio"), a(x, "source"), a(x, "lock")),
  bounding_box: (x) => arrange.boundingBox(a(x, "rects")),
  align: (x) => arrange.align(a(x, "rects"), a(x, "edge")),
  distribute: (x) => arrange.distribute(a(x, "rects"), a(x, "axis")),
  same_size: (x) => arrange.sameSize(a(x, "rects"), a(x, "reference")),
  new_slot_size: (x) => arrange.newSlotSize(a(x, "area"), a(x, "source")),
  new_slot_rect: (x) => arrange.newSlotRect(a(x, "existing"), a(x, "area"), a(x, "size")),
  composition_solve: (x) =>
    composition.solve(
      recipe(a(x, "recipe")),
      a(x, "composition"),
      a(x, "photo_sizes"),
      a(x, "caption_size"),
    ),
  composition_solve_strict: (x) =>
    composition.solveStrict(
      recipe(a(x, "recipe")),
      a(x, "composition"),
      a(x, "photo_sizes"),
      a(x, "caption_size"),
    ),
  composition_apply: (x) =>
    composition.applyComposition(
      a(x, "doc"),
      recipe(a(x, "recipe")),
      a(x, "photo_sizes"),
      a(x, "caption"),
    ),
  templates_restyle: (x) => {
    const id = a<string | null>(x, "recipe");
    return coreTemplates.restyle(
      a(x, "doc"),
      a(x, "style"),
      id === null ? null : recipe(id),
      a(x, "photo_sizes"),
    );
  },
  templates_relayout: (x) =>
    coreTemplates.relayout(
      a(x, "doc"),
      a(x, "layout"),
      recipe(a(x, "recipe")),
      a(x, "photo_sizes"),
      a(x, "caption"),
    ),
  templates_style_of_document: (x) => coreTemplates.styleOfDocument(a(x, "doc")),
  templates_layout_of_document: (x) => coreTemplates.layoutOfDocument(a(x, "doc")),
  composition_split_weights: (x) =>
    composition.splitWeights(recipe(a(x, "recipe")), a(x, "composition")),
  composition_block_area: (x) => composition.blockArea(a(x, "composition"), a(x, "caption_size")),
  composition_block_margins: (x) => composition.blockMargins(a(x, "cells"), a(x, "border")),
  composition_refit_crop: (x) =>
    composition.refitCrop(a(x, "previous"), a(x, "source"), a(x, "ratio")),
  composition_caption_band: (x) => composition.captionBand(a(x, "caption_size"), a(x, "gutter_y")),
  composition_format_ratio: (x) => composition.formatRatio(a(x, "composition_format")),
  alternatives: (x) =>
    alternatives.alternatives(
      a(x, "state"),
      a(x, "source"),
      a(x, "lock"),
      a(x, "placement"),
      a(x, "margins"),
      a(x, "linked"),
      a(x, "crop_ratio"),
      a(x, "mirror_x"),
      a(x, "mirror_y"),
    ),
};

function close(actual: unknown, expected: unknown): boolean {
  if (typeof expected === "number") {
    return (
      typeof actual === "number" &&
      Math.abs(actual - expected) <= 1e-12 * Math.max(1, Math.abs(expected))
    );
  }
  if (Array.isArray(expected)) {
    return (
      Array.isArray(actual) &&
      actual.length === expected.length &&
      expected.every((value, i) => close(actual[i], value))
    );
  }
  if (expected !== null && typeof expected === "object") {
    if (actual === null || typeof actual !== "object") return false;
    const keys = Object.keys(expected);
    return (
      keys.length === Object.keys(actual).length &&
      keys.every((k) => close((actual as Args)[k], (expected as Args)[k]))
    );
  }
  return actual === expected;
}

const dir = join(import.meta.dirname, "../../conformance/geometry");
let count = 0;
const failures: string[] = [];
for (const file of readdirSync(dir)
  .filter((f) => f.endsWith(".json"))
  .sort()) {
  const { cases } = JSON.parse(readFileSync(join(dir, file), "utf8")) as {
    cases: { name: string; fn: string; input: Args; expected: unknown }[];
  };
  for (const c of cases) {
    count++;
    const fn = FUNCTIONS[c.fn];
    if (!fn) {
      failures.push(`${file}: ${c.name}: no TypeScript mapping for ${c.fn}`);
      continue;
    }
    const actual = fn(c.input);
    if (!close(actual, c.expected)) {
      failures.push(
        `${file}: ${c.name}: got ${JSON.stringify(actual)}, expected ${JSON.stringify(c.expected)}`,
      );
    }
  }
}
if (failures.length > 0) {
  console.error(
    `Geometry conformance failed (${failures.length}/${count}):\n  ${failures.join("\n  ")}`,
  );
  process.exit(1);
}
console.log(`Geometry conformance OK (${count} cases)`);
