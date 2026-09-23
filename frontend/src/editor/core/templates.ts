// Frame styles and layouts applied to a document (Phase 8, docs/templates.md §3).
//
// PURE mirror of `backend/src/the_frame_v2/domain/templates.py`; parity pinned by
// `conformance/geometry/templates*.json`. The editor applies a template to the working document
// and the server applies the same one during a push update, so the two must agree field by field.
import {
  applyComposition,
  DEFAULT_CAPTION_STYLE,
  type CaptionStyle,
  type Composition,
  type CompositionBorder,
  type Recipe,
} from "./composition.ts";
import type {
  Band,
  DocCaption,
  DocMargins,
  DocSlot,
  EditorDocument,
  Mat,
  Shadow,
} from "./document.ts";
import type { Size } from "./geometry.ts";
import type { QualityLock } from "./placement.ts";

export type CaptionPlace = "none" | "above" | "below";

export interface SlotDefaults {
  bands: Band[];
  shadow: Shadow | null;
  quality_lock: QualityLock;
}

/** A frame style document: a *look*, never a geometry (`GET /frame-styles`). */
export interface StyleDocument {
  mat: Mat;
  margins: DocMargins;
  slot_defaults: SlotDefaults;
  caption_defaults: CaptionStyle;
}

/** A layout document: the `composition` block minus the caption's text and `detached`. */
export interface LayoutDocument {
  recipe: string;
  balance: number | null;
  outer: { x: number; y: number };
  gutter: { x: number; y: number };
  format: string;
  cell_formats: (string | null)[];
  border: CompositionBorder | null;
  caption_place: CaptionPlace;
}

/** The composition an artwork starts from, carrying its own caption text. */
export function layoutBlock(layout: LayoutDocument, text = ""): Composition {
  return {
    recipe: layout.recipe,
    balance: layout.balance,
    outer: { ...layout.outer },
    gutter: { ...layout.gutter },
    format: layout.format,
    cell_formats: [...layout.cell_formats],
    border: layout.border ? { ...layout.border } : null,
    caption: { text, place: layout.caption_place },
    detached: false,
  };
}

/** "Save as layout": the artwork's parameters, without its caption text. */
export function layoutOfDocument(doc: EditorDocument): LayoutDocument | null {
  const block = doc.composition;
  if (block === null || block.detached) return null;
  return {
    recipe: block.recipe,
    balance: block.balance,
    outer: { ...block.outer },
    gutter: { ...block.gutter },
    format: block.format,
    cell_formats: [...block.cell_formats],
    border: block.border ? { ...block.border } : null,
    caption_place: block.caption.place,
  };
}

/** "Save as style": the look of `doc`, without its geometry. */
export function styleOfDocument(doc: EditorDocument): StyleDocument {
  const slot = doc.slots[0] ?? null;
  const block = doc.composition;
  let bands: Band[] = [];
  if (block !== null && !block.detached) {
    if (block.border !== null) bands = [{ width: block.border.width, color: block.border.color }];
  } else if (slot !== null) {
    bands = slot.bands.map((band) => ({ ...band }));
  }
  const caption = doc.captions[0];
  return {
    mat: { color: doc.mat.color, texture: doc.mat.texture ? { ...doc.mat.texture } : null },
    margins: { ...doc.margins },
    slot_defaults: {
      bands,
      shadow: slot && slot.shadow ? { ...slot.shadow } : null,
      quality_lock: "no_upscale",
    },
    caption_defaults: caption
      ? {
          font: caption.font,
          weight: caption.weight,
          size: caption.size,
          color: caption.color,
          letter_spacing: caption.letter_spacing,
        }
      : { ...DEFAULT_CAPTION_STYLE },
  };
}

function dressedSlot(slot: DocSlot, defaults: SlotDefaults, bands: boolean): DocSlot {
  return {
    ...slot,
    rect: { ...slot.rect },
    source: { ...slot.source, orient: { ...slot.source.orient }, crop: { ...slot.source.crop } },
    bands: bands ? defaults.bands.map((band) => ({ ...band })) : slot.bands.map((b) => ({ ...b })),
    shadow: defaults.shadow ? { ...defaults.shadow } : null,
  };
}

function dressedCaption(caption: DocCaption, defaults: CaptionStyle): DocCaption {
  return { ...caption, ...defaults };
}

/**
 * Re-dress `doc` in `style` — mat, shadow, band, caption typography — keeping its layout.
 *
 * The style's `margins` are deliberately left out: under a composition the block owns them (§3.7),
 * and re-dressing must never move a photo the user placed. The band becomes `composition.border`
 * while a block is attached, since that is who writes `bands` from then on; a hand-built or
 * detached document takes the bands directly.
 *
 * A document that has no caption yet is solved with the style's typography, so a caption typed
 * afterwards is the style's.
 */
export function restyle(
  doc: EditorDocument,
  style: StyleDocument,
  recipe: Recipe | null,
  photoSizes: Record<string, Size>,
): EditorDocument {
  const block = doc.composition;
  const attached = block !== null && !block.detached;
  const defaults = style.slot_defaults;
  const slots = doc.slots.map((slot) => dressedSlot(slot, defaults, !attached));
  const captions = doc.captions.map((caption) => dressedCaption(caption, style.caption_defaults));
  const mat: Mat = {
    color: style.mat.color,
    texture: style.mat.texture ? { ...style.mat.texture } : null,
  };
  if (!attached || block === null) return { ...doc, mat, slots, captions };
  const band = defaults.bands[0];
  const restyled: Composition = {
    ...block,
    border: band ? { width: Math.max(1, band.width), color: band.color } : null,
  };
  const dressed: EditorDocument = { ...doc, mat, composition: restyled, slots, captions };
  if (recipe === null) return dressed;
  return applyComposition(
    dressed,
    recipe,
    photoSizes,
    captions.length === 0 ? style.caption_defaults : null,
  );
}

/**
 * Give `doc` the layout's recipe and parameters, then re-solve (§3.7).
 *
 * The artwork's caption text moves into the new block — a layout carries the side, never the
 * words — and a detached artwork is re-attached: applying a layout is exactly the "Re-apply
 * layout" of docs/simple-editor.md §5 with someone else's parameters.
 */
export function relayout(
  doc: EditorDocument,
  layout: LayoutDocument,
  recipe: Recipe,
  photoSizes: Record<string, Size>,
  caption: CaptionStyle | null = null,
): EditorDocument {
  const block = doc.composition;
  const text = block ? block.caption.text : (doc.captions[0]?.text ?? "");
  return applyComposition(
    { ...doc, composition: layoutBlock(layout, text) },
    recipe,
    photoSizes,
    caption,
  );
}
