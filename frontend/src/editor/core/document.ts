// The artwork document as the editor manipulates it: same shape as the API model
// (docs/artwork-document.md) but with every optional field filled in, so edits never have to
// guess a default. `normalizeDocument` is applied on load and the result is sent back as is.
import type { ArtworkDocument as ApiDocument } from "@/api/client";
import type { Composition } from "./composition.ts";
import { CANVAS_HEIGHT, CANVAS_WIDTH, type Margins, type Orient, type Rect } from "./geometry.ts";
import type { QualityLock } from "./placement.ts";

export type Placement = "fit_in_mat" | "fill" | "manual";
export type CaptionAnchor = "start" | "middle" | "end";

export interface TextureRef {
  id: string;
  strength: number;
}

export interface Mat {
  color: string;
  texture: TextureRef | null;
}

export interface DocMargins extends Margins {
  /** All four margins move together. */
  linked: boolean;
  /** `left` and `right` stay equal. */
  mirror_x: boolean;
  /** `top` and `bottom` stay equal. */
  mirror_y: boolean;
}

export interface Band {
  width: number;
  color: string;
  /** Drawn as the cut edge of a mat window: four mitred, shaded faces (rendering-spec.md §8.1). */
  bevel: boolean;
}

/** The shadow the TV's frame casts onto the artwork: an inner shadow of the whole canvas. */
export interface EdgeShadow {
  offset_x: number;
  offset_y: number;
  blur: number;
  color: string;
  opacity: number;
}

export interface Shadow {
  type: "inner" | "drop";
  offset_x: number;
  offset_y: number;
  blur: number;
  color: string;
  opacity: number;
}

export interface DocSlot {
  id: string;
  photo_id: string | null;
  rect: Rect;
  rotation: number;
  source: { orient: Orient; crop: Rect; crop_ratio: string };
  quality_lock: QualityLock;
  bands: Band[];
  shadow: Shadow | null;
}

export interface DocCaption {
  id: string;
  text: string;
  font: string;
  weight: number;
  size: number;
  color: string;
  letter_spacing: number;
  x: number;
  y: number;
  anchor: CaptionAnchor;
  rotation: number;
}

export interface EditorDocument {
  schema: 1;
  canvas: { width: number; height: number };
  mat: Mat;
  placement: Placement;
  margins: DocMargins;
  /** Parametric layout driving the slots (Phase 7); null = hand-built or legacy. */
  composition: Composition | null;
  slots: DocSlot[];
  captions: DocCaption[];
  /** The frame's shadow on the artwork, drawn over everything else; null = none. */
  edge_shadow: EdgeShadow | null;
}

/** Fill in the optional fields of a `composition` block so edits never have to guess a default. */
export function normalizeComposition(raw: NonNullable<ApiDocument["composition"]>): Composition {
  return {
    recipe: raw.recipe,
    balance: raw.balance ?? null,
    weights: (raw.weights ?? []).map((entry) => (entry ? [...entry] : null)),
    outer: { x: raw.outer?.x ?? 120, y: raw.outer?.y ?? 120 },
    gutter: { x: raw.gutter?.x ?? 80, y: raw.gutter?.y ?? 80 },
    format: raw.format ?? "fill",
    cell_formats: [...(raw.cell_formats ?? [])],
    border: raw.border ? { ...raw.border, bevel: raw.border.bevel ?? false } : null,
    caption: {
      text: raw.caption?.text ?? "",
      place: raw.caption?.place ?? "none",
      align: raw.caption?.align ?? "center",
    },
    detached: raw.detached ?? false,
  };
}

/** Fill in every optional field of an API document (the server always sends them; be safe). */
export function normalizeDocument(raw: ApiDocument): EditorDocument {
  const mat = raw.mat ?? { color: "#F2EFE8", texture: null };
  const margins = raw.margins ?? {
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    linked: false,
    mirror_x: false,
    mirror_y: false,
  };
  return {
    schema: 1,
    canvas: raw.canvas ?? { width: CANVAS_WIDTH, height: CANVAS_HEIGHT },
    mat: { color: mat.color, texture: mat.texture ?? null },
    placement: raw.placement,
    margins: {
      top: margins.top,
      right: margins.right,
      bottom: margins.bottom,
      left: margins.left,
      linked: margins.linked,
      mirror_x: margins.mirror_x ?? false,
      mirror_y: margins.mirror_y ?? false,
    },
    composition: raw.composition ? normalizeComposition(raw.composition) : null,
    slots: (raw.slots ?? []).map((slot) => ({
      id: slot.id,
      photo_id: slot.photo_id ?? null,
      rect: { ...slot.rect },
      rotation: slot.rotation,
      source: {
        orient: slot.source.orient ?? { rotate: 0, flip_h: false },
        crop: { ...slot.source.crop },
        crop_ratio: slot.source.crop_ratio,
      },
      quality_lock: slot.quality_lock,
      bands: (slot.bands ?? []).map((band) => ({ ...band, bevel: band.bevel ?? false })),
      shadow: slot.shadow ? { ...slot.shadow } : null,
    })),
    captions: (raw.captions ?? []).map((caption) => ({ ...caption })),
    edge_shadow: raw.edge_shadow ? { ...raw.edge_shadow } : null,
  };
}

export const toApiDocument = (doc: EditorDocument): ApiDocument => doc as ApiDocument;

export function findSlot(doc: EditorDocument, slotId: string | null): DocSlot | null {
  return doc.slots.find((slot) => slot.id === slotId) ?? null;
}

/** Total band thickness around a slot's photo (the drawn layer is that much larger). */
export function bandWidth(slot: DocSlot): number {
  return slot.bands.reduce((total, band) => total + band.width, 0);
}

/** Documents are compared by value to know whether anything still needs saving. */
export function sameDocument(a: EditorDocument, b: EditorDocument): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
