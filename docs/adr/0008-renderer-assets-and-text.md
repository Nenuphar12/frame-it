# ADR-0008 — Renderer assets, text and exactness choices

Status: accepted (2026-09-17, Phase 4)

## Context
Captions, textures and collage performance required choices the plan left open (§16: "exact bundled fonts
and texture set").

## Decision
- **Fonts**: Cormorant Garamond, EB Garamond, Inter (optical size 32), Josefin Sans — SIL OFL, built by
  `scripts/build_fonts.py` from google/fonts at a pinned commit as **static instances** with unique family names
  (`TF <id> <weight>`). Static files avoid variable-font support differences between Pango and browsers; unique
  names keep system fonts out of renders. Same files are served to the editor.
- **Text**: Pango through `pyvips.Image.text` (HarfBuzz shaping and kerning like browsers). Pillow's basic layout
  has no kerning (no raqm in wheels). Baseline from the font's hhea ascender, advance width measured with a
  marker glyph (libvips crops text to ink).
- **Textures**: three procedural CC0 tiles (paper, linen, canvas) from `scripts/generate_textures.py`,
  committed as PNG (their noise depends on the libvips version) with a manifest version in the render hash.
- **Exact rendering over speed**: originals are always decoded at full resolution; collages decode in
  parallel. JPEG shrink-on-load was measured (MAE ≈ 3 on sharp edges) and rejected.
- **Rotation** is an affine transform on the canvas pixel grid (no rounded placement), so 90°/180° are exact and
  region renders equal the full render.

## Consequences
~7 MB of fonts and ~2 MB of textures in the package. Captions support the fonts' glyph coverage (Latin,
Greek, Cyrillic depending on the font); missing glyphs fall back to Pango's defaults (not guaranteed identical
to the browser). Collage renders hold every decoded original in memory (≈ 3 bytes per source pixel per photo:
≈ 1.3 GB for nine 48 MP photos) — to revisit in the Phase 10 memory profiling.
