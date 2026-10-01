# Gotchas

> Hard-won facts that are not obvious from reading the code, grouped by what you are touching.
> **`AGENTS.md` keeps the cross-cutting ones**; these are the rest. Read the section for the
> subsystem you are changing *before* you change it — every entry here is something that already
> cost someone a debugging session.
>
> Add a gotcha in the same change as the code that taught it to you, in the section it belongs to.

## Tooling, build & tests

These bite whatever you are working on.

- TanStack Virtual triggers the React Compiler lint `incompatible-library`: suppressed in `PhotoGrid.tsx` on purpose.
- `Settings.allowed_hosts` must include the test host (`testserver`) in tests; production adds LAN IP/hostname.
- Registering commands with unstable dependencies used to cause a render loop; `useRegisterCommands` now keys
  on ids/shortcuts and calls the latest `run` via a ref — keep it that way.
- Two libraries in a test are two apps over **two data dirs** (`app_factory(data_dir=…)`), or you
  are importing an archive into the library that wrote it.

## Uploads, phones & LocalSend

`docs/localsend.md`, `docs/research/phone-uploads.md`.

- Resuming an upload without `meta` must keep the metadata of the original session (regression-tested).
- Android (any browser picker) zeroes GPS bytes in place, and the photo picker renames files to MediaStore
  ids (`1000125423.jpg`): never expect `gps_lat` from a phone web upload. A later copy with GPS/name is
  merged into the existing photo by content fingerprint (`docs/data-model.md`).
- LocalSend app: files without a token are hidden from its transfer list, and a `prepare-upload` accepting
  no file (204) shows nothing at all; 403/409/429 show fixed texts, other statuses an "Error ⓘ" — we avoid
  all of them for already-sent photos (`docs/localsend.md` "Already-sent photos").
- The LocalSend certificate (`<data_dir>/localsend/`) is pinned by phones: never regenerate it casually.
  Tests never bind 53317 (`start_workers=False`; runner tests use a free port and `localsend_discovery=False`).

## Imaging & rendering

`docs/rendering-spec.md`.

- libvips gotchas: trigonometric ops use **degrees**; `gaussblur` default `min_ampl=0.2` clips (use 0.005);
  `Image.text` is cropped to ink (offsets in `xoffset`/`yoffset`); `affine` pixel centres need the ±0.5
  `idx/odx` offsets (see `_rotate`); `find_load` is not exposed by pyvips (sniff instead).
- A render holds **every decoded original at once** (pyvips is lazy: nothing is released until the image is
  written, and the 512 MB LRU bounds what is kept *between* renders). Measured: 9 slots of 24 MP peak at
  2.3 GB. `MAX_RENDER_PIXELS` refuses more, counted from the file headers, as `render_too_large`.
- Canvas shadows allocate a surface covering the shape **and** its shadow: never draw the inner-shadow ring far
  away (S3's trick froze the tab). It is drawn around the layer and clipped — `docs/rendering-spec.md` §8.2.
- Konva does not put a `Text` node's `y` on the line top (it translates by `(ascent − descent) / 2 +
  lineHeight / 2`, draws `alphabetic`, and its font shorthand includes the weight): caption placement goes
  through `editor/canvas/fonts.ts`, which replicates both (`docs/research/render-parity.md`).

## The editor & its canvas

`docs/PLAN.md` §11, `frontend/src/editor/`.

- The editor's canvas gestures all go through **one** pointer pipeline in `EditorStage` (mode in a ref,
  flushed per animation frame). Handles are drawn by `SelectionOverlay` but hit-tested in `hit.ts` — they
  are not listening Konva nodes.
- Konva binds its mouse listeners **below** the container div, so a synthetic event must go to the
  `<canvas>` (or Konva's content div), never the outer `[data-tool]` element — and tinykeys drops a
  `KeyboardEvent` without a `code`, so synthetic shortcuts need `{ key, code }`. Both cost an E2E session.
- Radix layers see `Escape` in the **capture** phase on the document while tinykeys listens on `window`
  (bubble): a layer must `stopPropagation` in `onEscapeKeyDown`, or `Escape` closes the popover *and* runs
  the page's own `Escape` command.
- Radix focuses the first tabbable element of a dialog, which is the close cross: a dialog whose `Enter`
  should confirm passes `onOpenAutoFocus` and focuses its submit button (`CreateArtworksDialog`).
- Query results are new objects on every render: never feed them straight into a store (`openArtwork` writes
  `sizes` only when a photo id is actually new, or the editor re-renders in a loop).
- The React Compiler lint forbids `setState` in an effect body: derive the value during render instead (the
  stage view falls back to `fit()`, image/texture hooks read a module cache and only `setState` in the async
  callback).
- Editor number fields keep the typed text while focused (`panels/Controls.tsx`) and never snap it — the §7.5
  tolerance is 8 *screen* px, which swallowed typed margins. Sliders still snap.
- A **shadow** is edited in three places through one `ShadowFields`, and in Simple it dresses **every**
  slot (`setShadowEverywhere`): the block never writes `shadow` (§3.7), so it neither detaches nor
  re-solves. A preview needs a real filter (an offset rect hides under the band, and inner/drop then
  look identical); SVG `filter`/gradient ids are document-wide, so prefix them with `useId`.
- An in-app HTML drag must stamp itself (`shared/dnd.ts`): dragging a photo chip is dragging an
  `<img>`, which Chrome also offers to the page as a *file*, so the window-wide upload overlay lit
  up on every cell swap. `hasFiles` ignores a drag carrying one of our MIME types.
- A `<select>` left transparent gets a native popup Chrome paints from the *control's* colours —
  light popup, near-white options, visible only on hover. `styles.css` sets `select`/`option`
  colours at element level as the floor; utilities on a specific select still win.

## Geometry, crops & quality

`docs/geometry-and-quality.md`.

- A crop with width **and** height rounded independently can fall just outside `aspect_consistent`
  (the tolerance is exactly two roundings' budget). `refit_crop` derives the height from the width and
  the target ratio: the server must never re-solve a document into one it would reject (invariant 11).
- `zoom_crop` derives the crop's height from its width and the **rect's** aspect: scaling the sides on
  their own drifts, and a drifted crop makes `resize_crop` resize the *slot* ("zoom out and the frame
  changes size"). Both halves matter — the mirrored rule, and the editor routing the **wheel** through
  the same bounded 1×–8× scale as the slider.
- Under `fit_in_mat` + `native` the margins **are** the crop, in both directions: deriving the crop only
  when it overflowed made margins one-way, the photo never growing back (`docs/geometry-and-quality.md` §7.4).
- A slot without a photo is a placeholder: `quality_lock = free`, crop = its rect. Filling it takes
  `no_upscale` back, or an emptied slot would silently allow upscaling.
- "Same size" fits each slot *inside* the reference box: the solver's `resize_slot` has **cover** semantics
  (§7.3), so asking for the reference size directly makes the other slots bigger than it.

## Compositions & the solver (phase 7)

`docs/simple-editor.md`.

- The composition solver rounds **edges**, never sizes: a 3:2 cell can come out 2387×1592, and a cell's
  aspect is only exact to `1 + r` px of width. Assert `|w − a·h| ≤ 1 + a`, not `≤ 1`.
- The solver's over-constrained recovery is a **fixed ladder** (gutters ×10/10…0/10, then `outer`), not
  a bisection: both languages must agree bit for bit, and `i/10` gives the same doubles. Keep the recipe
  catalogue the *one* source both read (`conformance.ts` loads `presets/recipes.json` off disk).
- **An edit detaches a composition exactly when `apply` would overwrite it** (§3.7's table): slot geometry,
  bands, lock, crop ratio, margins, placement and a caption's position do; the shadow, the mat and a
  caption's typography do not. Orienting a photo, re-ordering slots and changing the photo count
  **re-solve**. Put any new editor action on one of those three lists.
- A caption's text belongs to the block: an edit on the canvas writes `composition.caption.text`,
  not just the caption, or the next solve takes it back.
- The Simple panel's sliders bisect on **`solve_strict`**, never on `solve`: the relaxation ladder
  answers "roomy" for an over-constrained value by laying the block out with *other* gutters, so a
  bisection on `solve` silently returns a bound that does not hold.
- A reframe inside a cell must zoom with the quality lock **off** (`relock` puts §3.7's lock back):
  under `no_upscale` the constraint solver shrinks the *slot* as soon as the crop gets smaller than
  it (§7.3), which fights the composition for ownership of the rect.
- Attaching a composition to a hand-built artwork moves its caption's text into the block: from
  then on the block owns `captions` (§3.7), so anything left behind is deleted by the next solve.
  Same reflex for any new field the block starts owning.
- Adding or removing a slot while a block is attached must re-pick the recipe
  (`recipeFollowsPhotoCount`) or the save fails with `recipe_slot_count`: the count comes from the
  photos, and past 6 photos the block detaches.
- `composition.apply` (↔ `applyComposition`) is the **only** writer of `docs/simple-editor.md` §3.7:
  the server calls it on every save, the editor will call it to preview. Change it in both languages
  and add a `composition_apply` conformance case — those fixtures compare whole documents, so a field
  the two sides disagree on shows up there rather than in the browser.
- **A ratio format carries its orientation**: `4:3` and `3:4` are different formats and the cells
  take the ratio as written. Only `auto` (the 1-cell recipe) turns the landscape form the photo's
  way. The recipes' `landscape`/`portrait` cell kinds are inert as a result.
- `composition.cell_formats` overrides the format cell by cell (`null` inherits, `original` = the photo's
  own aspect, never `fill`). `format: "original"` works at **any** photo count.
- A recipe cell of kind `auto` means *the format turned the photo's way* (portrait photo + `3:2` → a 2:3
  cell), **not** the photo's own aspect — that is what the `original` format is for. Reading §3.5 the
  other way makes every ratio chip a no-op for a single photo.

## Templates (phase 8)

`docs/templates.md`.

- **Every new artwork is parametric** (Phase 8): a `layout_id` names a saved *recipe + parameters* and is
  recorded as `origin_layout_id`; fewer photos than cells leaves placeholders, more is `layout_slot_count`.
  The hand-placed creation path is gone — a document without a block only comes from detaching.
  `settings.artwork_defaults` is `{style_id, recipe_id, format}` (the last two nullable).
- **A template is copied on apply**; only a push update changes an existing artwork, snapshotting each
  one (`pre_template_update`) first — that snapshot *is* the undo. `restyle`/`relayout` are mirrored, so
  editor and server apply the same template and a drift shows up as a fixture diff.
- **The style's band and the layout's border are the same field** (`composition.border`, since the
  block owns `bands`): applying both applies the *layout first*, so the style wins, and
  `build_composition_document` lets the style's band fill in a border the composition does not name.
  A layout whose `border` is `null` means *no border*, not *unspecified*.
- **`restyle` never writes the style's `margins`**: under a block the margins are derived (§3.7) and
  re-dressing must not move a photo the user placed. A style's margins only matter to a hand-built
  document and to its own card preview.

## Organization: filters, collections, search, trash (phase 9)

`docs/organization.md`.

- **A filter is a value**: the chip bar, a smart collection's stored AST and `POST /artworks/query`
  carry the same object. `domain/filters.py` says what a filter may *mean*, `services/library.py`
  is the only place that knows how it reaches the schema — add a field to both, never to one.
  `taken_at` and `place` are the only clauses that leave the `artworks` table (EXISTS over
  `artwork_photos`): an artwork is "from Kyoto" when one of its photos is.
- The FTS index is written **inside the transaction that changed the row** (`services/search.py`):
  any new writer of a title, a tag link, a place or a collection name calls `index_*`, or search
  goes quietly stale. It stays disposable — `reindex_all` rebuilds it and startup does that when
  the table is empty. User text never reaches FTS5 raw: `match_query` keeps tokens only.
- **What is deleted together is restored together**: one `trash_batch_id` per gesture. Trashing a
  photo takes a cascade — `trash_artworks` (same batch) or `empty_slots`, which re-saves each
  document through `artworks.validated` so an attached composition re-solves, snapshots it
  `pre_trash`, and leaves the placeholder a new artwork would have (`quality_lock = free`).
- A collection's `position` is a REAL among its siblings (and a manual item's among the
  collection's items): insert at the midpoint, renumber the whole list only when the gap falls
  under `1e-9`. Cycles, depth (8) and self-referencing smart filters are refused by the *server* —
  the tree never tries to guess.
- A **bare letter and a chord starting with it** (`c` vs `g c`) are two `tinykeys` instances that
  each match on their own, so both used to fire. `app/commands.ts` keeps one capture-phase listener
  that arms on a chord prefix; single-key bindings stand down for the next keystroke. Register any
  new single-key shortcut through the registry and it is covered. A **modal** also has to take the
  page's keys away while it is open (the viewer passes `undefined` shortcuts, `ArtworksPage.key()`).
- Manual order (`position`) belongs to **one** collection: `manual` sort + `include_nested` is a
  422 (`manual_sort_nested`), never a silent fallback, and `nested_count` counts *distinct*
  artworks. A drop in the grid inserts before the target going backwards and **after** it going
  forwards, or dragging a card right asks for the place it already has.
- A collection is scoped through **`_in_collections`** — manual membership unioned with the filters
  of the smart collections among the ids — never a bare `collection_items IN (…)`, or a smart
  *sub*-collection contributes nothing (its artworks are matches, not rows). Smart membership is
  derived and read-only: `smart_collection_ids` is reported apart from `collection_ids`.
- Every grid of artworks takes its keyboard from **`useArtworkGridCommands`** so the three pages
  cannot drift; a page adds a key by passing a handler (the collection page's `Backspace`).

## Archive: export & import (phase 10)

`docs/archive-format.md`.

- An archive is **a ZIP anyone can open** — that is a requirement, not an accident: JSON + JSON
  Lines + the originals + a `sha256sum`-format `checksums.sha256`, schemas in
  `docs/schemas/archive/`. `domain/archive.py` is the one place that says which columns travel;
  add a field there, keep it inside that shape.
- **An import matches on meaning, not on ids**: a photo is its SHA-256 (a local copy *is* that
  photo, and a trashed one comes back), a tag is its name, a built-in template is never
  overwritten. Everything else is by id, and `identical` ignores every timestamp, the trash batch
  and `document_version` — a no-op save on one side is not a conflict.
- Every id an archive carries is rewritten through **one set of maps** (`archive_import.IdMaps`):
  a document's `photo_id`s, a collection's `parent_id`/`cover_artwork_id`, a **smart collection's
  filter** (`filters.remap_ids`) and `artwork_defaults.style_id`. A reference to a **built-in**
  template has no mapping and must survive as written — mapping it to `None` quietly loses the
  origin badge on every artwork (regression-tested). An imported document is otherwise stored
  **verbatim**: an import is a restore, not a client save, so the solver is not re-run over it.
- **A row is compared after translation *and* after migration** — `archive_import._translated` (used
  by the report and the apply pass) plus `archive.comparable`, which runs both documents through the
  schema. The same artwork in two libraries names the same photo under two ids, and a document
  stored before a field existed has no default where a parsed one does: either alone makes a
  re-import report every artwork as a conflict (measured: 23 of 30 on the dev library). Anything
  new holding a foreign key goes through `artwork_values` / `collection_values`.
- A render travels only while it is still the render this app would make: the manifest carries
  `render_key` (renderer + asset versions, `services/render.render_key`); a mismatch re-renders.

## Jobs, performance & error UX (phase 11)

`docs/security.md`, `docs/rendering-spec.md` §8.5–8.6.

- **Every artwork listing filters `deleted_at IS NULL` and then orders**, so an index that does not lead
  with `deleted_at` makes SQLite sort the whole table into a temp B-tree — 13 ms a page on 10k artworks,
  64 ms for `created_asc` (migration `0008`). A new sort order needs its own composite starting with
  `deleted_at`; check `EXPLAIN QUERY PLAN` shows no `TEMP B-TREE` and measure with `scripts/bench_library.py`.
- `retry_job` **commits before enqueuing**: `JobQueue.enqueue` opens its own session and SQLite has one
  writer, so enqueuing inside a request's `DbSession` deadlocks. Same reflex as `_changed` in `api/artworks.py`.
- A failure carries a **code**, never a sentence: `jobs.code` is a column (a traceback and a
  `PermanentJobError` are indistinguishable by shape), and `toast.problem`/`toast.error` pass the code so the
  component translates `errors.<code>` — a new code needs its string or the raw server text shows through.
  Dotted job kinds map `.` to `_` (`activity.kinds.archive_export`).
- A Tailwind utility is one class (0,1,0), so an element-level floor in `styles.css` loses to it: the
  control-boundary rule uses an attribute selector (`select[class]`, 0,1,1) to outrank ~90 `border-border`
  call sites without editing them.

## TV display (phase 12)

`docs/tv-display.md`, `docs/research/tv-display.md`.

- **No TV at hand? `THE_FRAME_V2_FAKE_TV=1`** routes every target, discovery and pairing to one
  in-memory `FakeTv` (three "foreign" photos, 0.8 s per upload). Its photos vanish on restart while
  the map in the database stays — after a restart the next push sees the map's rows as gone and
  re-uploads. Never commit a config with it on; it logs a warning at start.
- **Never drop a `display_target_items` row because the set changed.** A row means "we uploaded it
  and the TV still has it"; only a delete we made or the TV no longer listing it removes one. Each
  upload is recorded in **its own** transaction straight after the TV accepts it, so a push that dies
  half way does not roll back the record of what did reach the TV — otherwise those images come back
  as "photos this app did not send", offered for irreversible deletion.
- **Reuse only a tail in slideshow mode** (`plan_push`): new uploads are always the newest, so
  re-uploading a middle image means re-uploading everything before it, or the TV plays it out of
  order. "Don't change" has no order and may reuse anything.
- `_with_tv` **commits the TV's new address from its own session** when it follows a TV by MAC.
  SQLite has one writer: a caller must not have written in the request's session before calling it
  (same reflex as `retry_job`), and must `session.refresh(target)` afterwards to see the new host.
- `enqueue_push` stores `progress = queued` before the job runs, so **every** failure path of `push`
  — including `empty_set` before the TV is reached — must clear it, or the tray waits forever after a
  reload.

## Driving the app in a browser

`docs/PLAN.md` §13.6.

- CDP `Runtime.evaluate` with `returnByValue` serialises a **DOM element as `{}`** — falsy in Python,
  so a poll that returns the element never succeeds. Return `!!element` (or a string, a number, an
  array) from anything you wait on.

- Driving this app over CDP: each open tab holds an SSE connection, so **six tabs exhaust the
  per-origin pool** and the next one renders an empty page — close tabs between runs;
  openapi-fetch binds `globalThis.fetch` at `createClient` time, so patching `window.fetch` later
  intercepts nothing (read results back through the API); and dispatch a synthetic key **once**, on
  the focused element — dispatching on `body` *and* `window` makes tinykeys see every key twice.

## Documents & serialization

`docs/artwork-document.md`.

- `ArtworkDocument.schema_version` is serialized as `"schema"` (alias): dump with `canonical()`.
