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
  "margins": { "top": 240, "right": 240, "bottom": 300, "left": 240, "linked": false },
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

**Validation rules** (server rejects with 422, client never produces):
- All rect/crop/margin/band values are integers; `rect.w, rect.h ≥ 1`.
- `crop` lies within oriented source bounds (needs photo dims → validated in service layer).
- Aspect consistency: `|rect.w/crop.w − rect.h/crop.h| ≤ 1/min(crop.w, crop.h)` (integer rounding tolerance).
- `quality_lock = native` ⇒ `rect.w = crop.w`, `rect.h = crop.h`, `rotation = 0`.
- `quality_lock = no_upscale` ⇒ `rect.w ≤ crop.w` and `rect.h ≤ crop.h`.
- Slot/caption ids unique; `font` and `texture.id` must exist in bundled assets.
- Slots may extend beyond the canvas (clipped at render).

**Evolution**: `schema` bumps require a pure migration function `migrate_vN_to_vN+1` in both `domain/document.py`
and archive import; documents are migrated on read and persisted on next save.

**Frame style document**: `{ mat, margins, slot_defaults: { bands, shadow, quality_lock }, caption_defaults: { font, weight, size, color, letter_spacing } }`.
**Layout document**: `{ slots: [{ id, rect, rotation, quality_lock, fill_mode: "fill"|"fit" }], captions: [{ …position/placeholder… }] }`.
