# Rendering spec

> Extracted from `PLAN.md` §8 (Phase 1). This file is now the maintained spec.

### 8.1 Pipeline (server, `imaging/render.py`, pyvips)

1. **Canvas**: 3840×2160, 3 bands uchar sRGB, filled with `mat.color`.
2. **Texture** (optional): bundled seamless 1024×1024 grayscale tile `t`, tiled from (0,0).
   Per channel: `out = clamp(round(mat + strength × (t − 128)), 0, 255)`.
3. **Slots**, in array order. For each slot with a photo:
   1. Decode original (§8.3) → oriented sRGB.
   2. Apply `orient.rotate`, then `orient.flip_h`.
   3. `crop` (integers).
   4. If not native: `resize(hscale = rect.w/crop.w, vscale = rect.h/crop.h, kernel = lanczos3)`; force exact
      `rect.w × rect.h` (crop/embed 1px if rounding differs).
   5. Bands inner → outer: `embed` with band color (size grows by `2×width`). Layer = photo+bands, RGBA opaque.
   6. **Inner shadow**: mask `m` = 255 outside layer rect / 0 inside (padded by `3σ+|offset|`), shift by offset,
      `gaussblur(σ = blur/2)`, crop back to layer rect, multiply by `opacity`, fill with shadow color, composite over layer.
   7. **Rotation** (≠0): `rotate(angle, interpolate = bicubic)` on the RGBA layer, transparent background.
   8. **Drop shadow**: alpha of (rotated) layer, padded, `gaussblur(σ = blur/2)`, × opacity, colored,
      composited onto canvas at layer position + offset.
   9. Composite layer onto canvas; top-left = `round(center − layer_size/2)` where
      `center = (rect.x + rect.w/2, rect.y + rect.h/2)`. Parts outside the canvas are clipped.
   All compositing: mode `over`, `compositing_space = srgb` (matches Canvas2D).
4. **Captions**: `pyvips.Image.text(fontfile=…, dpi=72, rgba=True)` using bundled font; letter spacing via Pango
   markup; anchor on baseline; optional rotation (bicubic); composite over.
5. Flatten to 3 bands uchar; assert 3840×2160.
6. **Outputs**: PNG master (compression 6, embedded sRGB ICC); JPEG derivative on demand
   (`Q = jpeg_quality`, `subsample_mode = off`, `optimize_coding = true`, strip metadata except sRGB ICC).

Region renders (loupe) use the same pipeline and `crop` at the end — libvips evaluates on demand, so only the
needed region is computed.

### 8.2 Client preview parity (`editor/canvas/`)

| Element | Client technique | Parity notes |
|---|---|---|
| Photos | Proxy (2560 long edge), drawn with Konva image + crop attrs | Only resampling differs |
| Texture | Build tinted tile via ImageData with the exact formula, use as pattern | Exact |
| Bands | Rects | Exact |
| Drop shadow | Canvas `shadowBlur = blur × stageScale` (canvas blur ≈ 2σ), offsets × stageScale | Visual parity, verified in spike S3 |
| Inner shadow | Offscreen canvas: inverted mask + shadow, clipped to rect | Same |
| Captions | Same font files via `@font-face`, Konva Text | Minor metric differences tolerated; TV preview uses server render |

**TV preview and loupe always use server renders** (authoritative).

### 8.3 Decoding & color (`imaging/decode.py`, `color.py`)

- Sniff magic bytes (never trust extension/mime). Supported: JPEG, PNG, AVIF (pyvips heifload). HEIC/HEIF (HEVC) → problem `unsupported_format_heic` with guidance.
- Reject > `max_image_pixels`, animated/multi-page files (use first/primary image only), CMYK JPEG converted via ICC.
- EXIF orientation applied (`autorot`); stored `width/height` are post-orientation.
- Color: if ICC present → `icc_transform("srgb", embedded = True, intent = perceptual)`; AVIF with nclx only → map
  primaries (sRGB/BT.709, Display P3, BT.2020) to a bundled ICC (compact CC0 profiles); none → assume sRGB.
  16-bit sources are transformed in 16-bit, then cast to 8-bit.
- HDR gain-map photos (Ultra HDR JPEG, AVIF with gain map): use the SDR base image. PQ/HLG-only HDR: tone-map is out of
  scope → flag `quality_warnings: ["hdr_unsupported"]` and use a clipped conversion.
- `imaging/capabilities.py` + `the_frame_v2 doctor`: report libvips version, loaders (heifload with AV1), lcms; fail fast
  at startup if a required capability is missing.

### 8.4 Render cache & jobs

- `render_hash = sha256(canonical_json(document) + renderer_version + sorted(photo sha256s) + asset versions)`.
- After each document save: enqueue `render` job with `coalesce_key = render:<artwork_id>` (only latest runs).
- Old renders for the artwork are deleted when a new one completes. SSE `artwork.rendered`.
- Memory: `pyvips.cache_set_max_mem`, one decoded original LRU of 2, `render_workers` default 1.

### 8.5 Performance budgets (mid-range laptop)

| Operation | Budget |
|---|---|
| Ingest 24 MP JPEG (decode, metadata, thumbs, proxy) | < 3 s |
| Ingest 12 MP AVIF | < 4 s |
| Render single slot 4K | < 2 s |
| Render 9-slot collage with shadows | < 6 s |
| Editor interaction (9 slots) | 60 fps on proxies |
| Grid scroll, 10k items | no jank (virtualized, lazy thumbs) |
| Region render (loupe 512²) | < 700 ms |
