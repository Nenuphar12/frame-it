// A bevelled band: the cut edge of a mat window, as four mitred faces (rendering-spec.md §8.1).
//
// Mirror of `shade` / `BEVEL_SHADES` in backend/src/the_frame_v2/imaging/render.py — the renderer
// is authoritative, this is what the canvas and the template cards draw. Parity of the colours is
// pinned by conformance/geometry/render.json; the geometry is four trapezoids either way.
import type { Rect } from "./geometry.ts";

export type BevelFace = "top" | "left" | "right" | "bottom";

/**
 * How each face is shaded: negative mixes the band colour towards black, positive towards white.
 * Light from above, slightly from the left — the top face (which looks down) is in shade, the
 * bottom one is lit.
 */
export const BEVEL_SHADES: Record<BevelFace, number> = {
  top: -0.3,
  left: -0.12,
  right: 0.35,
  bottom: 0.6,
};

/** `color` (`#RRGGBB`) mixed towards black (`amount < 0`) or white, rounded half up. */
export function shade(color: string, amount: number): [number, number, number] {
  const target = amount > 0 ? 255 : 0;
  const share = Math.abs(amount);
  const channel = (offset: number) => {
    const value = parseInt(color.slice(offset, offset + 2), 16);
    return Math.floor(value + (target - value) * share + 0.5);
  };
  return [channel(1), channel(3), channel(5)];
}

export const faceColor = (color: string, face: BevelFace): string =>
  `rgb(${shade(color, BEVEL_SHADES[face]).join(",")})`;

/**
 * The four faces of a band `width` thick whose **outer** edge is `outer`, as closed polygons
 * (`x, y` pairs). Drawn in this order the top and bottom faces own the diagonals, like the
 * renderer's pixel rule.
 */
export function bevelFaces(
  outer: Rect,
  width: number,
  color: string,
): { face: BevelFace; points: number[]; fill: string }[] {
  const { x, y, w, h } = outer;
  const right = x + w;
  const bottom = y + h;
  const d = width;
  const faces: [BevelFace, number[]][] = [
    ["left", [x, y, x + d, y + d, x + d, bottom - d, x, bottom]],
    ["right", [right, y, right, bottom, right - d, bottom - d, right - d, y + d]],
    ["top", [x, y, right, y, right - d, y + d, x + d, y + d]],
    ["bottom", [x, bottom, x + d, bottom - d, right - d, bottom - d, right, bottom]],
  ];
  return faces.map(([face, points]) => ({ face, points, fill: faceColor(color, face) }));
}
