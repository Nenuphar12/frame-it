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
- Inner shadow: **canvas shadow offsets ignore the transform** — the offset must be scaled by the stage scale
  (times the device pixel ratio) and, for a rotated slot, rotated into device space (the server applies the
  offset in the slot's frame, before rotation).
  ⚠️ **Corrected in Phase 5**: the far-away ring measured here (drawn 20 000 px aside, the distance compensated
  by the shadow offset) is correct on paper but unusable — the browser allocates a surface spanning the shape
  *and* its shadow, so it froze the tab. Since the layer rect clips the ring's own ink anyway, the ring is
  drawn directly **around** the layer (padding `3σ + |offset|`) with no compensation offset
  (`editor/canvas/SlotNode.tsx`).
- Canvas `letterSpacing` also adds space after the last character, Pango only between characters: shift the
  text by `spacing/2` (middle) or `spacing` (end) when drawing.
- Texture: build the tinted tile once per (texture, colour, strength) with the exact formula.
- Tolerances for "client preview matches server render" (Phase 5 AC): shadows/texture max diff ≤ 4;
  rotated edges and text are resampling/metric differences (compare ink boxes, ≤ 2 px).

## Measured in the editor (2026-09-19, Phase 5 sign-off)

The S3 numbers above come from a bare Canvas 2D harness. The check below is the **editor itself**
(`EditorStage`, proxies, Konva) against the server render of the same artwork, measured in the page: the
content layer is cropped to the mat, the server JPEG is drawn into a canvas of the same size, and the two
`ImageData` are compared (the overlay layer — guides, selection — is a second Konva layer and is excluded).
The stage was at its fit zoom, ≈ 0.337 (1 canvas px ≈ 3 TV px), and the client draws the 2560 px proxy while
the server draws the original, so edge pixels differ by resampling alone.

| Artwork | MAE | max | subpixels > 8 |
|---|---|---|---|
| Single photo, fill, paper texture, recessed shadow | **1.05** | 52 | 1.1 % |
| Polaroid pile (3 rotated slots, inner shadows) | **1.22** | 59 | 1.8 % |
| Single photo + caption (Cormorant Garamond 96 px, middle anchor) | **1.52** | 169 | — |

Caption ink box, client vs server, in TV px: **(−3, −3, +3, 0)** — one canvas pixel, the resolution of the
measurement. Text stems are where the `max` comes from (sub-pixel glyph positioning).

**Bug this found.** Konva does not put a `Text` node's `y` on the line top: it draws with
`textBaseline = "alphabetic"` after translating by `(ascent − descent) / 2 + lineHeight / 2`, measured on an
`M` (`konva/lib/shapes/Text.js`). The editor was offsetting by the *renderer's* rule
(`floor(ascender × size / upm + 0.5)`), which put captions **≈ 14 TV px too high** at 96 px, and it measured
the text width without the weight in the font shorthand (so an anchored caption was a few px off, too).
`editor/canvas/fonts.ts` now replicates Konva's own rule and font shorthand; the numbers above are after the
fix (caption band MAE 2.38 → 1.08). There is no automated guard: it depends on browser font metrics, which
the Node conformance script cannot measure.

## Caption rotation pivot (2026-09-21, Phase 6)

The renderer rotates a caption around its **anchor point** (`caption.x`, `caption.y` — the baseline anchor;
`_draw_caption` passes it as the affine pivot). A Konva `Text` node rotates around its own `x`/`y`, which is
the top-left of the text box, so a rotated caption drifted by up to the text's width on the canvas while the
server drew it correctly. `CaptionNode` now positions the node *on* the anchor point and shifts the glyphs off
it with `offsetX`/`offsetY` (the anchor shift and the baseline offset of `canvas/fonts.ts`), so both rotate
around the same point. It only showed on captions with a non-zero rotation, which nothing could produce before
captions became editable.
