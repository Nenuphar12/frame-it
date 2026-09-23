// Template cards draw themselves: no stored thumbnails, no server render.
//
// A layout is solved by the real solver at its own parameters (the same trick as the Simple
// panel's picker, docs/simple-editor.md §6.3), so a card can never drift from what the layout
// actually does. A style is a *look*, so its card is a mat with one framed photo rect on it.
import { solve, type Composition, type Recipe } from "@/editor/core/composition.ts";
import { CANVAS } from "@/editor/core/geometry.ts";
import type { LayoutDocumentApi, StyleDocumentApi } from "@/api/client";

const PHOTO = "#8c8c8c";

/** The block a layout describes, with a placeholder caption when it reserves a band. */
function block(layout: LayoutDocumentApi): Composition {
  return {
    recipe: layout.recipe,
    balance: layout.balance ?? null,
    outer: { x: layout.outer?.x ?? 120, y: layout.outer?.y ?? 120 },
    gutter: { x: layout.gutter?.x ?? 80, y: layout.gutter?.y ?? 80 },
    format: layout.format ?? "fill",
    cell_formats: [...(layout.cell_formats ?? [])],
    border: layout.border ? { ...layout.border } : null,
    caption: { text: "", place: layout.caption_place ?? "none" },
    detached: false,
  };
}

export function LayoutPreview({
  layout,
  recipe,
  mat = "#1b1b1b",
}: {
  layout: LayoutDocumentApi;
  recipe: Recipe | undefined;
  mat?: string;
}) {
  if (!recipe) return <div className="h-full w-full bg-panel-2" />;
  const composition = block(layout);
  const cells = solve(recipe, composition, Array(recipe.count).fill(null));
  const border = composition.border;
  return (
    <svg viewBox={`0 0 ${CANVAS.w} ${CANVAS.h}`} className="h-full w-full" role="presentation">
      <rect x={0} y={0} width={CANVAS.w} height={CANVAS.h} fill={mat} />
      {cells.map((cell) => (
        <g key={cell.id}>
          {border && (
            <rect
              x={cell.rect.x - border.width}
              y={cell.rect.y - border.width}
              width={cell.rect.w + 2 * border.width}
              height={cell.rect.h + 2 * border.width}
              fill={border.color}
            />
          )}
          <rect
            x={cell.rect.x}
            y={cell.rect.y}
            width={cell.rect.w}
            height={cell.rect.h}
            fill={PHOTO}
          />
        </g>
      ))}
      {composition.caption.place !== "none" && (
        <rect
          x={CANVAS.w * 0.35}
          y={
            composition.caption.place === "above"
              ? composition.outer.y
              : CANVAS.h - composition.outer.y - 90
          }
          width={CANVAS.w * 0.3}
          height={60}
          rx={30}
          fill={PHOTO}
          opacity={0.6}
        />
      )}
    </svg>
  );
}

/** A style on a sample photo: the mat, the band around the photo and the caption's colour. */
export function StylePreview({ style }: { style: StyleDocumentApi }) {
  const mat = style.mat?.color ?? "#F2EFE8";
  const band = style.slot_defaults?.bands?.[0];
  const shadow = style.slot_defaults?.shadow;
  const margins = style.margins ?? { top: 280, right: 300, bottom: 320, left: 300 };
  const x = margins.left;
  const y = margins.top;
  const w = CANVAS.w - margins.left - margins.right;
  const h = CANVAS.h - margins.top - margins.bottom;
  return (
    <svg viewBox={`0 0 ${CANVAS.w} ${CANVAS.h}`} className="h-full w-full" role="presentation">
      <defs>
        <linearGradient id="tf-style-photo" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#6f7f8f" />
          <stop offset="100%" stopColor="#c2b8a8" />
        </linearGradient>
      </defs>
      <rect x={0} y={0} width={CANVAS.w} height={CANVAS.h} fill={mat} />
      {shadow && (
        <rect
          x={x + (shadow.offset_x ?? 0)}
          y={y + (shadow.offset_y ?? 0) + 10}
          width={w}
          height={h}
          fill={shadow.color ?? "#000000"}
          opacity={(shadow.opacity ?? 0.3) * 0.6}
        />
      )}
      {band && (
        <rect
          x={x - band.width}
          y={y - band.width}
          width={w + 2 * band.width}
          height={h + 2 * band.width}
          fill={band.color}
        />
      )}
      <rect x={x} y={y} width={w} height={h} fill="url(#tf-style-photo)" />
      <rect
        x={CANVAS.w * 0.38}
        y={CANVAS.h - margins.bottom + Math.min(90, margins.bottom / 3)}
        width={CANVAS.w * 0.24}
        height={54}
        rx={27}
        fill={style.caption_defaults?.color ?? "#3A3A3A"}
        opacity={0.55}
      />
    </svg>
  );
}
