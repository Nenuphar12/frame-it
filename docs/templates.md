# Templates: frame styles & layouts (Phase 8)

> Spec for `PLAN.md` §14 Phase 8. Status: **implemented** (2026-09-23).
> Companion specs: `simple-editor.md` (the `composition` block a layout stores), `artwork-document.md`,
> `data-model.md` (`frame_styles`, `layouts`, `artworks.origin_*`).

## 1. Why

Phase 7 made every artwork parametric: a recipe plus a handful of numbers. That made the old
layout template — a list of absolute rects mapped into the mat — both redundant and wrong: it could
not express a format, a border or a caption band, and it fought the solver for ownership of the
slot rects. This phase rebuilds layouts on top of the composition block and gives both kinds of
template the management they never had (create, edit, duplicate, delete, export, import), plus the
one operation that makes templates worth having: **push update**.

Two kinds, deliberately independent (`PLAN.md` §4):

| | holds | owns in the document |
|---|---|---|
| **Frame style** | mat, margins, slot decorations, caption typography, the frame's shadow | `mat`, each slot's `shadow`, the border (flat or bevelled), the captions' font/size/colour, `edge_shadow` |
| **Layout** | a recipe and its parameters | `composition` (recipe, balance, weights, outer, gutter, format, cell formats, border, caption side and alignment) |

## 2. A layout is a recipe and its parameters

`domain/templates.LayoutDocument` is the `composition` block of `simple-editor.md` §2 **minus what
belongs to one artwork**: the caption's *text* and `detached`. What is left is exactly the set of
parameters the Simple panel edits:

```jsonc
{
  "recipe": "two-side-by-side",     // id from the bundled catalogue
  "balance": null,                   // Fill only, the recipe's range
  "weights": [],                     // per-split proportions (simple-editor.md §3.4); must fit
                                     // the recipe's splits, or the layout is `invalid_template`
  "outer":  { "x": 220, "y": 200 },
  "gutter": { "x": 100, "y": 100 },
  "format": "1:1",
  "cell_formats": [],
  "border": { "width": 18, "color": "#FFFFFF" },   // null = no border
  "caption_place": "below",          // the side; the words are the artwork's
  "caption_align": "center"          // left | center | right, against the block's printed edge
}
```

`layouts.slot_count` is the recipe's cell count, so "does this layout fit this selection?" is one
integer comparison. `LayoutDocument.block(text)` turns a layout into a composition and
`LayoutDocument.of(block)` does the reverse — that pair is all "apply" and "save as" need.

**Migration.** The stored documents had the old shape, so `0004_parametric_layouts` deletes every
layout row (they were all built-ins: there was no layout CRUD before this phase), clears
`artworks.origin_layout_id/revision` — they pointed at layouts that no longer exist and would have
lit up a bogus *outdated* badge — and drops the `artwork_defaults` setting, which changes shape in
§5. The built-ins are re-seeded at startup from `assets/presets/layouts.json`.

## 3. Applying a template — `restyle` and `relayout`

Both are PURE and **mirrored**: `domain/templates.py` ↔ `frontend/src/editor/core/templates.ts`,
pinned by `conformance/geometry/templates.json` (16 whole-document cases). They have to agree field
by field, because the editor applies a template to the working document and the server applies the
same one during a push update.

- **`restyle(doc, style, recipe, sizes)`** — mat, each slot's shadow, the captions' typography, and
  the band. The style's `margins` are deliberately **not** applied: under a block the margins are
  derived (`simple-editor.md` §3.7), and re-dressing must never move a photo the user placed. While
  a block is attached the band becomes `composition.border` (the block owns `bands`) and the
  document is re-solved; a hand-built or detached document takes the bands directly. A document with
  no caption yet is solved with the *style's* typography, so a caption typed later is the style's.
- **`relayout(doc, layout, recipe, sizes, caption)`** — the layout's block replaces the artwork's,
  carrying the artwork's caption text across, then `apply` re-solves. A detached artwork is
  re-attached: picking a layout is an explicit "lay this out for me", the same move as §5's
  *Re-apply layout* with someone else's parameters.
- **`style_of_document` / `layout_of_document`** — "Save as style" and "Save as layout". The style
  reads the mat, the first slot's shadow, the border (from the block while attached, from the slot's
  bands otherwise) and the first caption's typography; the layout is `LayoutDocument.of(block)` and
  is refused (`artwork_detached`) when the slots were placed by hand.

**Layout first, then the look.** When both are applied at once, the layout is applied first: both
own `composition.border`, and the style is what the user sees. Same reason `POST /artworks` lets the
style's band fill in the block's border when the composition does not name one.

## 4. Creating an artwork from a layout

`POST /artworks` with a `layout_id` is now the parametric path like any other: the layout's block
goes into the document, `composition.apply` writes the geometry, and the artwork records
`origin_layout_id` + `origin_layout_revision`. Fewer photos than cells is allowed (the rest are
placeholders); more is `422 layout_slot_count`. A `layout_id` together with an explicit
`composition` is `422 layout_and_composition`.

The pre-Phase-7 path — a hand-placed document with no block — is **gone**. A document without a
composition is still perfectly valid (legacy artworks, and anything the Advanced editor detaches),
it just is not something creation produces any more.

## 5. Origin, outdated, apply and push update

An artwork records the templates it came from (`origin_style_id/revision`,
`origin_layout_id/revision`). It is **outdated** when its recorded revision is below the template's
current one — editing a template bumps `revision` only when the *document* changes (compared **as
today's schema reads it**: a template stored before an optional field existed says the same thing
without that key, and re-seeding the built-ins after a schema addition is not an edit), so a rename
never makes anything outdated.

- `POST /artworks/{id}/apply-template` — re-dress and/or re-lay out one artwork server-side: a
  `pre_template_update` snapshot, then `restyle`/`relayout`, a new document version and the new
  origin. Used from outside the editor.
- Inside the editor, applying a style or a layout is a normal undoable edit (the mirrored functions
  run on the working document, autosaved like everything else) and a `PATCH /artworks/{id}` records
  the origin afterwards. The document never travels twice.
- `POST /{kind}/{id}/push-update/preview` walks the artworks made from the template and says what
  would change, applying nothing; `POST /{kind}/{id}/push-update` does it for real, snapshotting
  each artwork first — which is what makes the whole operation undoable, artwork by artwork, from
  the history. A layout skips an artwork holding another number of photos (`slot_count`) or one whose
  slots were placed by hand (`detached`): re-solving it would throw that work away.

`settings.artwork_defaults` is now `{style_id, recipe_id, format}` — a style, a recipe and a format
rather than a style and a layout. `recipe_id` and `format` may be `null`, meaning *follow the
photos*: the first catalogue entry for the number of photos selected, `original` for one photo and
`fill` above. A default recipe that does not match the selection is ignored the same way.

## 6. Template files

`.tfstyle.json` / `.tflayout.json`, both `{kind, version, name, document}` with `version: 1` and
`kind` one of `tfstyle` / `tflayout`. Export is `GET /{kind}/{id}/export` (the browser also builds
the same file from the row it already has, so the download needs no round trip); import is
`POST /{kind}/import`, which validates the document exactly as a hand-written one — a file of the
wrong kind is `wrong_template_kind`, an unknown version `unsupported_template_version`, a document
the model rejects `invalid_template`.

## 7. UI

- **Templates page** (`/templates`): tabs *Frame styles* / *Layouts*, cards with a preview the page
  draws itself — a layout is solved by the real solver at its own parameters (the trick of
  `simple-editor.md` §6.3, so a card cannot drift), a style is a mat with one framed photo on it.
  Per card: edit, duplicate, export, *Update artworks* and (for user templates) delete. Built-ins are
  read-only — duplicate one to get an editable copy.
- **Editing is a full-window dialog** (`Dialog size="full"`): the preview on the left, the settings
  in a 22 rem column on the **right** — the artwork editor's arrangement, so the two editors read
  the same way (remarks.md #1) — and the preview takes everything else (~1110×790 in a 1600×1000
  window, against ~256×144 before). The preview *is* the editor here: at dialog size you cannot tell
  a 12 px border from an 18 px one or see where a caption band lands. The markup keeps the controls
  first and flips the row (`lg:flex-row-reverse`), so the tab order still reaches them first and
  they stay on top when the dialog is too narrow for two columns.
- **A style says everything about a shadow that an artwork can** — type, blur, opacity, offsets and
  colour, through the same `ShadowFields` the editor's panels use. It offered only type and opacity
  before, which read as a limit of templates rather than of the dialog (remarks.md #2). The card
  draws the shadow with the renderer's own algorithm (`TemplatePreview`, §8.1 of the rendering
  spec): a real Gaussian at `σ = blur / 2`, cast by the *layer* (photo + band), recessed as the
  blurred complement of the layer clipped back inside it. The old hard rect peeking out from behind
  the photo showed nothing — a 6 px offset under a 12 px band is invisible, and recessed and raised
  looked identical. Its filter and gradient ids come from `useId`: they are document-wide, and the
  page draws one card per style.
- **Push update dialog**: the artworks the template made, each with *Outdated* / *Up to date* or the
  reason it will be skipped, the dry run's counts, and one button that applies it.
- **Editor**: the Simple panel's Layout section lists the saved layouts that fit the photo count and
  offers *Save as layout…*; the Background section offers *Save as style…*. Saving a template flushes
  the autosave first — the server reads the *stored* document.
- **Create dialog**: a saved layout that fits the selection can be picked instead of a bare recipe;
  choosing one sends `layout_id` and the artwork records it.
- **Settings**: the defaults of §5 (style, layout, format), with *Follow the photos* as the default
  for the last two.

## 8. Tests

- `tests/unit/test_domain.py`: building from a layout is the solver dressed by the style (including
  the style's band becoming the border, so the gutter stays a gap between printed edges), an empty
  cell stays a placeholder, `restyle` keeps the layout, `relayout` keeps the photos and the caption
  text, and the two "save as" readers round-trip.
- `tests/unit/test_conformance.py`: 16 `templates.json` cases — `restyle` × 2 styles × attached /
  detached × caption on / off, `restyle` without a recipe, `relayout` to two layouts and onto a
  detached artwork, and the two readers. Whole documents in, whole documents out, so a field the two
  languages disagree on shows up here rather than in the browser.
- `tests/api/test_templates.py`: CRUD and built-in protection, a layout's slot count following its
  recipe, creating from a layout (origin recorded), save-as in both directions (and `artwork_detached`),
  apply-template (snapshot, undo, `nothing_to_apply`), push update (editing a template changes nothing
  until pushed, then everything it owns and nothing else, undoable), the skip reasons, template files
  round-tripping, and admin-only access.
- Not covered by an automated test: the Templates page itself (no component tests in this project);
  driven in a browser instead — see `progress.md`.
