# S1 — Decoding matrix (2026-09-16)

Environment: `pyvips` 3.x + `pyvips-binary` (libvips **8.18.6**), Pillow 12, Python 3.14, Linux x86-64.

## Capabilities of the prebuilt libvips

| Loader / feature | Available | Notes |
|---|---|---|
| jpegload / pngload / webpload / tiffload | ✅ | |
| heifload (AV1 / AVIF) | ✅ | libheif with **aom only** |
| heifload (HEVC / HEIC) | ❌ | no libde265 → **HEIC unsupported** (user decision: dropped for v1) |
| uhdrload (Ultra HDR JPEG) | ✅ | SDR base used |
| icc_transform (lcms) | ✅ | built-in profiles `srgb`, `p3`, `cmyk` |
| jxlload, magickload | ❌ | not needed |

`frame-it doctor` reports these at runtime; startup fails if a required one is missing.

## Results (synthetic fixtures, reproduced by `tests/unit/test_imaging.py`)

| Input | Result |
|---|---|
| JPEG tagged Display P3 (200,100,50) | → sRGB (215,93,32) with perceptual intent; `is_wide_gamut` detected from ICC description (`sP3C`) |
| JPEG with EXIF orientation 6 | probe reports 200×300 (post-orientation); proxy and full decode rotated |
| 16-bit PNG (rgb16) | converted to 8-bit sRGB, value-exact; `bit_depth=16` + warning `high_bit_depth_reduced` |
| PNG with alpha | flattened on white |
| CMYK JPEG without profile | converted with libvips' default CMYK profile |
| AVIF (AV1) | decodes; EXIF read via libvips `exif-data` |
| HEIC (ftyp `heic`) | rejected with `unsupported_format_heic` before decoding (magic-byte sniff) |
| Truncated JPEG | rejected with `corrupt_image` |
| > `max_image_pixels` | rejected with `image_too_large` (header only, no decode) |

## Decisions

- All pixel access goes through `imaging/decode.py`; EXIF is parsed from the libvips blob with Pillow's
  `Image.Exif` (uniform for JPEG/PNG/AVIF, no Pillow decoding).
- Proxies use `pyvips.Image.thumbnail` (shrink-on-load) then colour management → fast ingest.
- Still to validate with **real device files** (Android Ultra HDR JPEG, a P3 phone JPEG): add them as CC0
  fixtures when available (plan §13.5).
