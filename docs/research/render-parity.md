# S3 — Preview/render parity (done 2026-09-17, start of Phase 4)

Question: how close can the editor preview (Konva = Canvas 2D) get to the authoritative pyvips render for
shadows, textures, rotated slots and captions (`rendering-spec.md` §8.2)?

**Method.** `scripts/render_parity/scenes.py` renders four 3840×2160 scenes with the real renderer;
`scripts/render_parity/index.html` draws the same documents with plain Canvas 2D (what Konva calls:
`shadowBlur`, `drawImage`, `fillText`, `letterSpacing`, patterns) and compares pixels in Chrome
(desktop, 2026-09). Run: `python3 -m http.server` in a folder with both outputs, fonts and textures.

## Results

| Element | Client technique | Result | Verdict |
|---|---|---|---|
| Drop shadow (blur 12–48, coloured, offset) | `shadowBlur = blur`, `shadowOffset*`, `shadowColor` with alpha | max diff **3/255**, MAE ≤ 0.14; profiles match row by row | σ = blur / 2 **confirmed** |
| Inner shadow (blur 30 and 120) | clip to layer; even-odd ring drawn 20 000 px away with `shadowOffsetX` compensating | max diff **3**, MAE ≤ 0.49 | Formula confirmed |
| Mat texture (linen, strength 0.6) | tinted tile via `ImageData` with `floor(mat + s·(t−128) + 0.5)`, pattern fill | **identical** (max diff 0) | Exact |
| Rotated slot (7°, band) | `translate/rotate` + `drawImage` (smoothing high) | MAE 0.21, max 41 on antialiased edges only | Resampling-only difference |
| Captions (4 fonts, sizes 64–200, letter spacing 0–0.2 em, rotated) | `@font-face` with the bundled TTFs, `textBaseline = "alphabetic"`, `letterSpacing` | ink boxes within **±2 px** (most 0–1 px); MAE 0.8–3.5 per box (11.8 for 64 px EB Garamond: glyph-level offsets inside the line) | Acceptable; TV preview and loupe use the server render |

## Rules for the Phase 5 canvas (`editor/canvas/`)

- Shadows: pass `blur` unchanged to `shadowBlur` (times the stage scale), offsets in device px.
- Inner shadow: the far-away ring trick works, but **canvas shadow offsets ignore the transform**: for a rotated
  slot the compensation offset must be rotated into device space (server applies the offset in the slot's
  frame, before rotation).
- Canvas `letterSpacing` also adds space after the last character, Pango only between characters: shift the
  text by `spacing/2` (middle) or `spacing` (end) when drawing.
- Texture: build the tinted tile once per (texture, colour, strength) with the exact formula.
- Tolerances for "client preview matches server render" (Phase 5 AC): shadows/texture max diff ≤ 4;
  rotated edges and text are resampling/metric differences (compare ink boxes, ≤ 2 px).
