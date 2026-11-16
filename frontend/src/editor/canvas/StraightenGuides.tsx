// The grid drawn over a photo while it is being straightened (`editor/guides.ts`).
import { Group, Line } from "react-konva";

import type { DocSlot } from "@/editor/core/document.ts";

/** Grid cells across the slot's short side: fine enough to follow a horizon, not a mesh. */
const CELLS_ACROSS = 6;

/**
 * Light horizontal and vertical lines over the slot — square cells, one line through the centre
 * either way — in the slot's own frame, so they stay true to the frame the photo turns in. Each
 * line is a light stroke over a soft dark one: readable on a bright sky and on a dark sea alike.
 */
export function StraightenGuides({ slot, scale }: { slot: DocSlot; scale: number }) {
  const { rect } = slot;
  const step = Math.min(rect.w, rect.h) / CELLS_ACROSS;
  const xs: number[] = [];
  const ys: number[] = [];
  for (let x = step; x < rect.w / 2; x += step) xs.push(x, -x);
  for (let y = step; y < rect.h / 2; y += step) ys.push(y, -y);
  const lines = [
    ...[0, ...xs].map((x) => [x, -rect.h / 2, x, rect.h / 2]),
    ...[0, ...ys].map((y) => [-rect.w / 2, y, rect.w / 2, y]),
  ];
  return (
    <Group
      x={rect.x + rect.w / 2}
      y={rect.y + rect.h / 2}
      rotation={slot.rotation}
      clipX={-rect.w / 2}
      clipY={-rect.h / 2}
      clipWidth={rect.w}
      clipHeight={rect.h}
      listening={false}
    >
      {lines.map((points, index) => (
        <Line
          key={`d${index}`}
          points={points}
          stroke="#000000"
          opacity={0.25}
          strokeWidth={3 / scale}
        />
      ))}
      {lines.map((points, index) => (
        <Line
          key={`l${index}`}
          points={points}
          stroke="#FFFFFF"
          opacity={0.6}
          strokeWidth={1 / scale}
        />
      ))}
    </Group>
  );
}
