// One slot on the canvas: drop shadow, bands, the cropped photo and the inner shadow.
//
// Parity with the server renderer (docs/rendering-spec.md §8.2, docs/research/render-parity.md):
// Konva already scales `shadowBlur`/`shadowOffset` by the absolute scale and the pixel ratio, so
// drop shadows take document units unchanged. The inner shadow has no canvas equivalent and is
// drawn as a clipped ring — see `InnerShadow` below.
import { Group, Image as KonvaImage, Rect, Shape } from "react-konva";

import { bandWidth, type DocSlot, type Shadow } from "@/editor/core/document.ts";
import type { Size } from "@/editor/core/geometry.ts";
import { useOrientedImage } from "./useOrientedImage.ts";

interface SlotNodeProps {
  slot: DocSlot;
  /** Oriented source size the crop is expressed in (photo size after EXIF and `orient`). */
  source: Size | null;
  /** Dim the slots that are not being edited (crop mode). */
  dimmed?: boolean;
}

/**
 * How far past the layer the shadow-casting ring extends. Big enough that the ring's own outer
 * edge casts nothing into the visible area (3σ of the blur plus the offset), and no bigger: the
 * browser allocates a surface for the shape *and* its shadow, so a ring drawn far away (the
 * trick S3 used, 20 000 px) makes Skia allocate a huge surface and freezes the tab.
 */
const ringPad = (shadow: Shadow) =>
  shadow.blur * 3 + Math.abs(shadow.offset_x) + Math.abs(shadow.offset_y) + 8;

export function SlotNode({ slot, source, dimmed = false }: SlotNodeProps) {
  const proxy = useOrientedImage(slot.photo_id, slot.source.orient);
  const { rect, shadow } = slot;
  const band = bandWidth(slot);
  const layer = {
    x: -rect.w / 2 - band,
    y: -rect.h / 2 - band,
    w: rect.w + 2 * band,
    h: rect.h + 2 * band,
  };
  // The proxy is the oriented photo scaled down: crops convert with a single factor.
  const toProxy = proxy && source ? proxy.width / source.w : 1;

  return (
    <Group
      x={rect.x + rect.w / 2}
      y={rect.y + rect.h / 2}
      rotation={slot.rotation}
      opacity={dimmed ? 0.35 : 1}
      listening={false}
    >
      {shadow?.type === "drop" && (
        <Rect
          x={layer.x}
          y={layer.y}
          width={layer.w}
          height={layer.h}
          fill={shadow.color}
          shadowColor={shadow.color}
          shadowBlur={shadow.blur}
          shadowOffsetX={shadow.offset_x}
          shadowOffsetY={shadow.offset_y}
          shadowOpacity={shadow.opacity}
        />
      )}
      {slot.bands.map((_, index) => {
        // Outermost first: each band is a filled rect that the inner bands and the photo cover.
        const from = slot.bands.length - 1 - index;
        const grow = slot.bands.slice(0, from + 1).reduce((total, b) => total + b.width, 0);
        return (
          <Rect
            key={from}
            x={-rect.w / 2 - grow}
            y={-rect.h / 2 - grow}
            width={rect.w + 2 * grow}
            height={rect.h + 2 * grow}
            fill={slot.bands[from]?.color}
          />
        );
      })}
      {proxy ? (
        <KonvaImage
          image={proxy.image}
          x={-rect.w / 2}
          y={-rect.h / 2}
          width={rect.w}
          height={rect.h}
          crop={{
            x: slot.source.crop.x * toProxy,
            y: slot.source.crop.y * toProxy,
            width: slot.source.crop.w * toProxy,
            height: slot.source.crop.h * toProxy,
          }}
        />
      ) : (
        <Rect
          x={-rect.w / 2}
          y={-rect.h / 2}
          width={rect.w}
          height={rect.h}
          fill="#1B1B1B"
          stroke="#555555"
          strokeWidth={4}
          dash={[24, 24]}
        />
      )}
      {shadow?.type === "inner" && <InnerShadow shadow={shadow} {...layer} />}
    </Group>
  );
}

interface InnerShadowProps {
  shadow: Shadow;
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Recessed look: a ring around the layer casts the shadow, and the layer rect clips it, so only
 * the part falling *inside* the photo shows — the ring's own ink is clipped away.
 *
 * Canvas shadow offsets ignore the current transform (S3), so the offset is scaled and rotated
 * into device space by hand; the server applies it in the slot's frame, before rotation.
 */
function InnerShadow({ shadow, x, y, w, h }: InnerShadowProps) {
  return (
    <Shape
      listening={false}
      perfectDrawEnabled={false}
      sceneFunc={(context, shape) => {
        const native = (context as unknown as { _context: CanvasRenderingContext2D })._context;
        const scale = shape.getAbsoluteScale().x * context.canvas.getPixelRatio();
        const radians = (shape.getAbsoluteRotation() * Math.PI) / 180;
        const cos = Math.cos(radians);
        const sin = Math.sin(radians);
        const offsetX = shadow.offset_x * scale;
        const offsetY = shadow.offset_y * scale;
        const pad = ringPad(shadow);

        native.save();
        native.beginPath();
        native.rect(x, y, w, h);
        native.clip();
        native.globalAlpha = shadow.opacity;
        native.shadowColor = shadow.color;
        native.shadowBlur = shadow.blur * scale;
        native.shadowOffsetX = offsetX * cos - offsetY * sin;
        native.shadowOffsetY = offsetX * sin + offsetY * cos;
        native.fillStyle = shadow.color;
        native.beginPath();
        native.rect(x - pad, y - pad, w + 2 * pad, h + 2 * pad);
        native.rect(x, y, w, h);
        native.fill("evenodd");
        native.restore();
      }}
    />
  );
}
