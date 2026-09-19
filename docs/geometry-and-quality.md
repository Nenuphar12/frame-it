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

### 7.3 Quality lock behaviour (editor constraint solver)

| Lock | Resize slot | Resize crop |
|---|---|---|
| `native` | Crop size follows slot size (centered on current crop center, clamped to source); if source too small → clamp slot | Slot size follows crop size (anchored at slot center) |
| `no_upscale` | Clamp so `rect ≤ crop`; if user drags beyond, grow crop (keeping ratio) until source bounds, then clamp | Clamp so `crop ≥ rect` |
| `free` | Unconstrained; crop kept | Unconstrained; slot kept |

Implemented in `domain/constraints.py` ↔ `editor/core/constraints.ts` (fixtures `constraints.json`).
Two invariants hold whatever the user drags: `rect` and `crop` keep the same aspect ratio
(`aspect_consistent`), and the lock holds — so the server never rejects what the editor produces.

| Function | Behaviour |
|---|---|
| `resize_slot(state, requested, source, lock, anchor)` | *Cover* semantics: the requested size is a box the slot must cover, so dragging one edge grows the slot. `anchor` is the point of the rect that stays fixed (`(0,0)` = top-left, `(0.5,0.5)` = centred). |
| `resize_crop(state, requested, source, lock)` | Crop clamped into the source. The slot follows only when it must: `native` always; `no_upscale` clamps the crop so it never drops below the slot (shrinking the slot only when the source cannot give more); any lock when the crop's **aspect** changed (`crop_ratio = free`), preserving the current scale. |
| `pan_crop` / `zoom_crop` | Pan the photo inside the slot; zoom (`factor > 1` shows more) then resolves through `resize_crop`. |
| `apply_lock(state, lock, source)` | Repairs a slot when the lock changes, preserving the framing: `native` takes the crop at the slot's size (scale 1); `no_upscale` shrinks an enlarged slot to its crop size around its centre; `free` changes nothing. |
| `apply_crop_ratio(state, ratio, source, lock)` | Largest rect with the new ratio inside the current crop, centred on it; the lock then resolves the slot. |

### 7.4 Placement modes (single slot)

- **fit_in_mat** — available area `A = canvas − margins`. Slot = largest rect with crop aspect that fits `A`,
  further limited by the lock (`no_upscale` ⇒ ≤ crop size; `native` ⇒ = crop size), centered in `A`.
  Margins are therefore minimums.
  **Native linking (bidirectional)**:
  - Edit margins ⇒ `A` changes ⇒ if `crop_ratio` is `free`: crop = `A` dimensions clamped to source; otherwise
    crop = largest crop with the ratio fitting `A`, clamped to source; slot = crop size. This runs on **every**
    margin edit, both ways: growing the margins shrinks the crop and shrinking them grows it back (up to the
    source), keeping the crop centre. Deriving it only when the crop overflowed `A` made the margins look
    one-way — the photo never came back after a detour through big margins.
  - Edit crop ⇒ slot = crop size ⇒ margins recomputed: extra space `(canvas − slot)` distributed among sides
    **preserving the previous per-side proportions** (when `linked`, uniform; when `mirror_x` / `mirror_y`,
    that axis is split evenly so both sides stay equal).
- **fill** — slot = full canvas; crop = largest centered 16:9 crop (user pans/zooms). If lock forbids upscale
  and source < 3840×2160 ⇒ conflict ⇒ alternatives panel.
- **manual** — any geometry; mandatory for multi-slot artworks. Switching to manual keeps current geometry.

Rounding rule (everywhere): compute in floats, then `round half to even` on final integer fields only.

Implemented functions (both languages, `conformance/geometry/placement.json`): `available_area`, `fit_rect`
(largest rect of a given ratio in an area, limited by the lock, centred), `largest_crop` (ratio + centre,
clamped), `native_crop_for_area` (margins edited under `native`), `margins_for_slot` (crop edited under
`native`: extra space shared in the previous per-side proportions, equal split when both sides are 0; `linked`
⇒ `floor(min(extra_x, extra_y) / 2)` on every side; `mirror_x` / `mirror_y` ⇒ `extra // 2` on both sides of
that axis), `fit_in_mat`, `fill`/`fill_slot` (a lock the source
cannot honour becomes `free`), `fit_slot`. Geometry helpers (`geometry.json`): `rect_to_oriented`,
`rect_from_oriented`, `reorient_crop`, `crop_within`, `aspect_consistent`, `parse_ratio`, `rotated_bounds`.
Constraint solver and alternatives: §7.3 and §7.6 (Phase 5).

### 7.5 Snapping (`editor/core/snapping.ts`, client only)

Priority order within 8 screen px: quality points (scale = 1, max size without upscale) → canvas edges/center →
other slots' edges/centers → equal gaps between slots → margins. Hold `Alt` to disable. Visual guides drawn in magenta.

Snapping applies to **dragged** values only. A value typed in a number field is taken literally: the tolerance
is 8 screen px, which is tens of document px on a fitted stage, so snapping a typed margin swallowed it (typing
`1` next to a `0` margin gave `0` back).

Client-only (the tolerance is in *screen* pixels, so it depends on the stage zoom) but pure: `snap(value,
candidates, tolerance)` picks the best candidate by priority, then by distance. Candidate generators:
`margin_candidates` (used by the margin controls: the quality point is the margin that makes the available area
exactly as wide/tall as the crop, i.e. scale 1) and `slot_candidates` (canvas and slot edges/centres, for the
free-form slot dragging of Phase 6). Equal gaps between slots come with Phase 6.

### 7.6 Alternatives when upscaled

For a slot with `scale > 1`, generate only feasible candidates (each is a full document patch + preview):
1. **Keep framing** — lock `free`, shows `upscaled N%`.
2. **Show more of the photo** — keep slot, enlarge crop to slot size (feasible if source large enough).
3. **Shrink the photo** — keep crop, slot = crop size (mat grows / slot shrinks around its center).
4. (fill placement) **Switch to fit in mat**.

Implemented in `domain/alternatives.py` ↔ `editor/core/alternatives.ts` (fixtures `alternatives.json`):
`alternatives(state, source, lock, placement, margins, linked, crop_ratio)` returns an ordered list of
`Alternative(id, rect, crop, quality_lock, placement, margins)` — a ready-to-apply patch of the slot plus the
document fields that must follow. Under `fit_in_mat`, **shrink** also grows the margins around the smaller slot
(`margins_for_slot`, keeping the per-side proportions). A lock of `free` goes back to `no_upscale` when an
alternative removes the enlargement. Empty list when the slot is not upscaled.
