// Template cards draw themselves: no stored thumbnails, no server render.
//
// A layout is solved by the real solver at its own parameters (the same trick as the Simple
// panel's picker, docs/simple-editor.md §6.3), so a card can never drift from what the layout
// actually does. A style is a *look*, so its card is a mat with one framed photo rect on it.
import { useId } from "react";

import { solve, type Composition, type Recipe } from "@/editor/core/composition.ts";
import type { Shadow } from "@/editor/core/document.ts";
import { CANVAS, type Rect } from "@/editor/core/geometry.ts";
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

/**
 * The shadow of a frame style, drawn the way the renderer draws it (`rendering-spec.md` §8.1).
 *
 * A hard rect peeking out from behind the photo showed nothing — a 6 px offset under a 12 px band
 * is invisible, and inner and drop looked identical (remarks.md #2). Both are filters here: the
 * blur is a real Gaussian at `σ = blur / 2`, and the recessed one is the renderer's algorithm —
 * the complement of the layer, offset, blurred, clipped back inside it.
 */
function ShadowFilter({ id, shadow, rect }: { id: string; shadow: Shadow; rect: Rect }) {
  const sigma = shadow.blur / 2;
  const pad = 3 * sigma + Math.abs(shadow.offset_x) + Math.abs(shadow.offset_y) + 8;
  const region = {
    x: rect.x - pad,
    y: rect.y - pad,
    width: rect.w + 2 * pad,
    height: rect.h + 2 * pad,
  };
  if (shadow.type === "drop") {
    return (
      <filter id={id} filterUnits="userSpaceOnUse" {...region}>
        <feDropShadow
          dx={shadow.offset_x}
          dy={shadow.offset_y}
          stdDeviation={sigma}
          floodColor={shadow.color}
          floodOpacity={shadow.opacity}
        />
      </filter>
    );
  }
  return (
    <filter id={id} filterUnits="userSpaceOnUse" {...region}>
      {/* 255 outside the layer, 0 inside: the mask the renderer blurs. */}
      <feComponentTransfer in="SourceAlpha" result="outside">
        <feFuncA type="table" tableValues="1 0" />
      </feComponentTransfer>
      <feOffset in="outside" dx={shadow.offset_x} dy={shadow.offset_y} result="shifted" />
      <feGaussianBlur in="shifted" stdDeviation={sigma} result="blurred" />
      {/* Back inside the layer, coloured, and over it. */}
      <feComposite in="blurred" in2="SourceAlpha" operator="in" result="ring" />
      <feFlood floodColor={shadow.color} floodOpacity={shadow.opacity} result="ink" />
      <feComposite in="ink" in2="ring" operator="in" result="shade" />
      <feMerge>
        <feMergeNode in="SourceGraphic" />
        <feMergeNode in="shade" />
      </feMerge>
    </filter>
  );
}

/** A style on a sample photo: the mat, the band around the photo, its shadow and the caption. */
export function StylePreview({ style }: { style: StyleDocumentApi }) {
  // Filter and gradient ids are document-wide: the Templates page draws a card per style.
  const uid = useId().replace(/:/g, "");
  const mat = style.mat?.color ?? "#F2EFE8";
  const band = style.slot_defaults?.bands?.[0];
  const shadow = style.slot_defaults?.shadow ?? null;
  const margins = style.margins ?? { top: 280, right: 300, bottom: 320, left: 300 };
  const x = margins.left;
  const y = margins.top;
  const w = CANVAS.w - margins.left - margins.right;
  const h = CANVAS.h - margins.top - margins.bottom;
  // The shadow is cast by the *layer* — photo plus bands — exactly as in the renderer.
  const width = band?.width ?? 0;
  const layer = { x: x - width, y: y - width, w: w + 2 * width, h: h + 2 * width };
  return (
    <svg viewBox={`0 0 ${CANVAS.w} ${CANVAS.h}`} className="h-full w-full" role="presentation">
      <defs>
        <linearGradient id={`${uid}-photo`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#6f7f8f" />
          <stop offset="100%" stopColor="#c2b8a8" />
        </linearGradient>
        {shadow && <ShadowFilter id={`${uid}-shadow`} shadow={shadow} rect={layer} />}
      </defs>
      <rect x={0} y={0} width={CANVAS.w} height={CANVAS.h} fill={mat} />
      <g filter={shadow ? `url(#${uid}-shadow)` : undefined}>
        {band && (
          <rect x={layer.x} y={layer.y} width={layer.w} height={layer.h} fill={band.color} />
        )}
        <rect x={x} y={y} width={w} height={h} fill={`url(#${uid}-photo)`} />
      </g>
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
