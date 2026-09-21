# Simple editor & parametric compositions (Phase 7)

> Spec for `PLAN.md` §14 Phase 7. Status: **proposed** — nothing implemented yet.
> Companion specs: `artwork-document.md` (document v1), `geometry-and-quality.md` (§7.x rules it reuses),
> `rendering-spec.md` (bands grow outward — §3 below depends on it).

## 1. Why

The Phase 6 editor is fully manual: every slot is placed by hand. It is precise but slow, and it gets worse as
soon as an artwork holds several photos. This phase adds a **parametric** way to build an artwork — pick a
configuration, move two sliders — and demotes the manual tools to a beta mode behind a switch.

Design goals, in order: a result that looks deliberate without any tweaking; two controls on the first screen;
nothing moves unless the user asked for it.

## 2. The `composition` block

A new **optional** field of the artwork document. `schema` stays `1`: an absent `composition` is a legacy or
hand-built artwork and every existing document stays valid, so there is no migration.

```jsonc
{
  "schema": 1,
  "mat": { "color": "#F2EFE8", "texture": null },
  "placement": "manual",
  "margins": { … },                    // written back by the solver, see §3.7
  "composition": {
    "recipe": "three-hero-left",       // id from assets/presets/recipes.json
    "balance": 0.62,                   // share of the root split's first child; Fill format only (§4.3)
    "outer":  { "x": 120, "y": 120 },  // minimum margin around the block, per axis
    "gutter": { "x": 80,  "y": 80 },   // gap between footprints, per axis, exact
    "format": "fill",                  // "fill" | "original" | "1:1" | "3:2" | … | "w:h"
    "border": { "width": 24, "color": "#FFFFFF" },   // null ⇒ no border; applied to every cell
    "caption": { "text": "Kyoto — April 2026", "place": "below" },  // place: "none" | "above" | "below"
    "detached": false                  // true ⇒ the slots are the truth, this block is memory only (§5)
  },
  "slots": [ … ],                      // derived from the block while detached = false
  "captions": [ … ]                    // derived from composition.caption while detached = false
}
```

Validation (in addition to the v1 rules):

- `recipe` must exist in the bundled catalogue, and its `count` must equal `len(slots)`.
- `balance` ∈ the recipe's declared range; ignored (and hidden) unless `format = "fill"`.
- `outer.x` ∈ [0, 800], `outer.y` ∈ [0, 450], `gutter.{x,y}` ∈ [0, 400]. Values that leave a cell narrower
  than `MIN_CELL = 40` px are clamped by the solver (§3.6), never rejected — an imported document must open.
- `format`: `"fill"`, `"original"` (only for a 1-cell recipe), or a ratio `w:h` with `w, h` ∈ [1, 1000].
- `border.width` ∈ [1, 200] when present.

## 3. The solver

Pure, mirrored: `domain/composition.py` ↔ `frontend/src/editor/core/composition.ts`, parity pinned by
`conformance/geometry/composition*.json`. Same rounding discipline as the rest of `domain/`: float maths,
`round_half_even` on final integer edges only.

```
solve(recipe, composition, photo_sizes) -> [Cell]     # Cell = { id, rect, ratio_label }
```

### 3.1 Recipe trees

A recipe is a split tree. Leaves are cells; `weights` drive Fill mode only.

```jsonc
{ "id": "three-hero-left", "count": 3, "name_key": "recipes.three-hero-left",
  "balance": { "min": 0.40, "max": 0.75, "default": 0.62 },   // null ⇒ no Balance slider
  "tree": {
    "split": "row", "weights": [2, 1],
    "children": [
      { "cell": "landscape" },
      { "split": "col", "weights": [1, 1],
        "children": [{ "cell": "landscape" }, { "cell": "landscape" }] }
    ] } }
```

- `split`: `row` (children left→right, separated by `gutter.x`) or `col` (top→bottom, `gutter.y`).
- `cell`: `landscape` | `portrait` | `square` | `auto`. Used **only** under a ratio format (§3.3);
  `auto` (the photo's own orientation) is reserved for the 1-cell recipe.
- **Cell order is depth-first = reading order**, and that is the slot order: photo *i* lands in cell *i*.
  The picker schemas are numbered so this is visible; swapping is one drag (§6).
- `balance` replaces the root split's weights with `[b, 1−b]`. Only a 2-child root may declare it.

### 3.2 Footprint space (the border)

The renderer draws bands **outward** from the slot rect (`rect.x − Σbands`, `rendering-spec.md` §3.19/§3.28).
So the solver works on **footprints** — the photo rect grown by `border.width` on each side — and the sliders
describe what the eye sees: `gutter` is the gap between two printed edges, `outer` the distance from the canvas
edge to a printed edge. The slot rect written to the document is the footprint deflated by `border.width`.

The aspect a format imposes is the **photo's**, not the footprint's. With `b = border.width` and a leaf of
target aspect `a`: `w_f = a·(h_f − 2b) + 2b`.

Shadows are ignored by the layout (they may overlap, as today).

### 3.3 Available area

`F = canvas ⊖ outer`. If `caption.place ≠ none`, reserve a band on that side before solving:

```
band = round(caption_size × 1.5) + gutter.y
A    = F minus band on the caption's side
```

`caption_size` comes from the style's `caption_defaults.size`. The reservation is a pure function of the size —
no font metrics — so both solvers agree (the `fonts.ts` measurement gotcha never enters the layout).

### 3.4 Fill format

Classic weighted split, the block fills `A` exactly.

- row: `free = w − (n−1)·gutter.x`; child widths `free × wᵢ / Σw`.
- col: `free = h − (n−1)·gutter.y`; child heights `free × hᵢ / Σw`.

Edges are accumulated as floats from the node origin and rounded one by one, gutters inserted as exact
integers, the last child snapped to the node's far edge — cells tile `A` with no drift (same technique as
`templates.map_rect_to_area`).

Each cell's `ratio_label` is its own `w:h`; leaf orientation is ignored.

### 3.5 Ratio format

Every cell must end up at exactly the chosen aspect. Let `r ≥ 1` be the landscape form of the format
(`3:2` and `2:3` are the same format); a cell's target aspect is `r` for `landscape`, `1/r` for `portrait`,
`1` for `square`, and the photo's own aspect for `auto`.

**Bottom-up**, every node gets an affine relation `w = α·h + β` between its footprint dimensions:

| node | α | β |
|---|---|---|
| leaf, aspect `a`, border `b` | `a` | `2b(1 − a)` |
| row of *n* children, gutter `gx` | `Σ αᵢ` | `Σ βᵢ + (n−1)·gx` |
| col of *n* children, gutter `gy` | `1 / Σ(1/αᵢ)` | `α · ( Σ(βᵢ/αᵢ) − (n−1)·gy )` |

*(col: children share the width, so `hᵢ = (w − βᵢ)/αᵢ` and `h = Σhᵢ + (n−1)gy`; invert.)*

**Fit and centre**: take `H = A.h`, `W = α·H + β`; if `W > A.w`, take `W = A.w`, `H = (A.w − β)/α`. The block
is centred in `A` — so `outer` is a **minimum** and the slack is shared equally between the two opposite sides.
`Balance` is inert here (§4.3): with every cell pinned to an aspect and every edge aligned, the proportions are
already determined.

**Top-down**: recurse with the same edge-accumulation walk as §3.4, child sizes coming from the affine
relations instead of the weights.

Worked example — `three-hero-left`, format `3:2`, `outer = 120`, `gutter = 80`, no border:
`α = 1.5 + 0.75 = 2.25`, `β = −60 + 80 = 20`, `A = 3600 × 1920`. `α·1920 + 20 = 4340 > 3600` ⇒
`H = (3600 − 20)/2.25 = 1591`, `W = 3600`. Hero `2387 × 1591`, each small cell `1133 × 756` (= 3:2 ✓),
block centred vertically with `(2160 − 1591)/2 = 284` px above and below.

### 3.6 Degenerate inputs

`MIN_CELL = 40` px on the photo rect. The panel bounds each slider by bisecting on the solver for the current
recipe and format, so a user cannot reach an over-constrained state. A document that arrives over-constrained
anyway (import, hand-edited JSON) is solved with gutters scaled down proportionally first, then `outer`, then
cells clamped to ≥ 1 px — the solver is total and never raises.

### 3.7 What the solver writes into the document

| field | value |
|---|---|
| `slots[i].rect` | cell *i*'s footprint deflated by `border.width` |
| `slots[i].rotation` | `0` — parametric compositions never rotate (rotation stays an Advanced tool) |
| `slots[i].source.crop` | preserved, re-fitted (§4.1) |
| `slots[i].source.crop_ratio` | the cell's `ratio_label` |
| `slots[i].quality_lock` | `no_upscale`, downgraded to `free` when the photo cannot honour it (§7.6 rule) |
| `slots[i].bands` | `[border]` when set, else `[]` |
| `slots[i].shadow` | untouched (style default / Advanced) |
| `margins` | the effective insets of the block's footprint bbox, `linked = false`, mirrors `false` |
| `placement` | `"manual"` |
| `captions` | one derived caption when `caption.place ≠ none`: `x = 1920`, `anchor = "middle"`, baseline `y` inside the reserved band; font/weight/size/colour from the style's `caption_defaults` |

Writing `margins` back keeps the Advanced panels and every existing helper reading a truthful document.

## 4. Re-solving

### 4.1 Crop preservation

Any composition change re-solves, and cell rects move. For each slot, the crop is recomputed **around the
previous crop's centre, keeping its zoom** (`crop.w` relative to the largest crop at the new ratio), clamped
into the source bounds; when no previous crop exists it is the centred cover crop. Same idea as
`placement.native_crop_for_area`, which already preserves `crop_center`. So reframing a photo survives a margin
drag — the invariant users notice first.

### 4.2 Triggers

Re-solve on: recipe, balance, outer, gutter, format, border, caption place/size, and on adding, removing or
swapping a photo. **Not** on a reframe (pan/zoom changes `source.crop` only, inside a fixed rect) and not on a
background change.

### 4.3 Balance

Shown only when the recipe declares it **and** `format = "fill"`. Under a ratio the panel shows a one-line hint
instead of the slider: *the format sets the proportions*.

### 4.4 Photo count changes

The count comes from the photos, not the picker. Adding or removing a photo keeps the current recipe if one
with the new count has the same id family, otherwise falls back to that count's first catalogue entry.
Margins, format, border, caption and every surviving crop are kept.

## 5. Detaching

The Advanced tools can do things the recipe cannot express (rotation, free placement, per-slot decorations).
The first such edit sets `composition.detached = true`:

- the slots become the truth; the block stays as **memory** of the last parameters;
- Simple mode disables its controls and shows a banner with **Re-apply layout** — one confirmed, undoable
  action that re-solves from the remembered parameters and clears the flag;
- the operation is a normal `store.edit()` patch, so `⌘Z` restores the hand-made geometry.

Edits that do **not** detach: reframing inside a cell, background, border, caption text, photo swap — Simple
owns those and they round-trip through the block.

## 6. UI

### 6.1 Mode switch

`/artworks/:id/edit` keeps one page. A `[Simple] [Advanced ᴮᴱᵀᴬ]` switch sits in the header; **Simple is the
default** for every artwork, including those without a `composition` (which show the picker instead of the
sliders). Advanced shows today's panel stack under a light warning strip: *Advanced tools are beta — free-form
edits drop the layout link.* The toggle is registered through `useRegisterCommands` (invariant 10), no default
shortcut. The canvas, undo/redo, autosave, review queue, TV preview and loupe are shared by both modes.

### 6.2 The Simple panel

One scrollable column, in this order:

```
Layout      ┌──┐┌──┐┌──┐┌──┐┌──┐          schemas, numbered, current recipe selected
            └──┘└──┘└──┘└──┘└──┘
Balance     ────●────  62%                 fill + asymmetric recipes only
Format      [Original] [Fill] [1:1] [5:4] [4:3] [3:2] [16:9] [ … ]
Margins     Outer  ────●────  120 px       ▸ More → Outer ↔ / ↕, Gap ↔ / ↕
            Gap    ──●──────   80 px
Photos      [1][2][3]                      drag to swap, click to select
              selected → drag on canvas to pan · Zoom ──●── 1.4×
Background  [swatch][swatch][swatch]  #F2EFE8
Border      ──●──────  24 px  [■]
Caption     [ Kyoto — April 2026        ]  ( ) none  (●) below  ( ) above
```

- `Original` appears **only** for the 1-cell recipe (the photo's own aspect, centred — today's `fit_in_mat`,
  and the default for a new single-photo artwork). Multi-photo recipes default to `Fill`.
- Sliders snap to stops; typed values never snap and keep what you type while focused (`panels/Controls.tsx`,
  the §7.5 lesson).
- Each `outer` slider shows its **effective** value next to the minimum when the block is centred with slack
  (`120 → 284`), so a slider that currently has no visible effect explains itself.
- Every slider's max comes from the bisection of §3.6.
- Reframe and zoom reuse the existing Framing controls and the existing pointer pipeline in `EditorStage`
  (invariant 12): panning a photo inside its cell is the crop gesture, with the rect fixed.

### 6.3 Picker schemas

Drawn from the solver itself: each thumbnail is `solve(recipe, {format: fill, outer: 6%, gutter: 4%})` at
thumbnail scale, rendered as SVG rects with the cell number. No hand-drawn assets, and a new recipe in the JSON
appears in the picker with a correct schema for free.

### 6.4 Catalogue

Rich for 2–4 photos, complete for 1, one safe default for 5 and 6. `name_key` → `i18n` (`recipes.*`).

| n | id | tree | schema |
|---|---|---|---|
| 1 | `single` | `cell(auto)` | `□` |
| 2 | `two-side-by-side` | `row[1:1](P,P)` | `▯▯` |
| 2 | `two-stacked` | `col[1:1](L,L)` | `▭ / ▭` |
| 2 | `two-hero-left` | `row[2:1](L,P)` ⚖ | `■ ▯` |
| 2 | `two-hero-right` | `row[1:2](P,L)` ⚖ | `▯ ■` |
| 3 | `three-row` | `row[1:1:1](P,P,P)` | `▯▯▯` |
| 3 | `three-hero-left` | `row[2:1](L, col[1:1](L,L))` ⚖ | `■ ▭/▭` |
| 3 | `three-hero-right` | `row[1:2](col[1:1](L,L), L)` ⚖ | `▭/▭ ■` |
| 3 | `three-one-over-two` | `col[1:1](L, row[1:1](P,P))` ⚖ | `▭ / ▯▯` |
| 3 | `three-two-over-one` | `col[1:1](row[1:1](P,P), L)` ⚖ | `▯▯ / ▭` |
| 4 | `four-grid` | `col[1:1](row[1:1](L,L), row[1:1](L,L))` | `▭▭ / ▭▭` |
| 4 | `four-row` | `row[1:1:1:1](P,P,P,P)` | `▯▯▯▯` |
| 4 | `four-hero-left` | `row[2:1](L, col[1:1:1](L,L,L))` ⚖ | `■ ▭/▭/▭` |
| 4 | `four-hero-right` | `row[1:2](col[1:1:1](L,L,L), L)` ⚖ | `▭/▭/▭ ■` |
| 4 | `four-one-over-three` | `col[3:2](L, row[1:1:1](L,L,L))` ⚖ | `▭ / ▭▭▭` |
| 5 | `five-two-over-three` | `col[1:1](row[1:1](L,L), row[1:1:1](P,P,P))` | `▭▭ / ▯▯▯` |
| 6 | `six-grid-3x2` | `col[1:1](row[1:1:1](L,L,L), row[1:1:1](L,L,L))` | `▭▭▭ / ▭▭▭` |

⚖ = declares a `Balance` range. Orientations only matter under a ratio format.

## 7. Authority & API

The **composition is the source of truth** whenever `detached = false`. `PUT /artworks/{id}/document`
re-solves server-side and **overwrites** the slot rects, keeping `photo_id`, crop, bands, shadow and lock from
the payload and re-fitting any crop whose rect moved (§4.1). A client bug can therefore never persist a wrong
rect, and no new error code is needed — the two solvers being identical (conformance) makes the overwrite a
no-op in practice.

Changes:

- `domain/document.py`: optional `Composition` model + the validation of §2.
- `domain/composition.py` (new, pure) and its TS mirror; `conformance/geometry/composition*.json`.
- `assets/presets/recipes.json` (stable ids, no `builtin-` prefix — they are not user-editable templates).
- `GET /api/v1/recipes` → the catalogue, so the client solves and draws schemas from one source. The
  conformance script reads the same file from disk.
- `POST /artworks` accepts `composition: { recipe?, format?, … }` instead of `layout_id`; with neither, it
  defaults to the first recipe for the photo count, `original` for 1 photo and `fill` above.
- `services/artworks.py`: re-solve on save; `templates.build_document` gains a composition path.
- `make gen-api` in the same change (invariant 6). No DB migration (the document is JSON), no renderer change,
  so **no `RENDERER_VERSION` bump and no golden update**.

Today's `assets/presets/layouts.json` and the layout-template code stay untouched and keep serving the beta
editor; Phase 8 rewrites layout templates around recipes (a saved layout becomes recipe + parameters).

## 8. Tests

- `tests/unit/test_composition.py`: cells tile `A` exactly with exact gutters (Fill); every cell hits the
  target aspect within 1 px (ratio); the block is centred; `balance` moves the split monotonically; borders
  shift the footprint, not the aspect; `MIN_CELL` clamping is total; crop preservation keeps the centre.
- `tests/unit/test_conformance.py`: a `CASES` entry per recipe × {fill, 3:2} × {no border, 24 px border} ×
  {caption none, below}, fixtures regenerated and the expected values checked by hand (the Gotchas rule).
- `tests/api/test_artworks.py`: `POST` with a composition; `PUT` with deliberately wrong rects → stored rects
  are the solved ones; a detached document is stored verbatim; re-apply clears the flag.
- Golden: none (no renderer change). One new render smoke test through an existing golden document is enough.
- Browser (soft, §13.6): build a 3-photo hero composition, drag both sliders, switch format to 3:2, reframe a
  photo, swap two photos, then check the **saved document** through the API — not screenshots.

## 9. Decisions taken (2026-09-21, with the user)

Model in the document · split-tree recipes + one solver · ratio ⇒ cells take the format, block centred, outer
is a minimum · orientation declared per cell by the recipe · 2 margin sliders expandable to 4 · one page with a
mode switch, Simple default · detach keeps the parameters and disables the sliders · Simple also owns reframe,
swap, background/border and captions · photos drive the count · rich for 2–4, one default for 5–6 · `Fill` +
ratio chips + custom, `Original` for a single photo only · Balance only in Fill mode · server re-solves and
overwrites · Phase 7, templates shift to Phase 8.

## 10. Open points

- The caption band factor (1.5 × size) is a guess; check it against a real render before fixing it in
  conformance.
- `settings.artwork_defaults` still names a style + layout; it should name a style + recipe + format. Left for
  Phase 8 with the rest of the template work.
- Mirrored variants (`*-hero-left` / `*-hero-right`) are separate entries. If the picker gets long, a `⇄`
  flip toggle on the recipe would halve it.
