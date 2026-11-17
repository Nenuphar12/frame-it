// The editor's propagation rules (`operations.ts`): how one edit carries into the rest of the
// document. Not a test per function — the rules that are easy to break and that only show on
// screen otherwise. The geometry they call is covered by the conformance fixtures; the server
// re-validates every save. Run by Node: `pnpm test` (in `make check`).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { produce, type Draft } from "immer";

import type { Recipe } from "./core/composition.ts";
import type { DocCaption, DocSlot, EditorDocument } from "./core/document.ts";
import { straightenedSize, type Rect } from "./core/geometry.ts";
import {
  MAX_ZOOM,
  MIN_ZOOM,
  addSlot,
  attachComposition,
  balanceFor,
  detach,
  flipSource,
  moveSlot,
  photoZoom,
  reapplyLayout,
  recipeFollowsPhotoCount,
  rotateSource,
  setBands,
  setLock,
  setMargins,
  setNativeFraming,
  setPhotoZoom,
  setRotation,
  setShadow,
  setSlotPhoto,
  setStraighten,
  slotOriented,
  swapPhotos,
  zoomCrop,
  type PhotoSizes,
} from "./operations.ts";

const SIZES: PhotoSizes = {
  wide: { w: 6000, h: 4000 },
  tall: { w: 3000, h: 4500 },
  square: { w: 3000, h: 3000 },
};

const RECIPES = (
  JSON.parse(
    readFileSync(
      join(import.meta.dirname, "../../../backend/src/frame_it/assets/presets/recipes.json"),
      "utf8",
    ),
  ) as { recipes: Recipe[] }
).recipes;

function recipe(id: string): Recipe {
  const found = RECIPES.find((r) => r.id === id);
  if (!found) throw new Error(`unknown recipe ${id}`);
  return found;
}

/** Every edit goes through an Immer draft, as in the store (`resolveComposition` needs one). */
const edit = (doc: EditorDocument, change: (draft: Draft<EditorDocument>) => void) =>
  produce(doc, change);

function slot(id: string, photo: string | null, rect: Rect): DocSlot {
  const size = photo ? SIZES[photo] : undefined;
  return {
    id,
    photo_id: photo,
    rect,
    rotation: 0,
    source: {
      orient: { rotate: 0, flip_h: false },
      straighten: 0,
      crop: size ? { x: 0, y: 0, w: size.w, h: size.h } : { x: 0, y: 0, w: rect.w, h: rect.h },
      crop_ratio: size ? "original" : "free",
    },
    quality_lock: "no_upscale",
    bands: [],
    shadow: null,
  };
}

function document(slots: DocSlot[], placement: EditorDocument["placement"]): EditorDocument {
  return {
    schema: 1,
    canvas: { width: 3840, height: 2160 },
    mat: { color: "#F2EFE8", texture: null },
    placement,
    margins: {
      top: 200,
      right: 200,
      bottom: 260,
      left: 200,
      linked: false,
      mirror_x: false,
      mirror_y: false,
    },
    composition: null,
    slots,
    captions: [],
    edge_shadow: null,
  };
}

/** One photo in the mat (`fit_in_mat`), placed by the rules themselves. */
function single(photo = "wide"): EditorDocument {
  const doc = document([slot("s_1", photo, { x: 0, y: 0, w: 100, h: 100 })], "fit_in_mat");
  return edit(doc, (d) => setMargins(d, {}, SIZES));
}

/** Several photos laid out by a recipe (an attached composition). */
function composed(recipeId: string, photos: string[]): EditorDocument {
  const slots = photos.map((photo, i) =>
    slot(`s_${i + 1}`, photo, { x: 100 * i, y: 0, w: 100, h: 100 }),
  );
  const doc = document(slots, photos.length > 1 ? "manual" : "fit_in_mat");
  return edit(doc, (d) => attachComposition(d, recipe(recipeId), RECIPES, SIZES));
}

const first = (doc: EditorDocument): DocSlot => {
  const found = doc.slots[0];
  if (!found) throw new Error("no slot");
  return found;
};
const aspect = (r: { w: number; h: number }) => r.w / r.h;

// ---- the mat and its margins ---------------------------------------------------------------------

test("margins re-place the photo inside them, whole", () => {
  const doc = edit(single(), (d) => setMargins(d, { left: 600 }, SIZES));
  const s = first(doc);
  assert.ok(s.rect.x >= 600 && s.rect.x + s.rect.w <= 3840 - 200);
  assert.ok(s.rect.y >= 200 && s.rect.y + s.rect.h <= 2160 - 260);
  assert.deepEqual(s.source.crop, { x: 0, y: 0, w: 6000, h: 4000 });
});

test("linked margins move together; a mirrored axis follows the side that moved", () => {
  const linked = edit(single(), (d) => setMargins(d, { linked: true, top: 300 }, SIZES));
  const { top, right, bottom, left } = linked.margins;
  assert.deepEqual([top, right, bottom, left], [300, 300, 300, 300]);
  const mirrored = edit(single(), (d) => setMargins(d, { mirror_x: true, left: 500 }, SIZES));
  assert.equal(mirrored.margins.right, 500);
});

test("a margin never eats the whole canvas", () => {
  const doc = edit(single(), (d) => setMargins(d, { left: 99_999 }, SIZES));
  assert.equal(doc.margins.left, 3839);
  assert.equal(doc.margins.right, 0);
});

// ---- native linking and the quality lock ---------------------------------------------------------

test("native: the slot is the crop pixel for pixel, and the free space becomes the margins", () => {
  const doc = edit(single(), (d) => setLock(d, d.slots[0]!, "native", SIZES));
  const s = first(doc);
  assert.equal(s.quality_lock, "native");
  assert.deepEqual([s.rect.w, s.rect.h], [s.source.crop.w, s.source.crop.h]);
  assert.equal(doc.margins.left + s.rect.w + doc.margins.right, 3840);
  assert.equal(doc.margins.top + s.rect.h + doc.margins.bottom, 2160);
});

test("native forbids rotation, both ways", () => {
  const turned = edit(single(), (d) => setRotation(d.slots[0]!, 10));
  const locked = edit(turned, (d) => setLock(d, d.slots[0]!, "native", SIZES));
  assert.equal(first(locked).rotation, 0);
  const rotatedAgain = edit(locked, (d) => setRotation(d.slots[0]!, 10));
  assert.equal(first(rotatedAgain).quality_lock, "no_upscale");
});

// ---- turning, mirroring, straightening -----------------------------------------------------------

test("a quarter turn carries the crop instead of resetting it; four give it back", () => {
  const zoomed = edit(single(), (d) => setPhotoZoom(d, d.slots[0]!, 2, SIZES));
  const crop = first(zoomed).source.crop;
  const turned = edit(zoomed, (d) => rotateSource(d, d.slots[0]!, 1, SIZES));
  const after = first(turned).source.crop;
  assert.deepEqual([after.w, after.h], [crop.h, crop.w]); // the same crop, turned
  let doc = turned;
  for (let i = 0; i < 3; i += 1) doc = edit(doc, (d) => rotateSource(d, d.slots[0]!, 1, SIZES));
  assert.deepEqual(first(doc).source.crop, crop);
});

test("a mirror turns the straightening the other way", () => {
  const straight = edit(single(), (d) => setStraighten(d, d.slots[0]!, 3, SIZES));
  const mirrored = edit(straight, (d) => flipSource(d, d.slots[0]!, SIZES));
  assert.equal(first(mirrored).source.straighten, -3);
  const back = edit(mirrored, (d) => flipSource(d, d.slots[0]!, SIZES));
  assert.equal(first(back).source.straighten, 3);
});

test("a straighten gesture that comes back to 0 restores the framing", () => {
  const doc = single();
  const from = { crop: first(doc).source.crop, straighten: 0 };
  const tilted = edit(doc, (d) => setStraighten(d, d.slots[0]!, 4, SIZES, from));
  assert.notDeepEqual(first(tilted).source.crop, from.crop); // 4° needs a tighter crop
  const back = edit(tilted, (d) => setStraighten(d, d.slots[0]!, 0, SIZES, from));
  assert.deepEqual(first(back).source.crop, from.crop);
});

test("a straightened crop stays inside the turned photo", () => {
  const doc = edit(single(), (d) => setStraighten(d, d.slots[0]!, 10, SIZES));
  const s = first(doc);
  const bounds = straightenedSize(slotOriented(s, SIZES)!, 10);
  const { x, y, w, h } = s.source.crop;
  assert.ok(x >= 0 && y >= 0 && x + w <= bounds.w && y + h <= bounds.h);
});

// ---- zoom ------------------------------------------------------------------------------------------

test("the wheel cannot zoom past the slider's bounds", () => {
  let doc = edit(single(), (d) => setLock(d, d.slots[0]!, "free", SIZES));
  for (let i = 0; i < 20; i += 1) doc = edit(doc, (d) => zoomCrop(d, d.slots[0]!, 0.5, SIZES));
  assert.equal(photoZoom(first(doc), SIZES), MAX_ZOOM);
  for (let i = 0; i < 20; i += 1) doc = edit(doc, (d) => zoomCrop(d, d.slots[0]!, 2, SIZES));
  assert.equal(photoZoom(first(doc), SIZES), MIN_ZOOM);
});

test("under the default lock, zooming in stops before the photo is stretched", () => {
  let doc = single(); // `no_upscale`
  for (let i = 0; i < 20; i += 1) doc = edit(doc, (d) => zoomCrop(d, d.slots[0]!, 0.5, SIZES));
  const s = first(doc);
  assert.ok(s.rect.w <= s.source.crop.w && s.rect.h <= s.source.crop.h); // scale ≤ 1
  assert.ok(photoZoom(s, SIZES)! < MAX_ZOOM);
});

// ---- photos and slots ------------------------------------------------------------------------------

test("a photo put in a slot starts upright and straight", () => {
  let doc = edit(single(), (d) => setStraighten(d, d.slots[0]!, 5, SIZES));
  doc = edit(doc, (d) => rotateSource(d, d.slots[0]!, 1, SIZES));
  doc = edit(doc, (d) => setSlotPhoto(d, d.slots[0]!, "square", SIZES));
  assert.equal(first(doc).source.straighten, 0);
  assert.deepEqual(first(doc).source.orient, { rotate: 0, flip_h: false });
});

test("swapped photos are cropped to the slot they land in, and keep their straightening", () => {
  const slots = [
    slot("s_1", "wide", { x: 100, y: 100, w: 1600, h: 900 }),
    slot("s_2", "tall", { x: 2000, y: 100, w: 900, h: 1350 }),
  ];
  let doc = document(slots, "manual");
  doc = edit(doc, (d) => setStraighten(d, d.slots[0]!, 3, SIZES));
  doc = edit(doc, (d) => swapPhotos(d, "s_1", "s_2", SIZES));
  const [a, b] = doc.slots;
  assert.equal(a!.photo_id, "tall");
  assert.equal(b!.photo_id, "wide");
  assert.equal(a!.source.straighten, 0);
  assert.equal(b!.source.straighten, 3); // the horizon belongs to the photo
  for (const s of doc.slots) assert.ok(Math.abs(aspect(s.source.crop) - aspect(s.rect)) < 0.01);
});

test("a second photo makes the artwork manual and takes the front slot's decorations", () => {
  let doc = edit(single(), (d) => {
    setBands(d.slots[0]!, [{ width: 40, color: "#FFFFFF", bevel: true }]);
    setShadow(d.slots[0]!, {
      type: "drop",
      offset_x: 0,
      offset_y: 12,
      blur: 30,
      color: "#000000",
      opacity: 0.3,
    });
  });
  doc = edit(doc, (d) => void addSlot(d, "square", SIZES));
  assert.equal(doc.placement, "manual");
  const added = doc.slots[1]!;
  assert.equal(added.id, "s_2");
  assert.deepEqual(added.bands, first(doc).bands);
  assert.deepEqual(added.shadow, first(doc).shadow);
});

// ---- compositions ------------------------------------------------------------------------------------

test("native framing makes the crop exactly the cell, without moving the cell", () => {
  const doc = composed("two-side-by-side", ["wide", "wide"]);
  const rect = first(doc).rect;
  const native = edit(doc, (d) => setNativeFraming(d, d.slots[0]!, SIZES));
  const s = first(native);
  assert.deepEqual(s.rect, rect);
  assert.deepEqual([s.source.crop.w, s.source.crop.h], [rect.w, rect.h]);
});

test("zooming an attached slot never moves its cell; the lock says whether it upscales", () => {
  const doc = composed("two-side-by-side", ["wide", "tall"]);
  const rect = first(doc).rect;
  const close = edit(doc, (d) => setPhotoZoom(d, d.slots[0]!, 3, SIZES));
  assert.deepEqual(first(close).rect, rect);
  assert.ok(first(close).source.crop.w < rect.w); // a third of the photo, stretched over the cell
  assert.equal(first(close).quality_lock, "free");
  const whole = edit(close, (d) => setPhotoZoom(d, d.slots[0]!, 1, SIZES));
  assert.deepEqual(first(whole).rect, rect);
  assert.equal(first(whole).quality_lock, "no_upscale");
});

test("a balance carried to another recipe is clamped into that recipe's range", () => {
  assert.equal(balanceFor(recipe("two-hero-right"), 0.7), 0.6);
  assert.equal(balanceFor(recipe("two-hero-left"), 0.2), 0.4);
  assert.equal(balanceFor(recipe("two-side-by-side"), 0.5), null); // no balance there
});

test("the recipe follows the photo count: same family, else the first; beyond, detached", () => {
  const grow = (doc: EditorDocument) =>
    edit(doc, (d) => {
      addSlot(d, "square", SIZES);
      recipeFollowsPhotoCount(d, RECIPES, SIZES);
    });
  const hero = grow(composed("two-hero-left", ["wide", "tall"]));
  assert.equal(hero.composition!.recipe, "three-hero-left");
  assert.equal(hero.slots.length, 3);
  const row = grow(composed("two-side-by-side", ["wide", "tall"]));
  assert.equal(row.composition!.recipe, "three-row");
  const seven = grow(composed("six-grid-3x2", ["wide", "wide", "wide", "tall", "tall", "tall"]));
  assert.equal(seven.composition!.detached, true); // no recipe for 7: the slots are the truth
});

test("a hand-made edit detaches the layout; re-applying it gives the solved geometry back", () => {
  const doc = composed("two-side-by-side", ["wide", "tall"]);
  const solved = doc.slots.map((s) => s.rect);
  const moved = edit(doc, (d) => {
    detach(d);
    moveSlot(d.slots[0]!, 50, 0);
  });
  assert.equal(moved.composition!.detached, true);
  assert.equal(first(moved).rect.x, solved[0]!.x + 50);
  const reapplied = edit(moved, (d) => reapplyLayout(d, RECIPES, SIZES));
  assert.equal(reapplied.composition!.detached, false);
  assert.deepEqual(
    reapplied.slots.map((s) => s.rect),
    solved,
  );
});

test("an artwork given a composition keeps its caption's text", () => {
  const caption: DocCaption = {
    id: "c_1",
    text: "Lisbon, 2024",
    font: "inter",
    weight: 400,
    size: 48,
    color: "#333333",
    letter_spacing: 0,
    x: 1920,
    y: 2000,
    anchor: "middle",
    rotation: 0,
  };
  const doc = { ...document([slot("s_1", "wide", { x: 0, y: 0, w: 100, h: 100 })], "fit_in_mat") };
  doc.captions = [caption];
  const attached = edit(doc, (d) => attachComposition(d, recipe("single"), RECIPES, SIZES));
  assert.equal(attached.composition!.caption.text, "Lisbon, 2024");
  assert.equal(attached.composition!.caption.place, "below");
});
