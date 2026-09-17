# Geometry, quality & placement rules

> Extracted from `PLAN.md` §7 (Phase 1). This file is now the maintained spec.

Implemented identically in `backend/src/the_frame_v2/domain/` and `frontend/src/editor/core/`, verified by
`conformance/geometry/*.json` (§13.3).

### 7.1 Coordinate conventions

- Canvas: origin top-left, x → right, y → down, unit = TV pixel, integers.
- Source space: original pixels **after** EXIF orientation, then `orient.rotate` (clockwise), then `orient.flip_h`.
- Changing `orient` transforms the existing crop into the new space (not a reset).
- Rotation: degrees clockwise around the center of `rect` (float allowed, rounded to 0.1°).

### 7.2 Scale and tiers

```
scale_x = rect.w / crop.w ; scale_y = rect.h / crop.h ; scale = max(scale_x, scale_y)
tier = native      if rect.w == crop.w and rect.h == crop.h and rotation == 0
     = downscaled  if scale ≤ 1            (includes rotated 1:1 slots, labelled "resampled")
     = upscaled    otherwise               (badge shows round_half_even(scale*100) %)
```
Artwork aggregates: `worst_tier` (native < downscaled < upscaled), `min_scale`, `max_scale`.
Empty slots are ignored for tiers and set `is_incomplete`.

### 7.3 Quality lock behaviour (editor constraint solver, `constraints.ts`)

| Lock | Resize slot | Resize crop |
|---|---|---|
| `native` | Crop size follows slot size (centered on current crop center, clamped to source); if source too small → clamp slot | Slot size follows crop size (anchored at slot center) |
| `no_upscale` | Clamp so `rect ≤ crop`; if user drags beyond, grow crop (keeping ratio) until source bounds, then clamp | Clamp so `crop ≥ rect` |
| `free` | Unconstrained; crop kept | Unconstrained; slot kept |

### 7.4 Placement modes (single slot)

- **fit_in_mat** — available area `A = canvas − margins`. Slot = largest rect with crop aspect that fits `A`,
  further limited by the lock (`no_upscale` ⇒ ≤ crop size; `native` ⇒ = crop size), centered in `A`.
  Margins are therefore minimums.
  **Native linking (bidirectional)**:
  - Edit margins ⇒ `A` changes ⇒ if `crop_ratio` is `free`: crop = `A` dimensions clamped to source; otherwise
    crop = largest crop with the ratio fitting `A`, clamped to source; slot = crop size.
  - Edit crop ⇒ slot = crop size ⇒ margins recomputed: extra space `(canvas − slot)` distributed among sides
    **preserving the previous per-side proportions** (when `linked`, uniform).
- **fill** — slot = full canvas; crop = largest centered 16:9 crop (user pans/zooms). If lock forbids upscale
  and source < 3840×2160 ⇒ conflict ⇒ alternatives panel.
- **manual** — any geometry; mandatory for multi-slot artworks. Switching to manual keeps current geometry.

Rounding rule (everywhere): compute in floats, then `round half to even` on final integer fields only.

Implemented functions (both languages, `conformance/geometry/placement.json`): `available_area`, `fit_rect`
(largest rect of a given ratio in an area, limited by the lock, centred), `largest_crop` (ratio + centre,
clamped), `native_crop_for_area` (margins edited under `native`), `margins_for_slot` (crop edited under
`native`: extra space shared in the previous per-side proportions, equal split when both sides are 0; `linked`
⇒ `floor(min(extra_x, extra_y) / 2)` on every side), `fit_in_mat`, `fill`/`fill_slot` (a lock the source
cannot honour becomes `free`), `fit_slot`. Geometry helpers (`geometry.json`): `rect_to_oriented`,
`rect_from_oriented`, `reorient_crop`, `crop_within`, `aspect_consistent`, `parse_ratio`, `rotated_bounds`.
Constraint solver, snapping and alternatives are Phase 5.

### 7.5 Snapping (`snapping.ts`)

Priority order within 8 screen px: quality points (scale = 1, max size without upscale) → canvas edges/center →
other slots' edges/centers → equal gaps between slots → margins. Hold `Alt` to disable. Visual guides drawn in magenta.

### 7.6 Alternatives when upscaled (`alternatives.ts`)

For a slot with `scale > 1`, generate only feasible candidates (each is a full document patch + preview):
1. **Keep framing** — lock `free`, shows `upscaled N%`.
2. **Show more of the photo** — keep slot, enlarge crop to slot size (feasible if source large enough).
3. **Shrink the photo** — keep crop, slot = crop size (mat grows / slot shrinks around its center).
4. (fill placement) **Switch to fit in mat**.
