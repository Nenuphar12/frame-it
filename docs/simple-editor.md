# Simple editor & parametric compositions (Phase 7)

> Spec for `PLAN.md` §14 Phase 7. Status: **implemented** (2026-09-22) — the `composition` block,
> the mirrored solver, the recipe catalogue, `GET /recipes`, the server authority (`apply`,
> re-solve on save, `POST /artworks` with a composition), the **Simple panel** and the
> `[Simple] [Advanced ᴮᴱᵀᴬ]` switch with `detached` / Re-apply layout. Sections marked ✅ describe
> shipped code.
> Companion specs: `artwork-document.md` (document v1), `geometry-and-quality.md` (§7.x rules it reuses),
> `rendering-spec.md` (bands grow outward — §3 below depends on it).

## 1. Why

The Phase 6 editor is fully manual: every slot is placed by hand. It is precise but slow, and it gets worse as
soon as an artwork holds several photos. This phase adds a **parametric** way to build an artwork — pick a
configuration, move two sliders — and demotes the manual tools to a beta mode behind a switch.

Design goals, in order: a result that looks deliberate without any tweaking; two controls on the first screen;
nothing moves unless the user asked for it.

## 2. The `composition` block ✅

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
    "balance": 0.62,                   // share of the root split's first child; Fill only (§4.3)
                                       // null ⇒ the recipe's own default
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

- `recipe` must exist in the bundled catalogue, and its `count` must equal `len(slots)` — unless
  `detached`, where the slots are the truth and the count may have drifted (§5). Checked in
  `validate_references` (it needs the catalogue), so the problem codes are `unknown_recipe` /
  `recipe_slot_count` / `balance_out_of_range` / `balance_not_supported`.
- `balance` ∈ the recipe's declared range; ignored (and hidden) unless `format = "fill"`.
- `outer.x` ∈ [0, 800], `outer.y` ∈ [0, 450], `gutter.{x,y}` ∈ [0, 400]. Values that leave a cell narrower
  than `MIN_CELL = 40` px are clamped by the solver (§3.6), never rejected — an imported document must open.
- `format`: `"fill"`, `"original"` (only for a 1-cell recipe — a structural rule, so it is rejected
  by the document model itself), or a ratio `w:h` with `w, h` ∈ [1, 1000].
- `border.width` ∈ [1, 200] when present.

## 3. The solver ✅

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
  `auto` is reserved for the 1-cell recipe and means *the format turned the photo's way* — a
  portrait photo under `3:2` gets a 2:3 cell. (It cannot mean the photo's own aspect: that is what
  `original` is for, and it would make every ratio chip a no-op for a single photo.)
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
`1` for `square`, and `r` or `1/r` for `auto` following the photo's orientation (§3.1).
Under `format: "original"` every leaf takes the photo's own aspect; a leaf whose photo is unknown
falls back to `A`'s aspect, so a single empty cell fills the mat exactly (today's `fit_in_mat`).

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
`H = (3600 − 20)/2.25 = 1591.1`, `W = 3600`. Hero `2387 × 1592` at `(120, 284)`, each small cell
`1133 × 756`, block centred vertically with ~284 px above and below. The hero is 1592, not 1591:
**edges** are rounded, not sizes, and `284.4 … 1875.6` rounds to `284 … 1876`. That is also why a
cell's aspect is only exact to `1 + r` px of width (two rounded edges per side, §8).

### 3.6 Degenerate inputs

`MIN_CELL = 40` px on the photo rect. The panel bounds each slider by bisecting on the solver for the current
recipe and format, so a user cannot reach an over-constrained state. A document that arrives over-constrained
anyway (import, hand-edited JSON) is re-solved down a **fixed ladder**: the gutters scaled by
`10/10 … 0/10`, then `outer` by the same steps with the gutters at zero, stopping at the first attempt
where every cell clears `MIN_CELL`; the last attempt is returned with cells clamped to ≥ 1 px. A fixed
ladder rather than a bisection on purpose — the two solvers must agree bit for bit, and eleven divisions
by ten give the same doubles in both languages. The solver is total and never raises.

### 3.7 What the solver writes into the document ✅

`composition.apply(doc, recipe, photo_sizes, caption_style)` — pure and mirrored
(`applyComposition` in TS) — is the single implementation of this table: the server calls it on
every save and the editor will call it to preview. A document with no block, or a detached one, is
returned unchanged.

| field | value |
|---|---|
| `slots[i].rect` | cell *i*'s footprint deflated by `border.width` (`Cell.rect` is already that) |
| `slots[i].rotation` | `0` — parametric compositions never rotate (rotation stays an Advanced tool) |
| `slots[i].source.crop` | preserved, re-fitted (§4.1) |
| `slots[i].source.crop_ratio` | the cell's `ratio_label` |
| `slots[i].quality_lock` | `no_upscale`, downgraded to `free` when the photo cannot honour it (§7.6 rule) |
| `slots[i].bands` | `[border]` when set, else `[]` |
| `slots[i].shadow` | untouched (style default / Advanced) |
| `margins` | the effective insets of the block's footprint bbox (`block_margins`), `linked = false`, mirrors `false` |
| `placement` | `"manual"` |
| `captions` | one derived caption when `caption.place ≠ none` **and its text is not blank**: `x = 1920`, `anchor = "middle"`, baseline `y` inside the reserved band; font/weight/size/colour from the style's `caption_defaults` |

Writing `margins` back keeps the Advanced panels and every existing helper reading a truthful document.

Three rules the table leaves implicit, decided while implementing:

- **Baseline.** The reserved band (§3.3) holds the gutter on the block's side and a line of
  `CAPTION_BAND_FACTOR × size`; the baseline sits `CAPTION_BASELINE_FACTOR × size = 1.05 × size`
  below that line's top — leading shared above and below, plus a typical ascent. A pure number,
  like the band, so both solvers agree without font metrics. It is computed from the **nominal**
  `outer`: when an over-constrained document makes the solver relax (§3.6) the block moves and the
  caption stays where the parameters asked.
- **Typography is the document's, the text is the block's.** `caption.text` and `caption.place`
  live in the composition; font, weight, size, colour and letter-spacing come from the document's
  existing caption (so anything the user changed survives a re-solve), or from the style's
  `caption_defaults` when there is none — `caption_style_of` / `captionStyleOf`. The derived
  caption keeps the existing caption's id, else takes `DERIVED_CAPTION_ID`.
- **An empty slot stays a placeholder**: crop = the cell, `crop_ratio = "free"`, lock `free`.
  Filling it takes `no_upscale` back, exactly as in the Advanced editor.

`refit_crop` derives the crop's **height from its width and the target ratio**, never by scaling
the largest crop's height: rounding two independent sides can land just outside `aspect_consistent`
and the server would reject its own output (invariant 11).

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

## 5. Detaching ✅

The Advanced tools can do things the recipe cannot express (rotation, free placement, per-slot decorations).
The first such edit sets `composition.detached = true`:

- the slots become the truth; the block stays as **memory** of the last parameters;
- Simple mode disables its controls and shows a banner with **Re-apply layout** — one confirmed, undoable
  action that re-solves from the remembered parameters and clears the flag;
- the operation is a normal `store.edit()` patch, so `⌘Z` restores the hand-made geometry.

Edits that do **not** detach: reframing inside a cell, background, border, caption text, photo swap — Simple
owns those and they round-trip through the block.

The rule the code applies is mechanical: **an edit detaches exactly when `apply` would overwrite
it** (§3.7's table). So moving, resizing or rotating a slot, its bands, its lock, its crop ratio,
the margins, the placement and a caption's *position* all detach, while a shadow, the mat and a
caption's *typography* do not — `apply` leaves those alone, so they survive the next solve and must
not cost the user their layout link. Three edits are re-solved instead of detaching, because the
block can express them: orienting a photo (90°/flip changes the aspect a `original`/`auto` cell
follows), re-ordering the slots (the array order *is* the cell assignment, so it reads as a swap)
and adding or removing a photo (§4.4).

A caption's text is the one field the panel and the canvas share: typed on the canvas it is written
into `composition.caption.text`, not just onto the caption, or the next solve would take it back.

## 6. UI

### 6.1 Mode switch ✅

`/artworks/:id/edit` keeps one page. A `[Simple] [Advanced ᴮᴱᵀᴬ]` switch sits in the header; **Simple is the
default** for every artwork, including those without a `composition` (which show the picker instead of the
sliders). Advanced shows today's panel stack under a light warning strip: *Advanced tools are beta — free-form
edits drop the layout link.* The toggle is registered through `useRegisterCommands` (invariant 10), no default
shortcut. The canvas, undo/redo, autosave, review queue, TV preview and loupe are shared by both modes.

The canvas is shared but not identical: in Simple the stage runs the **crop** gesture, so dragging a
photo reframes it inside its fixed cell and the transform handles are never offered (`handleAt`
returns nothing unless the select tool is active). The select/crop toggle itself is an Advanced
control and is hidden in Simple, which has only one gesture to offer.

### 6.2 The Simple panel ✅

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

Decided while implementing (stage 3):

- **A hand-built artwork shows the picker alone** and picking a layout *attaches* a block
  (`attachComposition`): the mat, the photos and their order are kept, and a caption the artwork
  already had moves into the block — the block owns the captions from then on (§3.7), so leaving it
  behind would delete the user's text.
- **The slider bounds are client-only** (`editor/core/bounds.ts`, like `snapping.ts`): the server
  needs no such rule because the solver is total. The bisection runs on `solve_strict` — one
  attempt, no ladder — because `solve` would answer "roomy" for an over-constrained value by
  quietly laying the block out with *other* gutters. `solve_strict` and `roomy` are mirrored and
  pinned by conformance like everything else in that module.
- **Reframing turns the lock off.** Under `no_upscale` the constraint solver shrinks the *slot* as
  soon as the crop gets smaller than it (§7.3) — which would fight the cell. A reframe inside a
  cell therefore zooms with the lock off and restores §3.7's lock afterwards (`relock`), so the
  rect belongs to the composition at all times.
- **Balance is clamped when the recipe changes.** The ranges differ between recipes
  (`hero-left` is 0.40–0.75, `hero-right` 0.25–0.60), so carrying the value over unclamped builds a
  document the server rejects with `balance_out_of_range` — `balanceFor` clamps it instead.
- **The photo count keeps the block valid.** A slot added or removed in the Advanced editor
  re-picks the recipe (§4.4, `recipeFollowsPhotoCount`); beyond the catalogue (7 photos and up) the
  block detaches, which is also what stops the server rejecting the save with `recipe_slot_count`.

### 6.3 Picker schemas ✅

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

> ✅ Both halves are in: stage 1 the catalogue (`domain/composition.py` + its TS mirror,
> `assets/presets/recipes.json`, `services/recipes.py`, `GET /api/v1/recipes`), stage 2 the
> authority below (2026-09-22).

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
  Passing both is `422 layout_and_composition`; the other codes are `unknown_recipe`,
  `recipe_slot_count` and `no_recipe` (no catalogue entry holds that many photos). An explicit
  `layout_id` still builds a Phase 6 document with **no** block — that is how the Advanced editor
  and today's create dialog keep working. `settings.artwork_defaults.layout_id` therefore no longer
  picks the default for a composition-created artwork (§10: it should name a recipe, Phase 8).
- `services/artworks.py`: `validated()` parses, checks references, then `resolved()` re-solves, so
  every write path (`PUT document`, snapshot restore) goes through the same authority.
  `templates.build_composition_document` builds the skeleton a new artwork starts from — whole
  photos fitted in the canvas, which `apply` turns into centred cover crops (zoom 1, §4.1).
- `make gen-api` in the same change (invariant 6). No DB migration (the document is JSON), no renderer change,
  so **no `RENDERER_VERSION` bump and no golden update**.

Today's `assets/presets/layouts.json` and the layout-template code stay untouched and keep serving the beta
editor; Phase 8 rewrites layout templates around recipes (a saved layout becomes recipe + parameters).

## 8. Tests

- ✅ `tests/unit/test_composition.py` (152 tests): cells tile `A` exactly with exact gutters (Fill);
  every cell hits the target aspect to within `1 + r` px of width — both edges of a side are rounded,
  so `w` and `h` are each within 1 px of the ideal rect and `|w − a·h| ≤ 1 + a`; the block is centred;
  `balance` moves the split monotonically and is inert under a ratio; borders shift the footprint, not
  the aspect; cells never overlap and stay on the canvas; the solver is total at every slider extreme;
  crop preservation keeps the centre and the zoom.
- ✅ `tests/unit/test_composition.py` also covers `apply` (§3.7): the cells land in the slots for
  every recipe × format, the framing and the photo of each slot survive, a lock the photo cannot
  honour is downgraded, an empty slot stays a placeholder, the border becomes a band, the caption
  is derived (and dropped when blank), a detached document comes back untouched — plus the
  property that matters most: **an applied document re-validates**, so the server never writes one
  it would reject (invariant 11).
- ✅ `tests/unit/test_conformance.py`: 203 composition cases — one per recipe × {fill, 3:2} ×
  {no border, 24 px border} × {caption none, below}, plus the balance ends, the `original`/`auto`
  paths, an over-constrained document and the write-back helpers. 17 of them run `apply` on a whole
  document (border, caption above/below, an empty slot, an unknown photo, a 90° orient, a detached
  block) — document in, document out, so the two languages agree field by field, not just on rects.
  Both solvers agree on all of them.
- `tests/api/test_artworks.py`: ✅ the catalogue endpoint, a document carrying a composition, the
  four catalogue problem codes, `PUT` with deliberately wrong rects → the stored rects are the
  solved ones and the reframe survives, a detached document stored verbatim, creating from a
  composition (border, caption, 3:2 cells) and the four `POST` problem codes; ⏳ (stage 4) re-apply
  clears the flag.
- Golden: none (no renderer change). One new render smoke test through an existing golden document is enough.
- ✅ Browser (soft, §13.6, done 2026-09-22 over CDP): a 3-photo hero composition, both sliders
  dragged, format switched to 3:2, a photo reframed and two swapped, a border added and a caption
  typed — each checked against the **saved document** through the API, not screenshots. The
  effective-outer readout the panel showed (`→ 373`) is the margin the server stored, which is the
  AC "the server-stored rects equal the ones the editor previewed".

## 9. Decisions taken (2026-09-21, with the user)

Model in the document · split-tree recipes + one solver · ratio ⇒ cells take the format, block centred, outer
is a minimum · orientation declared per cell by the recipe · 2 margin sliders expandable to 4 · one page with a
mode switch, Simple default · detach keeps the parameters and disables the sliders · Simple also owns reframe,
swap, background/border and captions · photos drive the count · rich for 2–4, one default for 5–6 · `Fill` +
ratio chips + custom, `Original` for a single photo only · Balance only in Fill mode · server re-solves and
overwrites · Phase 7, templates shift to Phase 8.

## 10. Open points

- The caption band factor (1.5 × size) is a guess **now pinned by conformance**; checking it against a
  real render belongs to stage 3, when a composition actually derives a caption. Changing it then means
  regenerating the fixtures.
- `settings.artwork_defaults` still names a style + layout; it should name a style + recipe + format. Left for
  Phase 8 with the rest of the template work.
- Mirrored variants (`*-hero-left` / `*-hero-right`) are separate entries. If the picker gets long, a `⇄`
  flip toggle on the recipe would halve it.
