// Caption fonts: the editor loads the very files the renderer uses (`GET /fonts/{id}/{w}.ttf`)
// under the same unique family names, so the preview measures the same glyphs (§8.1 step 4).
import { API_BASE } from "@/api/client";

const loaded = new Set<string>();

/** Family name embedded in the bundled files (see scripts/build_fonts.py). */
export const fontFamily = (id: string, weight: number) => `TF ${id} ${weight}`;

/** Register a bundled font with the document; resolves once the glyphs are usable. */
export async function loadFont(id: string, weight: number): Promise<void> {
  const family = fontFamily(id, weight);
  if (loaded.has(family)) return;
  loaded.add(family);
  const face = new FontFace(family, `url(${API_BASE}/fonts/${id}/${weight}.ttf)`);
  try {
    document.fonts.add(await face.load());
  } catch {
    loaded.delete(family);
  }
}

/** The font shorthand Konva gives the 2D context for a `Text` node (`Text._getContextFont`). */
export const contextFont = (size: number, family: string, weight: number) =>
  `${weight} normal ${size}px "${family}"`;

let context: CanvasRenderingContext2D | null = null;

/** Advance width of the text, measured with the very font the canvas will draw with. */
export function measureText(
  text: string,
  size: number,
  family: string,
  weight: number,
  letterSpacingPx: number,
): number {
  context ??= document.createElement("canvas").getContext("2d");
  if (!context) return text.length * size * 0.5;
  context.font = contextFont(size, family, weight);
  return context.measureText(text).width + letterSpacingPx * text.length;
}

/**
 * Distance from a `Text` node's `y` down to the baseline Konva actually draws on: it sets
 * `textBaseline = "alphabetic"` and translates by `(ascent − descent) / 2 + lineHeight / 2`,
 * both measured on an `M` (konva `Text._sceneFunc`). Drawing the node at `caption.y − this`
 * therefore puts the baseline on `caption.y`, where the renderer puts it (§8.1 step 4) — the
 * renderer's own rule (`floor(ascender × size / upm + 0.5)` below the *line top*) does not apply
 * here, because Konva does not place the node's `y` at the line top.
 */
export function baselineOffset(size: number, family: string, weight: number): number {
  context ??= document.createElement("canvas").getContext("2d");
  if (!context) return size * 0.8;
  context.font = contextFont(size, family, weight);
  const metrics = context.measureText("M");
  const ascent = metrics.fontBoundingBoxAscent ?? metrics.actualBoundingBoxAscent;
  const descent = metrics.fontBoundingBoxDescent ?? metrics.actualBoundingBoxDescent;
  return (ascent - descent) / 2 + size / 2;
}

/**
 * Horizontal shift for an anchored caption. Canvas `letterSpacing` also adds space *after* the
 * last glyph while Pango only spaces between them, so the text is shifted back (S3).
 */
export function anchorShift(
  width: number,
  anchor: "start" | "middle" | "end",
  letterSpacingPx: number,
): number {
  if (anchor === "middle") return -width / 2 + letterSpacingPx / 2;
  if (anchor === "end") return -width + letterSpacingPx;
  return 0;
}

/**
 * Ink-ish box of a caption in document coordinates, *before* rotation: what the selection
 * outline draws and what the pointer hit-tests. The width is the advance width the canvas will
 * use, the height a generous line box around the baseline (the exact ink box is the renderer's
 * business — `docs/research/render-parity.md`).
 */
export function captionBox(caption: {
  text: string;
  size: number;
  font: string;
  weight: number;
  letter_spacing: number;
  x: number;
  y: number;
  anchor: "start" | "middle" | "end";
}): { x: number; y: number; w: number; h: number } {
  const family = fontFamily(caption.font, caption.weight);
  const spacing = caption.letter_spacing * caption.size;
  const width = measureText(caption.text, caption.size, family, caption.weight, spacing);
  const baseline = baselineOffset(caption.size, family, caption.weight);
  return {
    x: Math.round(caption.x + anchorShift(width, caption.anchor, spacing)),
    y: Math.round(caption.y - baseline),
    w: Math.max(1, Math.round(width)),
    h: Math.max(1, Math.round(caption.size * 1.3)),
  };
}
