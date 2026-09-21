# Artwork document spec (v1)

> Extracted from `PLAN.md` §6 (Phase 1). This file is now the maintained spec.

Validated by Pydantic (`domain/document.py`), published as JSON Schema (`docs/schemas/artwork-document.v1.json`),
exposed through OpenAPI → TS types. **Array order = z-order (first is back-most).**

```jsonc
{
  "schema": 1,
  "canvas": { "width": 3840, "height": 2160 },          // constant in v1, still stored
  "mat": {
    "color": "#F2EFE8",
    "texture": null                                    // or { "id": "paper-01", "strength": 0.35 }
  },
  "placement": "fit_in_mat",                            // fit_in_mat | fill | manual (multi-slot ⇒ manual)
  "margins": { "top": 240, "right": 240, "bottom": 300, "left": 240,
               "linked": false,                        // all four sides move together
               "mirror_x": false, "mirror_y": false }, // left = right / top = bottom
  "slots": [
    {
      "id": "s_01",
      "photo_id": "0192…",                              // null ⇒ empty slot (incomplete artwork)
      "rect": { "x": 612, "y": 240, "w": 2616, "h": 1744 },   // photo area in canvas px, integers, unrotated
      "rotation": 0,                                    // degrees clockwise around rect center, [-180, 180]
      "source": {
        "orient": { "rotate": 0, "flip_h": false },     // rotate ∈ {0,90,180,270}; applied after EXIF
        "crop": { "x": 0, "y": 0, "w": 6000, "h": 4000 },// integers, in oriented source px
        "crop_ratio": "original"                        // original | free | "16:9" | "4:3" | "3:2" | "1:1" | "w:h"
      },
      "quality_lock": "no_upscale",                     // native | no_upscale | free
      "bands": [ { "width": 12, "color": "#FFFFFF" } ], // inner → outer, max 3, width ≥ 1
      "shadow": { "type": "inner", "offset_x": 0, "offset_y": 6, "blur": 24, "color": "#000000", "opacity": 0.35 }
                                                        // null | type inner|drop; blur ∈ [0,200]; opacity ∈ [0,1]
    }
  ],
  "captions": [
    { "id": "c_01", "text": "Kyoto — April 2026", "font": "cormorant-garamond", "weight": 500,
      "size": 48, "color": "#3A3A3A", "letter_spacing": 0.02,
      "x": 1920, "y": 2040, "anchor": "middle", "rotation": 0 }   // (x,y) = baseline anchor point
  ]
}
```

Implementation: `backend/src/the_frame_v2/domain/document.py`; JSON Schemas in `docs/schemas/` (`make gen-api`).

**Validation rules** (server rejects with 422, client never produces):
- All rect/crop/margin/band values are integers; `rect.w, rect.h ≥ 1`. Canvas coordinates within ±20 000,
  crop values ≤ 100 000; margins leave at least 1 px (`left + right < 3840`, `top + bottom < 2160`).
- `crop` lies within oriented source bounds (needs photo dims → validated in service layer, like photo existence,
  fonts/weights and textures).
- Aspect consistency: `|rect.w·crop.h − rect.h·crop.w| ≤ (rect.w + rect.h + crop.w + crop.h) / 2` — each side of
  either rectangle may be off by 0.5 from rounding. (The Phase 1 formula `≤ 1/min(crop)` rejected valid upscaled
  slots whose crop is rounded from the slot ratio.)
- `quality_lock = native` ⇒ `rect.w = crop.w`, `rect.h = crop.h`, `rotation = 0`.
- `quality_lock = no_upscale` ⇒ `rect.w ≤ crop.w` and `rect.h ≤ crop.h`.
- Slot/caption ids unique (`[A-Za-z0-9_-]{1,64}`); `font` and `texture.id` must exist in bundled assets, `weight`
  must be one of the font's bundled weights (`GET /fonts`).
- `placement` other than `manual` ⇒ exactly one slot. Colours are `#RRGGBB`. Captions are single-line.
- `rotation` is stored rounded to 0.1°. Slots may extend beyond the canvas (clipped at render).
- Errors: 422 `invalid_document` with `extra.errors = [{loc, msg, type}]` (e.g. `loc = ["slots", 0, "source",
  "crop"]`, `type = "crop_out_of_bounds"`); a malformed request body gives 422 `validation_error` with the same
  shape (`loc` prefixed by `body`).

**Editing** (Phase 6): the editor creates slot ids as `s_<n>` and caption ids as `c_<n>` (never reusing one),
adds a slot with `NEW_SLOT_FRACTION` of the available area at the photo's aspect (§7.7), and switches
`placement` to `manual` as soon as a second slot exists. A slot without a photo carries `quality_lock = free`
and a crop the size of its rect (a placeholder); filling it takes `no_upscale` back.

**Evolution**: `schema` bumps require a pure migration function `migrate_vN_to_vN+1` in both `domain/document.py`
and archive import; documents are migrated on read and persisted on next save.

**Frame style document**: `{ mat, margins, slot_defaults: { bands, shadow, quality_lock }, caption_defaults: { font, weight, size, color, letter_spacing } }`.
**Layout document**: `{ slots: [{ id, rect, rotation, quality_lock, fill_mode: "fill"|"fit" }], captions: [{ id, placeholder, x, y, anchor, rotation }] }`.
Layout rects are designed for the full canvas.

**Building an artwork** (`domain/templates.py::build_document`, templates copied on apply):
- One-slot layouts use `placement` (default `fit_in_mat`): the whole photo inside the style's margins, or `fill`.
  The style's `slot_defaults.quality_lock` applies.
- Multi-slot layouts are `manual`: layout rects are mapped (edges scaled) into the style's available area
  `canvas − margins`; `fill` slots crop the photo to the slot ratio (centred, `crop_ratio = "w:h"`), `fit` slots
  shrink to the photo ratio inside the rect. The layout slot's lock applies.
- A lock the photo cannot honour becomes `free` (e.g. `no_upscale` for a small photo filling a slot): the
  artwork is created and shows its upscaled tier; the editor offers alternatives (§7.6).
- Fewer photos than slots ⇒ empty slots (artwork incomplete). Bands and shadow come from the style.
- Built-in presets: `assets/presets/{frame_styles,layouts}.json` (stable ids `builtin-style-*`,
  `builtin-layout-*`), seeded at startup. Default for new artworks: Gallery recessed + Single
  (setting `artwork_defaults`, UI in Phase 5).
