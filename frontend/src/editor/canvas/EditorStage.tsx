// The editor canvas: the artwork drawn at 1:1 document coordinates inside a zoomable stage.
//
// The document is the single source of truth; this component only maps pointer gestures onto the
// editor operations (crop pan/zoom, slot move/resize/rotate, caption move, selection) and draws
// the overlays (selection, handles, available area, snapping guides). The server render stays
// authoritative — see the loupe and the TV preview.
//
// One pointer pipeline, one flush per animation frame: a mouse fires far more events than the
// canvas can redraw, and one React render per event freezes the tab (§8.5 and the Gotchas).
import type { KonvaEventObject } from "konva/lib/Node";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Layer, Line, Rect, Stage } from "react-konva";

import type { Anchor } from "@/editor/core/constraints.ts";
import type { DocCaption, EditorDocument } from "@/editor/core/document.ts";
import type { Rect as DocRect, Size } from "@/editor/core/geometry.ts";
import { availableArea } from "@/editor/core/placement.ts";
import { snapRect, TOLERANCE_PX } from "@/editor/core/snapping.ts";
import { slotSource, type PhotoSizes } from "@/editor/operations";
import { CaptionNode } from "./CaptionNode.tsx";
import { captionBox } from "./fonts.ts";
import {
  angleTo,
  handleAnchor,
  handlePoint,
  hitsRect,
  HANDLES,
  resizedSize,
  slotAt,
  snapAngle,
  type Handle,
  type Point,
} from "./hit.ts";
import { HANDLE_HIT_PX, HANDLE_PX, ROTATE_DISTANCE_PX, SelectionOverlay } from "./SelectionOverlay";
import { SlotNode } from "./SlotNode.tsx";
import { cachedTile, tileKey, tintedTile } from "./texture.ts";

export interface StageView {
  scale: number;
  x: number;
  y: number;
}

export type SelectMode = "replace" | "toggle";

interface EditorStageProps {
  doc: EditorDocument;
  sizes: PhotoSizes;
  tool: "select" | "crop";
  selectedSlotIds: string[];
  selectedCaptionId: string | null;
  onSelectSlot: (slotId: string | null, mode: SelectMode) => void;
  onSelectCaption: (captionId: string | null) => void;
  /** Crop panning, in source pixels (already converted from screen movement). */
  onPanCrop: (dx: number, dy: number) => void;
  onZoomCrop: (factor: number) => void;
  /** Free-form transforms of the selection (`manual` placement only). */
  onMoveSlots: (dx: number, dy: number) => void;
  onResizeSlot: (size: Size, anchor: Anchor) => void;
  onRotateSlot: (degrees: number) => void;
  onMoveCaption: (dx: number, dy: number) => void;
  onEditCaption: (captionId: string, text: string) => void;
  /** A photo dragged from the picker and dropped on the canvas (on a slot, or on the mat). */
  onDropPhoto?: (photoId: string, onSlotId: string | null, at: Point) => void;
  /** Magenta guides (document coordinates) drawn while a value is snapped (§7.5). */
  guides?: { x?: number | null; y?: number | null };
  /** Called with document coordinates while the pointer moves (loupe). */
  onPointer?: (point: { x: number; y: number } | null) => void;
  /** Current zoom, so panels can express tolerances in screen pixels (snapping, §7.5). */
  onScaleChange?: (scale: number) => void;
}

const MIN_SCALE = 0.02;
const MAX_SCALE = 2;
const ROTATION_STEP = 15;

/** What the pointer is doing between mousedown and mouseup. */
type Gesture =
  | { mode: "pan" }
  | { mode: "crop" }
  | { mode: "slot"; rect: DocRect; id: string; collapse: boolean; moved: boolean }
  | { mode: "resize"; handle: Handle; rect: DocRect; rotation: number }
  | { mode: "rotate"; rect: DocRect; offset: number }
  | { mode: "caption"; x: number; y: number };

export function EditorStage({
  doc,
  sizes,
  tool,
  selectedSlotIds,
  selectedCaptionId,
  onSelectSlot,
  onSelectCaption,
  onPanCrop,
  onZoomCrop,
  onMoveSlots,
  onResizeSlot,
  onRotateSlot,
  onMoveCaption,
  onEditCaption,
  onDropPhoto,
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
  const [editing, setEditing] = useState<{ id: string; value: string } | null>(null);
  /** Only used for the cursor: the gesture itself lives in a ref (no render per event). */
  const [moving, setMoving] = useState(false);
  const [snapGuides, setSnapGuides] = useState<{ x: number | null; y: number | null }>({
    x: null,
    y: null,
  });
  const gesture = useRef<Gesture | null>(null);
  const origin = useRef<Point>({ x: 0, y: 0 });
  const latest = useRef<{ x: number; y: number; alt: boolean; shift: boolean } | null>(null);
  const frame = useRef<number | null>(null);
  const cropDelta = useRef<{ dx: number; dy: number } | null>(null);
  const pointer = useRef<{ x: number; y: number } | null>(null);
  const pointerFrame = useRef<number | null>(null);
  const { width, height } = doc.canvas;

  // The flush runs one frame after the event, so it must see the document and the view as they
  // are *now*. They are mirrored into refs in a layout effect: writing a ref during render is
  // forbidden (React Compiler lint), and a passive effect would land after the next frame.
  const live = useRef(doc);
  const viewRef = useRef<StageView | null>(null);

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

  useLayoutEffect(() => {
    live.current = doc;
    viewRef.current = view;
  });

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
  const selectedSlots = doc.slots.filter((slot) => selectedSlotIds.includes(slot.id));
  const primaryId = selectedSlotIds[selectedSlotIds.length - 1] ?? null;
  const primary = doc.slots.find((slot) => slot.id === primaryId) ?? null;
  const caption = doc.captions.find((item) => item.id === selectedCaptionId) ?? null;
  const transformable = doc.placement === "manual" && tool === "select";

  const boxes = useMemo(
    () => new Map(doc.captions.map((item) => [item.id, captionBox(item)] as const)),
    [doc.captions],
  );

  /**
   * Pointer position in document (TV) pixels, computed from the raw event rather than Konva's
   * `getPointerPosition()` — that one is null unless Konva has recorded the pointer for the event,
   * which silently left the loupe with no position.
   */
  const documentPoint = useCallback((clientX: number, clientY: number): Point | null => {
    const rect = container.current?.getBoundingClientRect();
    const current = viewRef.current;
    if (!rect || !current) return null;
    return {
      x: (clientX - rect.left - current.x) / current.scale,
      y: (clientY - rect.top - current.y) / current.scale,
    };
  }, []);

  const captionAt = useCallback(
    (point: Point): DocCaption | null => {
      for (let index = doc.captions.length - 1; index >= 0; index--) {
        const item = doc.captions[index]!;
        const rect = boxes.get(item.id);
        if (rect && hitsRect(point, rect, item.rotation, 4, { x: item.x, y: item.y })) return item;
      }
      return null;
    },
    [doc.captions, boxes],
  );

  /** Handle of the primary slot under the pointer (hit box in screen pixels). */
  const handleAt = useCallback(
    (point: Point): Handle | "rotate" | null => {
      if (!primary || !transformable || !view) return null;
      const reach = (HANDLE_PX / 2 + HANDLE_HIT_PX) / view.scale;
      const knob = handlePoint(primary.rect, primary.rotation, "n");
      const radians = (primary.rotation * Math.PI) / 180;
      const rotateKnob = {
        x: knob.x + (ROTATE_DISTANCE_PX / view.scale) * Math.sin(radians),
        y: knob.y - (ROTATE_DISTANCE_PX / view.scale) * Math.cos(radians),
      };
      if (Math.hypot(point.x - rotateKnob.x, point.y - rotateKnob.y) <= reach) return "rotate";
      for (const name of HANDLES) {
        const spot = handlePoint(primary.rect, primary.rotation, name);
        if (Math.hypot(point.x - spot.x, point.y - spot.y) <= reach) return name;
      }
      return null;
    },
    [primary, transformable, view],
  );

  // ---- gesture flush ---------------------------------------------------------------------------
  const flush = useCallback(() => {
    frame.current = null;
    const current = gesture.current;
    const move = latest.current;
    const scale = viewRef.current?.scale ?? 1;
    if (current?.mode === "crop" || !current) {
      const crop = cropDelta.current;
      cropDelta.current = null;
      if (crop) onPanCrop(crop.dx, crop.dy);
      return;
    }
    if (!move) return;
    const delta = { x: (move.x - origin.current.x) / scale, y: (move.y - origin.current.y) / scale };
    if (current.mode === "pan") {
      // Panning pins the view: `fit()` is the starting point while it still follows the container.
      origin.current = { x: move.x, y: move.y };
      setPinned((pinnedView) => {
        const base = pinnedView ?? fit();
        return { ...base, x: base.x + delta.x * scale, y: base.y + delta.y * scale };
      });
      return;
    }
    if (current.mode === "slot") {
      const slot = live.current.slots.find((item) => item.id === primaryId);
      if (!slot) return;
      current.moved = true;
      let target = {
        ...current.rect,
        x: Math.round(current.rect.x + delta.x),
        y: Math.round(current.rect.y + delta.y),
      };
      if (!move.alt) {
        const others = live.current.slots
          .filter((item) => !selectedSlotIds.includes(item.id))
          .map((item) => item.rect);
        const snapped = snapRect(target, others, TOLERANCE_PX / Math.max(scale, 0.001), {
          w: width,
          h: height,
        });
        target = snapped.rect;
        setSnapGuides(snapped.guides);
      } else {
        setSnapGuides({ x: null, y: null });
      }
      onMoveSlots(target.x - slot.rect.x, target.y - slot.rect.y);
      return;
    }
    if (current.mode === "resize") {
      onResizeSlot(
        resizedSize(current.rect, current.rotation, current.handle, delta),
        handleAnchor(current.handle),
      );
      return;
    }
    if (current.mode === "rotate") {
      const point = documentPoint(move.x, move.y);
      if (!point) return;
      const angle = angleTo(current.rect, point) - current.offset;
      onRotateSlot(snapAngle(angle, move.shift ? ROTATION_STEP : null));
      return;
    }
    const item = live.current.captions.find((entry) => entry.id === selectedCaptionId);
    if (!item) return;
    onMoveCaption(
      Math.round(current.x + delta.x) - item.x,
      Math.round(current.y + delta.y) - item.y,
    );
  }, [
    documentPoint,
    fit,
    height,
    onMoveCaption,
    onMoveSlots,
    onPanCrop,
    onResizeSlot,
    onRotateSlot,
    primaryId,
    selectedCaptionId,
    selectedSlotIds,
    width,
  ]);

  const schedule = () => {
    frame.current ??= requestAnimationFrame(flush);
  };

  // ---- pointer ---------------------------------------------------------------------------------
  const onWheel = (event: KonvaEventObject<WheelEvent>) => {
    event.evt.preventDefault();
    if (!view) return;
    if (tool === "crop" && primary) {
      onZoomCrop(event.evt.deltaY > 0 ? 1.06 : 1 / 1.06);
      return;
    }
    const stage = event.target.getStage();
    const position = stage?.getPointerPosition();
    if (!position) return;
    const factor = event.evt.deltaY > 0 ? 1 / 1.1 : 1.1;
    const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, view.scale * factor));
    const ratio = scale / view.scale;
    setView({
      scale,
      x: position.x - (position.x - view.x) * ratio,
      y: position.y - (position.y - view.y) * ratio,
    });
  };

  const onMouseDown = (event: KonvaEventObject<MouseEvent>) => {
    const point = documentPoint(event.evt.clientX, event.evt.clientY);
    if (!point || !view) return;
    origin.current = { x: event.evt.clientX, y: event.evt.clientY };
    latest.current = null;
    if (event.evt.button === 1) {
      gesture.current = { mode: "pan" };
      return;
    }
    const handle = handleAt(point);
    if (handle && primary) {
      gesture.current =
        handle === "rotate"
          ? { mode: "rotate", rect: primary.rect, offset: angleTo(primary.rect, point) - primary.rotation }
          : { mode: "resize", handle, rect: primary.rect, rotation: primary.rotation };
      return;
    }
    if (tool === "crop") {
      gesture.current = primary ? { mode: "crop" } : { mode: "pan" };
      return;
    }
    const hitCaption = captionAt(point);
    if (hitCaption) {
      onSelectCaption(hitCaption.id);
      gesture.current = { mode: "caption", x: hitCaption.x, y: hitCaption.y };
      return;
    }
    const hit = slotAt(doc.slots, point);
    const additive = event.evt.shiftKey || event.evt.ctrlKey || event.evt.metaKey;
    if (!hit) {
      if (!additive) onSelectSlot(null, "replace");
      gesture.current = { mode: "pan" };
      return;
    }
    const alreadySelected = selectedSlotIds.includes(hit.id);
    if (additive) onSelectSlot(hit.id, "toggle");
    else if (!alreadySelected) onSelectSlot(hit.id, "replace");
    const target = additive || alreadySelected ? (primary ?? hit) : hit;
    if (doc.placement === "manual") {
      gesture.current = {
        mode: "slot",
        rect: target.rect,
        id: hit.id,
        // Clicking a slot of a multi-selection keeps it (so the group can be dragged) and only
        // collapses the selection onto that slot if the pointer never moved — a plain click.
        collapse: !additive && alreadySelected && selectedSlotIds.length > 1,
        moved: false,
      };
      setMoving(true);
    } else {
      gesture.current = { mode: "pan" };
    }
  };

  const onMouseMove = (event: KonvaEventObject<MouseEvent>) => {
    // Reported at most once per frame: the loupe re-renders the editor on every point it gets.
    if (onPointer) {
      pointer.current = documentPoint(event.evt.clientX, event.evt.clientY);
      pointerFrame.current ??= requestAnimationFrame(() => {
        pointerFrame.current = null;
        onPointer(pointer.current);
      });
    }
    const current = gesture.current;
    if (!current || !view) return;
    if (current.mode === "crop") {
      if (!primary) return;
      const source = slotSource(primary, sizes);
      if (!source) return;
      const dx = event.evt.clientX - origin.current.x;
      const dy = event.evt.clientY - origin.current.y;
      if (dx === 0 && dy === 0) return;
      origin.current = { x: event.evt.clientX, y: event.evt.clientY };
      // Dragging moves the photo, so the crop moves the opposite way, in source pixels.
      const perPixel = primary.source.crop.w / Math.max(1, primary.rect.w) / view.scale;
      const pending = cropDelta.current ?? { dx: 0, dy: 0 };
      cropDelta.current = { dx: pending.dx - dx * perPixel, dy: pending.dy - dy * perPixel };
      schedule();
      return;
    }
    latest.current = {
      x: event.evt.clientX,
      y: event.evt.clientY,
      alt: event.evt.altKey,
      shift: event.evt.shiftKey,
    };
    schedule();
  };

  const endDrag = () => {
    if (frame.current !== null) {
      cancelAnimationFrame(frame.current);
      frame.current = null;
      flush();
    }
    const current = gesture.current;
    if (current?.mode === "slot" && current.collapse && !current.moved) {
      onSelectSlot(current.id, "replace");
    }
    gesture.current = null;
    latest.current = null;
    setMoving(false);
    setSnapGuides({ x: null, y: null });
  };

  const onDoubleClick = (event: KonvaEventObject<MouseEvent>) => {
    const point = documentPoint(event.evt.clientX, event.evt.clientY);
    if (!point) return;
    const hit = captionAt(point);
    if (hit) setEditing({ id: hit.id, value: hit.text });
  };

  const commitEditing = () => {
    if (editing && editing.value.trim()) onEditCaption(editing.id, editing.value.trim());
    setEditing(null);
  };

  const editingBox = editing ? boxes.get(editing.id) : null;
  const guideX = guides?.x ?? snapGuides.x;
  const guideY = guides?.y ?? snapGuides.y;
  const cursor =
    tool === "crop" ? "grab" : moving ? "grabbing" : "default";

  return (
    <div
      ref={container}
      className="relative h-full w-full overflow-hidden bg-[#111]"
      data-tool={tool}
      onDragOver={(event) => {
        if (onDropPhoto && event.dataTransfer.types.includes(PHOTO_MIME)) event.preventDefault();
      }}
      onDrop={(event) => {
        const photoId = event.dataTransfer.getData(PHOTO_MIME);
        if (!onDropPhoto || !photoId) return;
        event.preventDefault();
        const point = documentPoint(event.clientX, event.clientY);
        if (!point) return;
        const dropTarget = slotAt(doc.slots, point);
        onDropPhoto(photoId, dropTarget?.id ?? null, point);
      }}
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
          onDblClick={onDoubleClick}
          onMouseLeave={() => {
            endDrag();
            onPointer?.(null);
          }}
          style={{ cursor }}
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
                dimmed={tool === "crop" && primaryId !== null && slot.id !== primaryId}
              />
            ))}
            {doc.captions.map((item) => (
              <CaptionNode key={item.id} caption={item} hidden={editing?.id === item.id} />
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
            <SelectionOverlay
              slots={selectedSlots}
              primary={primary}
              caption={caption}
              captionBox={caption ? (boxes.get(caption.id) ?? null) : null}
              scale={view.scale}
              transformable={transformable}
            />
            {guideX != null && (
              <Line
                points={[guideX, 0, guideX, height]}
                stroke="#FF2D9B"
                strokeWidth={2 / view.scale}
              />
            )}
            {guideY != null && (
              <Line
                points={[0, guideY, width, guideY]}
                stroke="#FF2D9B"
                strokeWidth={2 / view.scale}
              />
            )}
          </Layer>
        </Stage>
      )}
      {editing && editingBox && view && (
        <input
          // Inline caption editing: an input laid over the canvas, at the caption's own size.
          autoFocus
          className="absolute z-10 rounded-sm border border-accent bg-panel px-1 text-text outline-none"
          style={{
            left: editingBox.x * view.scale + view.x,
            top: editingBox.y * view.scale + view.y,
            width: Math.max(120, editingBox.w * view.scale + 24),
            height: editingBox.h * view.scale,
            fontSize: Math.max(11, editingBox.h * view.scale * 0.7),
          }}
          value={editing.value}
          onChange={(event) => setEditing({ id: editing.id, value: event.target.value })}
          onBlur={commitEditing}
          onKeyDown={(event) => {
            event.stopPropagation();
            if (event.key === "Enter") commitEditing();
            if (event.key === "Escape") setEditing(null);
          }}
        />
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

/** Drag & drop payload of a photo dragged out of the picker onto the canvas. */
export const PHOTO_MIME = "text/x-the-frame-photo";

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
