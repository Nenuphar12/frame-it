// Selection chrome of the composition editor: outlines, transform handles and the rotation knob.
//
// The handles are plain Konva shapes drawn in document coordinates and un-scaled by the stage
// zoom, so they keep the same size on screen. They do not handle their own events: `EditorStage`
// owns one pointer pipeline (a gesture is accumulated and flushed once per animation frame, §8.5),
// and hit-tests the handles with `hit.ts` before it starts a drag.
import { Circle, Group, Line, Rect } from "react-konva";

import type { DocCaption, DocSlot } from "@/editor/core/document.ts";
import type { Rect as DocRect } from "@/editor/core/geometry.ts";
import { HANDLES, handleFraction, type Handle } from "./hit.ts";

/** Handle side and rotation-knob distance, in screen pixels (divided by the stage scale). */
export const HANDLE_PX = 9;
export const ROTATE_DISTANCE_PX = 26;
/** Extra tolerance around a handle when hit-testing the pointer. */
export const HANDLE_HIT_PX = 7;

interface SelectionOverlayProps {
  slots: DocSlot[];
  /** The slot that shows handles (the last one picked); `null` while several are selected. */
  primary: DocSlot | null;
  caption: DocCaption | null;
  captionBox: DocRect | null;
  scale: number;
  /** Handles are only drawn where a free-form transform is possible (`manual` placement). */
  transformable: boolean;
}

export function SelectionOverlay({
  slots,
  primary,
  caption,
  captionBox,
  scale,
  transformable,
}: SelectionOverlayProps) {
  const thin = 2 / scale;
  const handle = HANDLE_PX / scale;
  return (
    <>
      {slots.map((slot) => (
        <Group
          key={slot.id}
          x={slot.rect.x + slot.rect.w / 2}
          y={slot.rect.y + slot.rect.h / 2}
          rotation={slot.rotation}
        >
          <Rect
            x={-slot.rect.w / 2}
            y={-slot.rect.h / 2}
            width={slot.rect.w}
            height={slot.rect.h}
            stroke="#FFFFFF"
            strokeWidth={thin}
            opacity={slot === primary ? 0.95 : 0.55}
            dash={slot === primary ? undefined : [12 / scale, 8 / scale]}
          />
          {slot === primary && transformable && (
            <>
              <Line
                points={[0, -slot.rect.h / 2, 0, -slot.rect.h / 2 - ROTATE_DISTANCE_PX / scale]}
                stroke="#FFFFFF"
                strokeWidth={thin}
                opacity={0.8}
              />
              <Circle
                x={0}
                y={-slot.rect.h / 2 - ROTATE_DISTANCE_PX / scale}
                radius={handle / 1.6}
                fill="#FFFFFF"
                stroke="#111111"
                strokeWidth={thin / 2}
              />
              {HANDLES.map((name) => {
                const [fx, fy] = handleFraction(name as Handle);
                return (
                  <Rect
                    key={name}
                    x={-slot.rect.w / 2 + fx * slot.rect.w - handle / 2}
                    y={-slot.rect.h / 2 + fy * slot.rect.h - handle / 2}
                    width={handle}
                    height={handle}
                    fill="#FFFFFF"
                    stroke="#111111"
                    strokeWidth={thin / 2}
                  />
                );
              })}
            </>
          )}
        </Group>
      ))}
      {caption && captionBox && (
        <Rect
          x={captionBox.x}
          y={captionBox.y}
          width={captionBox.w}
          height={captionBox.h}
          rotation={caption.rotation}
          offsetX={0}
          offsetY={0}
          stroke="#5B8DEF"
          strokeWidth={thin}
          dash={[10 / scale, 6 / scale]}
        />
      )}
    </>
  );
}
