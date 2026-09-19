// The editor canvas: the artwork drawn at 1:1 document coordinates inside a zoomable stage.
//
// The document is the single source of truth; this component only maps pointer gestures onto the
// editor operations (crop pan/zoom, selection) and draws the overlays (selection, available area,
// snapping guides). The server render stays authoritative — see the loupe and the TV preview.
import type { KonvaEventObject } from "konva/lib/Node";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Group, Layer, Line, Rect, Stage } from "react-konva";

import type { EditorDocument } from "@/editor/core/document.ts";
import { availableArea } from "@/editor/core/placement.ts";
import { slotSource, type PhotoSizes } from "@/editor/operations";
import { CaptionNode } from "./CaptionNode.tsx";
import { SlotNode } from "./SlotNode.tsx";
import { cachedTile, tileKey, tintedTile } from "./texture.ts";

export interface StageView {
  scale: number;
  x: number;
  y: number;
}

interface EditorStageProps {
  doc: EditorDocument;
  sizes: PhotoSizes;
  tool: "select" | "crop";
  selectedSlotId: string | null;
  onSelect: (slotId: string | null) => void;
  /** Crop panning, in source pixels (already converted from screen movement). */
  onPanCrop: (dx: number, dy: number) => void;
  onZoomCrop: (factor: number) => void;
  /** Magenta guides (document coordinates) drawn while a value is snapped (§7.5). */
  guides?: { x?: number | null; y?: number | null };
  /** Called with document coordinates while the pointer moves (loupe). */
  onPointer?: (point: { x: number; y: number } | null) => void;
  /** Current zoom, so panels can express tolerances in screen pixels (snapping, §7.5). */
  onScaleChange?: (scale: number) => void;
}

const MIN_SCALE = 0.02;
const MAX_SCALE = 2;

export function EditorStage({
  doc,
  sizes,
  tool,
  selectedSlotId,
  onSelect,
  onPanCrop,
  onZoomCrop,
  guides,
  onPointer,
  onScaleChange,
}: EditorStageProps) {
  const container = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ width: 0, height: 0 });
  // `null` = "follow the container": the view is then derived from `fit()` on every render, so
  // resizing the window re-fits without an effect. Zooming or panning pins an explicit view.
  const [pinned, setPinned] = useState<StageView | null>(null);
  const [, redraw] = useState(0);
  const dragging = useRef<{ mode: "pan" | "crop"; x: number; y: number } | null>(null);
  const pending = useRef<{ mode: "pan" | "crop"; dx: number; dy: number } | null>(null);
  const frame = useRef<number | null>(null);
  const pointer = useRef<{ x: number; y: number } | null>(null);
  const pointerFrame = useRef<number | null>(null);
  const { width, height } = doc.canvas;

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const rect = entry?.contentRect;
      if (rect) setBox({ width: rect.width, height: rect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const fit = useCallback((): StageView => {
    const scale = Math.min(box.width / width, box.height / height) * 0.94;
    return {
      scale: scale || MIN_SCALE,
      x: (box.width - width * scale) / 2,
      y: (box.height - height * scale) / 2,
    };
  }, [box.width, box.height, width, height]);

  const view = pinned ?? (box.width > 0 ? fit() : null);
  const setView = setPinned;

  const mat = doc.mat;
  const key = mat.texture ? tileKey(mat.texture.id, mat.color, mat.texture.strength) : null;
  const texture = key ? cachedTile(key) : null;
  useEffect(() => {
    if (!mat.texture || texture) return;
    let active = true;
    // The tile is memoised in the module: a redraw is all the component needs once it is ready.
    void tintedTile(mat.texture.id, mat.color, mat.texture.strength).then(
      () => active && redraw((value) => value + 1),
    );
    return () => {
      active = false;
    };
  }, [key, mat.color, mat.texture, texture]);

  useEffect(() => {
    if (view) onScaleChange?.(view.scale);
  }, [view, onScaleChange]);

  useEffect(
    () => () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      if (pointerFrame.current !== null) cancelAnimationFrame(pointerFrame.current);
    },
    [],
  );

  const area = useMemo(() => availableArea(doc.margins, { w: width, h: height }), [
    doc.margins,
    width,
    height,
  ]);
  const selected = doc.slots.find((slot) => slot.id === selectedSlotId) ?? null;

  /**
   * Pointer position in document (TV) pixels, computed from the raw event rather than Konva's
   * `getPointerPosition()` — that one is null unless Konva has recorded the pointer for the event,
   * which silently left the loupe with no position.
   */
  const documentPoint = (event: KonvaEventObject<MouseEvent>): { x: number; y: number } | null => {
    const rect = container.current?.getBoundingClientRect();
    if (!rect || !view) return null;
    return {
      x: (event.evt.clientX - rect.left - view.x) / view.scale,
      y: (event.evt.clientY - rect.top - view.y) / view.scale,
    };
  };

  const onWheel = (event: KonvaEventObject<WheelEvent>) => {
    event.evt.preventDefault();
    if (!view) return;
    if (tool === "crop" && selected) {
      onZoomCrop(event.evt.deltaY > 0 ? 1.06 : 1 / 1.06);
      return;
    }
    const stage = event.target.getStage();
    const pointer = stage?.getPointerPosition();
    if (!pointer) return;
    const factor = event.evt.deltaY > 0 ? 1 / 1.1 : 1.1;
    const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, view.scale * factor));
    const ratio = scale / view.scale;
    setView({
      scale,
      x: pointer.x - (pointer.x - view.x) * ratio,
      y: pointer.y - (pointer.y - view.y) * ratio,
    });
  };

  const onMouseDown = (event: KonvaEventObject<MouseEvent>) => {
    const point = documentPoint(event);
    if (!point) return;
    const middle = event.evt.button === 1 || event.evt.shiftKey;
    const hit = doc.slots.findLast(
      (slot) =>
        point.x >= slot.rect.x &&
        point.x <= slot.rect.x + slot.rect.w &&
        point.y >= slot.rect.y &&
        point.y <= slot.rect.y + slot.rect.h,
    );
    if (!middle && tool === "select") onSelect(hit?.id ?? null);
    const cropping = tool === "crop" && !middle && selected !== null;
    dragging.current = { mode: cropping ? "crop" : "pan", x: event.evt.clientX, y: event.evt.clientY };
  };

  // Pointer moves are accumulated and flushed once per animation frame: a mouse can fire far more
  // events than the canvas can redraw, and one React render per event is what kills the frame rate.
  const flush = useCallback(() => {
    frame.current = null;
    const move = pending.current;
    pending.current = null;
    if (!move) return;
    if (move.mode === "pan") {
      // Panning pins the view: `fit()` is the starting point while it still follows the container.
      setPinned((current) => {
        const base = current ?? fit();
        return { ...base, x: base.x + move.dx, y: base.y + move.dy };
      });
      return;
    }
    onPanCrop(move.dx, move.dy);
  }, [fit, onPanCrop]);

  const schedule = (mode: "pan" | "crop", dx: number, dy: number) => {
    const current = pending.current;
    pending.current =
      current && current.mode === mode
        ? { mode, dx: current.dx + dx, dy: current.dy + dy }
        : { mode, dx, dy };
    frame.current ??= requestAnimationFrame(flush);
  };

  const onMouseMove = (event: KonvaEventObject<MouseEvent>) => {
    // Reported at most once per frame: the loupe re-renders the editor on every point it gets.
    if (onPointer) {
      pointer.current = documentPoint(event);
      pointerFrame.current ??= requestAnimationFrame(() => {
        pointerFrame.current = null;
        onPointer(pointer.current);
      });
    }
    const drag = dragging.current;
    if (!drag || !view) return;
    const dx = event.evt.clientX - drag.x;
    const dy = event.evt.clientY - drag.y;
    if (dx === 0 && dy === 0) return;
    dragging.current = { ...drag, x: event.evt.clientX, y: event.evt.clientY };
    if (drag.mode === "pan") {
      schedule("pan", dx, dy);
      return;
    }
    if (!selected) return;
    // Dragging moves the photo, so the crop moves the opposite way, in source pixels.
    const source = slotSource(selected, sizes);
    if (!source) return;
    const perPixel = selected.source.crop.w / Math.max(1, selected.rect.w) / view.scale;
    schedule("crop", -dx * perPixel, -dy * perPixel);
  };

  const endDrag = () => {
    dragging.current = null;
    if (frame.current !== null) {
      cancelAnimationFrame(frame.current);
      frame.current = null;
      flush();
    }
  };

  return (
    <div
      ref={container}
      className="relative h-full w-full overflow-hidden bg-[#111]"
      data-tool={tool}
    >
      {view && box.width > 0 && (
        <Stage
          width={box.width}
          height={box.height}
          scaleX={view.scale}
          scaleY={view.scale}
          x={view.x}
          y={view.y}
          onWheel={onWheel}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={endDrag}
          onMouseLeave={() => {
            endDrag();
            onPointer?.(null);
          }}
          style={{ cursor: tool === "crop" ? "grab" : "default" }}
        >
          <Layer listening={false}>
            <Rect x={0} y={0} width={width} height={height} fill={doc.mat.color} />
            {texture && (
              <Rect
                x={0}
                y={0}
                width={width}
                height={height}
                fillPatternImage={texture as unknown as HTMLImageElement}
                fillPatternRepeat="repeat"
              />
            )}
            {doc.slots.map((slot) => (
              <SlotNode
                key={slot.id}
                slot={slot}
                source={slotSource(slot, sizes)}
                dimmed={tool === "crop" && selectedSlotId !== null && slot.id !== selectedSlotId}
              />
            ))}
            {doc.captions.map((caption) => (
              <CaptionNode key={caption.id} caption={caption} />
            ))}
          </Layer>
          <Layer listening={false}>
            {doc.placement === "fit_in_mat" && (
              <Rect
                x={area.x}
                y={area.y}
                width={area.w}
                height={area.h}
                stroke="#5B8DEF"
                strokeWidth={2 / view.scale}
                dash={[10 / view.scale, 10 / view.scale]}
                opacity={0.7}
              />
            )}
            {selected && (
              <Group
                x={selected.rect.x + selected.rect.w / 2}
                y={selected.rect.y + selected.rect.h / 2}
                rotation={selected.rotation}
              >
                <Rect
                  x={-selected.rect.w / 2}
                  y={-selected.rect.h / 2}
                  width={selected.rect.w}
                  height={selected.rect.h}
                  stroke="#FFFFFF"
                  strokeWidth={2 / view.scale}
                  opacity={0.9}
                />
              </Group>
            )}
            {guides?.x != null && (
              <Line
                points={[guides.x, 0, guides.x, height]}
                stroke="#FF2D9B"
                strokeWidth={2 / view.scale}
              />
            )}
            {guides?.y != null && (
              <Line
                points={[0, guides.y, width, guides.y]}
                stroke="#FF2D9B"
                strokeWidth={2 / view.scale}
              />
            )}
          </Layer>
        </Stage>
      )}
      <StageControls view={view} onFit={() => setView(null)} onZoom={(factor) =>
        setView((current) => {
          if (!current) return current;
          const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, current.scale * factor));
          const ratio = scale / current.scale;
          return {
            scale,
            x: box.width / 2 - (box.width / 2 - current.x) * ratio,
            y: box.height / 2 - (box.height / 2 - current.y) * ratio,
          };
        })
      } />
    </div>
  );
}

function StageControls({
  view,
  onFit,
  onZoom,
}: {
  view: StageView | null;
  onFit: () => void;
  onZoom: (factor: number) => void;
}) {
  return (
    <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-md border border-border bg-panel/90 px-1.5 py-1 text-xs backdrop-blur">
      <button type="button" className="px-1.5 py-0.5 hover:text-accent" onClick={() => onZoom(1 / 1.2)}>
        −
      </button>
      <span className="w-12 text-center tabular-nums text-muted">
        {view ? Math.round(view.scale * 100) : 0}%
      </span>
      <button type="button" className="px-1.5 py-0.5 hover:text-accent" onClick={() => onZoom(1.2)}>
        +
      </button>
      <button type="button" className="px-1.5 py-0.5 text-muted hover:text-accent" onClick={onFit}>
        Fit
      </button>
    </div>
  );
}
