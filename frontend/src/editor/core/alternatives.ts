// Alternatives for an upscaled slot — mirror of backend/src/frame_it/domain/alternatives.py.
// Spec: docs/geometry-and-quality.md §7.6. Parity: conformance/geometry/alternatives.json.
import { CANVAS, roundHalfEven, type Margins, type Rect, type Size } from "./geometry.ts";
import type { SlotState } from "./constraints.ts";
import { cropCenter, fitInMat, marginsForSlot, type QualityLock } from "./placement.ts";

export type AlternativeId = "keep_framing" | "show_more" | "shrink" | "fit_in_mat";
export type Placement = "fit_in_mat" | "fill" | "manual";

/** A full patch: what the slot becomes, and the document changes it implies. */
export interface Alternative {
  id: AlternativeId;
  rect: Rect;
  crop: Rect;
  quality_lock: QualityLock;
  /** `null` when the document's placement does not change. */
  placement: Placement | null;
  /** `null` when the margins do not change. */
  margins: Margins | null;
}

function centred(rect: Rect, size: Size): Rect {
  return {
    x: roundHalfEven(rect.x + (rect.w - size.w) / 2),
    y: roundHalfEven(rect.y + (rect.h - size.h) / 2),
    w: size.w,
    h: size.h,
  };
}

export function isUpscaled(state: SlotState): boolean {
  return state.rect.w > state.crop.w || state.rect.h > state.crop.h;
}

/** `free` was chosen because the photo had to be enlarged: go back to the default lock. */
function kept(lock: QualityLock): QualityLock {
  return lock === "free" ? "no_upscale" : lock;
}

/** Feasible ways out of an upscaled slot (empty when the slot is not upscaled). */
export function alternatives(
  state: SlotState,
  source: Size,
  lock: QualityLock,
  placement: Placement,
  margins: Margins,
  linked = false,
  cropRatio = "original",
  mirrorX = false,
  mirrorY = false,
): Alternative[] {
  if (!isUpscaled(state)) return [];
  const { rect, crop } = state;
  const result: Alternative[] = [
    { id: "keep_framing", rect, crop, quality_lock: "free", placement: null, margins: null },
  ];

  if (source.w >= rect.w && source.h >= rect.h) {
    const [cx, cy] = cropCenter(crop);
    result.push({
      id: "show_more",
      rect,
      crop: {
        x: Math.min(Math.max(0, roundHalfEven(cx - rect.w / 2)), source.w - rect.w),
        y: Math.min(Math.max(0, roundHalfEven(cy - rect.h / 2)), source.h - rect.h),
        w: rect.w,
        h: rect.h,
      },
      quality_lock: kept(lock),
      placement: null,
      margins: null,
    });
  }

  const size = { w: crop.w, h: crop.h };
  if (placement === "fit_in_mat") {
    const newMargins = marginsForSlot(size, margins, linked, CANVAS, mirrorX, mirrorY);
    const shrunk = fitInMat(source, crop, cropRatio, newMargins, "no_upscale").rect;
    result.push({
      id: "shrink",
      rect: shrunk,
      crop,
      quality_lock: kept(lock),
      placement: null,
      margins: newMargins,
    });
  } else {
    result.push({
      id: "shrink",
      rect: centred(rect, size),
      crop,
      quality_lock: kept(lock),
      placement: null,
      margins: null,
    });
  }

  if (placement === "fill") {
    const fitted = fitInMat(source, crop, cropRatio, margins, "no_upscale");
    result.push({
      id: "fit_in_mat",
      rect: fitted.rect,
      crop: fitted.crop,
      quality_lock: fitted.quality_lock,
      placement: "fit_in_mat",
      margins: null,
    });
  }
  return result;
}
