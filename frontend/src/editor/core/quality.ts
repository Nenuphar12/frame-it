// Quality tiers and artwork aggregates — mirror of backend/src/the_frame_v2/domain/quality.py.
// Spec: docs/geometry-and-quality.md §7.2.
import { roundHalfEven } from "./geometry.ts";

export type Tier = "native" | "downscaled" | "upscaled";
export const TIER_ORDER: Record<Tier, number> = { native: 0, downscaled: 1, upscaled: 2 };

export interface SlotGeometry {
  rect_w: number;
  rect_h: number;
  crop_w: number;
  crop_h: number;
  rotation: number;
  has_photo: boolean;
}

export interface SlotQuality {
  tier: Tier;
  scale: number;
  /** Badge value: round(scale × 100). */
  percent: number;
}

export interface ArtworkQuality {
  worst_tier: Tier | null;
  min_scale: number | null;
  max_scale: number | null;
  photo_count: number;
  is_incomplete: boolean;
}

export function slotScale(slot: SlotGeometry): number {
  return Math.max(slot.rect_w / slot.crop_w, slot.rect_h / slot.crop_h);
}

export function slotQuality(slot: SlotGeometry): SlotQuality {
  const scale = slotScale(slot);
  let tier: Tier;
  if (slot.rect_w === slot.crop_w && slot.rect_h === slot.crop_h && slot.rotation === 0) {
    tier = "native";
  } else if (scale <= 1) {
    tier = "downscaled";
  } else {
    tier = "upscaled";
  }
  return { tier, scale, percent: roundHalfEven(scale * 100) };
}

/** Empty slots are ignored for tiers and make the artwork incomplete (as does having no slot). */
export function artworkQuality(slots: SlotGeometry[]): ArtworkQuality {
  const filled = slots.filter((s) => s.has_photo).map(slotQuality);
  if (filled.length === 0) {
    return {
      worst_tier: null,
      min_scale: null,
      max_scale: null,
      photo_count: 0,
      is_incomplete: true,
    };
  }
  let worst: Tier = "native";
  for (const q of filled) if (TIER_ORDER[q.tier] > TIER_ORDER[worst]) worst = q.tier;
  const scales = filled.map((q) => q.scale);
  return {
    worst_tier: worst,
    min_scale: Math.min(...scales),
    max_scale: Math.max(...scales),
    photo_count: filled.length,
    is_incomplete: filled.length < slots.length,
  };
}
