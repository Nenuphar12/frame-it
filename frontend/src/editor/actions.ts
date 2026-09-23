// What the editor UI calls: a semantic action per control, bound to the store and the operations.
// Components never touch the document directly, so every change is undoable and autosaved.
import type { Alternative } from "@/editor/core/alternatives.ts";
import type { Composition, Recipe } from "@/editor/core/composition.ts";
import {
  findSlot,
  type DocMargins,
  type DocSlot,
  type EditorDocument,
  type Placement,
} from "@/editor/core/document.ts";
import type { Orient } from "@/editor/core/geometry.ts";
import type { QualityLock } from "@/editor/core/placement.ts";
import * as ops from "@/editor/operations";
import type { Axis, Edge } from "@/editor/core/arrange.ts";
import type { Anchor } from "@/editor/core/constraints.ts";
import type { DocCaption } from "@/editor/core/document.ts";
import type { Size } from "@/editor/core/geometry.ts";
import {
  edit,
  ensurePhotoSize,
  primarySlotId,
  select,
  selectCaption,
  useEditor,
} from "@/editor/store";

/**
 * Run a slot mutation on the *primary* slot — the last one picked. Framing and cropping always
 * work on a single slot; what applies to the whole selection goes through `onSlots`.
 */
function onSlot(
  recipe: (doc: EditorDocument, slot: DocSlot) => void,
  group: string | null = null,
): void {
  const slotId = primarySlotId(useEditor.getState());
  if (!slotId) return;
  edit((doc) => {
    const slot = findSlot(doc, slotId);
    if (slot) recipe(doc, slot);
  }, group);
}

/** Run a slot mutation on every selected slot (locks and decorations apply to all of them). */
function onSlots(
  recipe: (doc: EditorDocument, slot: DocSlot) => void,
  group: string | null = null,
): void {
  const ids = useEditor.getState().selectedSlotIds;
  if (ids.length === 0) return;
  edit((doc) => {
    for (const id of ids) {
      const slot = findSlot(doc, id);
      if (slot) recipe(doc, slot);
    }
  }, group);
}

/** Run a mutation on the selected caption. */
function onCaption(
  recipe: (doc: EditorDocument, captionId: string) => void,
  group: string | null = null,
): void {
  const captionId = useEditor.getState().selectedCaptionId;
  if (!captionId) return;
  edit((doc) => recipe(doc, captionId), group);
}

const sizes = () => useEditor.getState().sizes;

/**
 * Keep an attached composition true after the photos changed (§4.2, §4.4): the recipe follows the
 * new count, then the block re-solves. A no-op for a hand-built or detached document.
 */
function reflow(doc: EditorDocument): void {
  ops.recipeFollowsPhotoCount(doc, useEditor.getState().recipes, sizes());
  ops.resolveComposition(doc, useEditor.getState().recipes, sizes());
}

export const setMargins = (margins: Partial<DocMargins>, group: string | null = "margins") =>
  edit((doc) => {
    ops.setMargins(doc, margins, sizes());
    ops.detach(doc);
  }, group);

export const setPlacement = (placement: Placement) =>
  edit((doc) => {
    ops.setPlacement(doc, placement, sizes());
    ops.detach(doc);
  });

export const setMatColor = (color: string, group: string | null = "mat-color") =>
  edit((doc) => ops.setMatColor(doc, color), group);

export const setTexture = (id: string | null, strength: number, group: string | null = null) =>
  edit((doc) => ops.setTexture(doc, id, strength), group);

/** Re-dress the artwork in a frame style: mat, shadow, border and caption typography. */
export const applyStyle = (style: ops.StyleDocument) =>
  edit((doc) => ops.applyStyle(doc, style, recipes(), sizes()));

/**
 * Caption size (the Simple panel's slider). It is not a free-form edit: the band the solver
 * reserves is a function of the size (§3.3), so the block re-solves around the new one — and the
 * typography round-trips, `apply` reading it back off the document (§3.7).
 */
export const setCaptionSize = (size: number, group: string | null = "caption-size") =>
  edit((doc) => {
    const caption = doc.captions[0];
    if (!caption) return;
    ops.updateCaption(doc, caption.id, { size: Math.max(4, Math.min(1000, Math.round(size))) });
    reflow(doc);
  }, group);

export const setLock = (lock: QualityLock) =>
  onSlots((doc, slot) => {
    ops.setLock(doc, slot, lock, sizes());
    ops.detach(doc);
  });

export const setCropRatio = (ratio: string) =>
  onSlot((doc, slot) => {
    ops.setCropRatio(doc, slot, ratio, sizes());
    ops.detach(doc);
  });

export const setOrient = (orient: Orient) =>
  onSlot((doc, slot) => {
    ops.setOrient(doc, slot, orient, sizes());
    reflow(doc);
  });

export const rotateSource = (turns: number) =>
  onSlot((doc, slot) => {
    ops.rotateSource(doc, slot, turns, sizes());
    reflow(doc);
  });

export const flipSource = () =>
  onSlot((doc, slot) => {
    ops.flipSource(doc, slot, sizes());
    reflow(doc);
  });

export const setRotation = (degrees: number) =>
  onSlot((doc, slot) => {
    ops.setRotation(slot, degrees);
    ops.detach(doc);
  }, "rotation");

export const panCrop = (dx: number, dy: number) =>
  onSlot((doc, slot) => ops.panCrop(doc, slot, dx, dy, sizes()), "crop-pan");

export const zoomCrop = (factor: number) =>
  onSlot((doc, slot) => ops.zoomCrop(doc, slot, factor, sizes()), "crop-zoom");

/** Show the photo pixel for pixel inside its cell (the Simple panel's "Native 100%"). */
export const setNativeFraming = () =>
  onSlot((doc, slot) => ops.setNativeFraming(doc, slot, sizes()));

/** Absolute photo zoom (the panel's slider, §7.5); the wheel uses `zoomCrop`. */
export const setZoom = (zoom: number) =>
  onSlot((doc, slot) => ops.setPhotoZoom(doc, slot, zoom, sizes()), "crop-zoom");

export const setBands = (bands: DocSlot["bands"]) =>
  onSlots((doc, slot) => {
    ops.setBands(slot, bands);
    ops.detach(doc); // the block writes `bands` from its own border (§3.7)
  }, "bands");

export const setShadow = (shadow: DocSlot["shadow"], group: string | null = "shadow") =>
  onSlots((_doc, slot) => ops.setShadow(slot, shadow), group);

export const applyAlternative = (alternative: Alternative) =>
  onSlot((doc, slot) => {
    ops.applyAlternative(doc, slot, alternative);
    ops.detach(doc);
  });

/** Nudge the photo inside its slot (arrow keys; `Shift` = 10 canvas px, §11.5). */
export function nudgeCrop(dx: number, dy: number): void {
  const state = useEditor.getState();
  const slot = state.doc ? findSlot(state.doc, primarySlotId(state)) : null;
  if (!slot) return;
  const perPixel = slot.source.crop.w / Math.max(1, slot.rect.w);
  panCrop(dx * perPixel, dy * perPixel);
}

/**
 * What the arrow keys move (§11.5): the selected caption, the selected slots of a composition,
 * or — with the crop tool, or on a single-slot artwork — the photo inside its slot.
 */
export function nudge(dx: number, dy: number): void {
  const state = useEditor.getState();
  if (state.selectedCaptionId) {
    moveCaption(dx, dy);
    return;
  }
  if (state.tool === "select" && state.doc?.placement === "manual") {
    moveSlots(dx, dy);
    return;
  }
  nudgeCrop(dx, dy);
}

// ---- composition: slots (Phase 6) --------------------------------------------------------------
/** Add a slot (empty when `photoId` is null) and select it. */
export async function addSlot(
  photoId: string | null,
  at: { x: number; y: number } | null = null,
): Promise<void> {
  if (photoId) await ensurePhotoSize(photoId); // its size decides the slot's shape and crop
  let added: string | null = null;
  edit((doc) => {
    added = ops.addSlot(doc, photoId, sizes(), at);
    reflow(doc);
  });
  if (added) select(added);
}

export function removeSelectedSlots(): void {
  const ids = useEditor.getState().selectedSlotIds;
  if (ids.length === 0) return;
  edit((doc) => {
    ops.removeSlots(doc, ids);
    reflow(doc);
  });
  select(null);
}

export async function setSlotPhoto(slotId: string, photoId: string | null): Promise<void> {
  if (photoId) await ensurePhotoSize(photoId);
  edit((doc) => {
    const slot = findSlot(doc, slotId);
    if (slot) ops.setSlotPhoto(doc, slot, photoId, sizes());
    reflow(doc);
  });
}

export const swapPhotos = (firstId: string, secondId: string) =>
  edit((doc) => {
    ops.swapPhotos(doc, firstId, secondId, sizes());
    reflow(doc);
  });

/** Move every selected slot (canvas drag, arrow keys). */
export const moveSlots = (dx: number, dy: number, group: string | null = "slot-move") => {
  if (dx === 0 && dy === 0) return;
  onSlots((doc, slot) => {
    ops.moveSlot(slot, dx, dy);
    ops.detach(doc);
  }, group);
};

export const setSlotPosition = (x: number, y: number) =>
  onSlot((doc, slot) => {
    ops.setSlotPosition(slot, x, y);
    ops.detach(doc);
  }, "slot-move");

export const resizeSlot = (size: Size, anchor: Anchor, group: string | null = "slot-resize") =>
  onSlot((doc, slot) => {
    ops.resizeSlotTo(doc, slot, size, anchor, sizes());
    ops.detach(doc);
  }, group);

export const fitSlotToPhoto = () =>
  onSlots((doc, slot) => {
    ops.fitSlotToPhoto(doc, slot, sizes());
    ops.detach(doc);
  });

export const fillSlotWithPhoto = () =>
  onSlots((doc, slot) => {
    ops.fillSlotWithPhoto(doc, slot, sizes());
    ops.detach(doc);
  });

/** Z-order: `delta` = +1 brings the slot one step forward (§11.5, `[` and `]`). */
export function moveInOrder(delta: number): void {
  const slotId = primarySlotId(useEditor.getState());
  if (!slotId) return;
  edit((doc) => {
    ops.moveSlotInOrder(doc, slotId, delta);
    reflow(doc);
  });
}

export const reorderSlots = (from: number, to: number) =>
  edit((doc) => {
    ops.reorderSlots(doc, from, to);
    reflow(doc);
  });

// ---- composition: arranging a selection --------------------------------------------------------
const selection = () => useEditor.getState().selectedSlotIds;

export const alignSlots = (edge: Edge) =>
  edit((doc) => {
    ops.alignSlots(doc, selection(), edge);
    ops.detach(doc);
  });

export const distributeSlots = (axis: Axis) =>
  edit((doc) => {
    ops.distributeSlots(doc, selection(), axis);
    ops.detach(doc);
  });

export function sameSizeSlots(): void {
  const state = useEditor.getState();
  const primary = primarySlotId(state);
  if (!primary) return;
  edit((doc) => {
    ops.sameSizeSlots(doc, state.selectedSlotIds, primary, sizes());
    ops.detach(doc);
  });
}

export function applyDecorations(): void {
  const state = useEditor.getState();
  const primary = primarySlotId(state);
  if (!primary) return;
  edit((doc) => {
    ops.applyDecorations(doc, primary, state.selectedSlotIds, sizes());
    ops.detach(doc); // it copies the bands across, which the block owns
  });
}

// ---- composition: captions ---------------------------------------------------------------------
export function addCaption(text: string, defaults: Partial<DocCaption> = {}): void {
  let added: string | null = null;
  edit((doc) => {
    added = ops.addCaption(doc, text, defaults);
    ops.detach(doc);
  });
  if (added) selectCaption(added);
}

/** Keys `apply` re-derives from the block: editing one by hand is a free-form edit (§3.7). */
const CAPTION_GEOMETRY: (keyof DocCaption)[] = ["x", "y", "anchor", "rotation"];

export const updateCaption = (patch: Partial<DocCaption>, group: string | null = "caption") =>
  onCaption((doc, id) => {
    ops.updateCaption(doc, id, patch);
    const block = doc.composition;
    if (!block || block.detached) return;
    if (CAPTION_GEOMETRY.some((key) => key in patch)) {
      ops.detach(doc);
      return;
    }
    // Typography round-trips (`apply` reads it back off the document), but the *text* lives in the
    // block: writing it only on the caption would lose it at the next solve.
    if (typeof patch.text === "string" && doc.captions[0]?.id === id) {
      block.caption = {
        text: patch.text,
        place: block.caption.place === "none" ? "below" : block.caption.place,
      };
    }
    reflow(doc);
  }, group);

export const moveCaption = (dx: number, dy: number, group: string | null = "caption-move") =>
  onCaption((doc, id) => {
    ops.moveCaption(doc, id, dx, dy);
    ops.detach(doc);
  }, group);

export function removeCaption(): void {
  const captionId = useEditor.getState().selectedCaptionId;
  if (!captionId) return;
  edit((doc) => {
    ops.removeCaption(doc, captionId);
    ops.detach(doc);
  });
  selectCaption(null);
}

// ---- parametric compositions (Phase 7) ---------------------------------------------------------
const recipes = () => useEditor.getState().recipes;

/** The recipe the document is currently laid out by, if its block is attached (§5). */
export const activeRecipe = (state = useEditor.getState()): Recipe | null =>
  state.doc ? ops.attachedRecipe(state.doc, state.recipes) : null;

/**
 * Change one or more parameters of the block and re-solve (§4.2 triggers).
 *
 * `group` merges a slider drag into one undo step, exactly like the margin sliders.
 */
export const setComposition = (patch: Partial<Composition>, group: string | null = null) =>
  edit((doc) => ops.setComposition(doc, patch, recipes(), sizes()), group);

/** Pick a layout: the recipe of the current block, or a first block for a hand-built artwork. */
export function setRecipe(recipeId: string): void {
  const recipe = recipes().find((item) => item.id === recipeId);
  if (!recipe) return;
  edit((doc) => {
    if (doc.composition && !doc.composition.detached) {
      ops.setComposition(
        doc,
        { recipe: recipe.id, balance: ops.balanceFor(recipe, doc.composition.balance) },
        recipes(),
        sizes(),
      );
    } else {
      ops.attachComposition(doc, recipe, recipes(), sizes());
    }
  });
}

/**
 * "Re-apply layout" (§5): re-solve from the remembered parameters and clear `detached`. One patch,
 * so `⌘Z` puts the hand-made geometry back — which is why the banner can offer it as one button.
 */
export const reapplyLayout = () => edit((doc) => ops.reapplyLayout(doc, recipes(), sizes()));

/** Re-solve after something outside the block changed the photos (add, remove, swap — §4.2/§4.4). */
export const resolveComposition = () =>
  edit((doc) => {
    ops.recipeFollowsPhotoCount(doc, recipes(), sizes());
    ops.resolveComposition(doc, recipes(), sizes());
  });
