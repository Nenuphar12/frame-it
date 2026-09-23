# Progress log

## 2026-09-16 — Phases 0–3

**Phase 0 (spikes)**: S1 decoding matrix done (`research/decoding.md`); S2 protocol + heuristics done, real
Android picker verification pending a device (`research/phone-uploads.md`); S4 hashing benchmark done on
desktop; S3 moved to the start of Phase 4 (needs the renderer).

**Phase 1 (foundations)**: uv/pnpm projects, settings, SQLite + Alembic (full schema), problem+json errors,
job queue, SSE broker, CLI, SPA serving, OpenAPI → TS types, i18n, themes, command palette + shortcuts,
Makefile, Dockerfile/compose (image not built here: no Docker daemon access), AGENTS.md, ADRs 0001–0006.

**Phase 2 (security & devices)**: localhost trust, setup code, QR pairing, roles, Host allowlist, CSRF guard,
security headers, rate limiting, device management UI, optional TLS settings.

**Phase 3 (ingest & library)**: resumable chunked uploads with dedupe and hash verification, ingest job
(sniff, probe, colour-managed proxies/thumbnails, EXIF, GeoNames reverse geocoding, quality warnings),
HEIC rejection, desktop drag & drop (files and folders), phone upload page with metadata, Photos grid
(virtualized, search, details drawer with tags), Inbox (selection, dismiss).

**Verification**: 74 backend tests; ruff, mypy strict, tsc, ESLint (0 errors), i18n check green; end-to-end
run of the built app: LAN pairing via QR link, chunked upload with interruption/resume, desktop drop upload
with live inbox update, role redirects, HEIC rejection.

**Bugs found and fixed during E2E**: upload metadata wiped on resume; command registration render loop;
capture times shifted by the browser timezone; city districts ("Lyon 01") chosen as place names.

**2026-09-17 — real-device feedback**: Android zeroes GPS for browser uploads and the photo picker renames
files → `location_removed` warning and merge of later copies by content fingerprint (migration 0002,
`photo_hash_aliases`, backfill job); startup log shows the LAN URL; Docker image PATH fixed; fixed-size grid
thumbnails.

**2026-09-17 — LocalSend receiver** (ADR-0007, `docs/localsend.md`): protocol v2 receive side on TLS port 53317
with multicast discovery, admin approval of new devices (dialog + Devices section), hand-off to ingest.

## 2026-09-17 — Phase 4 (artwork domain & renderer)

**S3 spike** (`research/render-parity.md`): Canvas 2D vs pyvips in Chrome — shadows max diff 3/255 (σ = blur/2
confirmed), texture identical, rotated slots differ only on antialiased edges, caption ink boxes within ±2 px.

**Domain**: artwork document v1 (Pydantic, JSON Schemas in `docs/schemas/`, precise 422 errors, migrations
hook), geometry/quality/placement mirrored in TypeScript (`frontend/src/editor/core/`) and checked by 77 shared
fixtures (`pnpm conformance` + pytest), frame style/layout documents and `build_document`.

**Renderer** (`imaging/render.py`): mat + texture, bands, inner/drop shadows, exact rotation, captions (Pango,
bundled OFL fonts), PNG master + 4:4:4 JPEG + thumbnails, region renders, scaled renders. Parallel decoding made
the 9-slot collage 3.8 s (budget 6 s). Built-in presets: 6 frame styles, 7 layouts. Render cache + coalesced
render jobs + `artwork.rendered` SSE.

**API**: artworks CRUD-ish (create from photos + style + layout, `PUT document` with `If-Match`, patch, validate,
duplicate, trash, snapshots with restore, render/thumb endpoints), frame styles/layouts/fonts/textures (read),
`POST /render/region`.

**UI (review aid until the Phase 5 editor)**: Inbox "Create artworks" (style, layout, placement), Artworks page
(grid, filters) and full-screen viewer of the server render (favorite, ready/draft, duplicate, download, delete).

**After the user's review (2026-09-17)**: Photos page gained selection (click, Ctrl/Shift-click, `$mod+a`,
`Escape`, `i` details) and "Create artworks" (`n`, also in the details drawer) so any photo — including processed
ones — can get more artworks; Float mount preset has no band any more (seeding updates the built-in row; existing
artworks keep their document).

**Verification**: `make check` green (220 backend tests incl. 7 golden images, conformance, mypy, tsc, ESLint);
native 3840×2160 photo renders bit-identical to its decode; E2E on a copy of the dev library with real phone
photos (create 6 artworks, polaroid pile via API, viewer shortcuts, live updates).

**Known limits / follow-ups**: collections can only be listed (creation in Phase 9 — renumbered when the
simple editor became Phase 7), so the phone collection picker stays empty; trashed artworks cannot be
restored before Phase 9; no ESLint rule for literal JSX strings
yet; Docker image not rebuilt/tested with the fonts (Pango/fontconfig in the slim image); collage renders hold
all decoded originals in memory.

**LocalSend "already sent" handling (2026-09-17/18, user remark)**: re-sending a photo already in the library was
silent and confusing. Now nothing is transferred twice, the sender's app sees a plain successful transfer (no
error, no text message — both were tried and dropped as more confusing than helpful; when every offered photo is
already known the smallest one is transferred and dropped, because an app that is given no file to send shows no
transfer screen at all), and every received photo,
already sent or not, goes **back to the inbox** — the rule for all uploads, so re-sending is how you bring a
photo back (`photo_copies.receive_again`; a trashed one is restored). The web upload tray now mirrors LocalSend
transfers ("Already in your library — back in the inbox · from <device>"), including skipped and unsupported
files. Behaviour of the LocalSend app checked in its source (`docs/localsend.md` "Already-sent photos").
A photo coming back without being ingested publishes `photo.updated`, otherwise open pages only showed it after a
manual reload (user report). Verified: `make check`; TLS end-to-end runs against a live server with real photos
(including the SSE the browser receives). Not tried on a real phone.

## 2026-09-18 — Phase 5 (editor, single photo) — **partially verified, see "Open items"**

**Pure core (mirrored Python/TypeScript, 107 conformance cases, was 77)**: constraint solver
(`domain/constraints.py` ↔ `editor/core/constraints.ts`, §7.3) — slot resize with *cover* semantics and an
anchor, crop resize/pan/zoom, lock switching, crop-ratio switching; alternatives (`domain/alternatives.py` ↔
`alternatives.ts`, §7.6) returning ready-to-apply patches. Both keep the two document invariants (aspect
consistency and the quality lock) so the editor can never produce a document the server rejects — asserted for
every solver result in `tests/unit/test_constraints.py` (19 behaviour tests). Snapping (`snapping.ts`, §7.5) is
client-only (screen-pixel tolerance) but pure: the margin controls snap to the *quality point* (scale = 1).

**Backend additions**: photo palette (`imaging/palette.py`, k-means in OKLab on a 64×64 sample → dominant,
muted and complementary entries; deterministic, cached in `cache/palettes/`), swatches CRUD, curated mat
colours (`GET /presets/colors`), `GET/PUT /artwork-defaults` (default style/layout, Settings UI), font metrics
in `GET /fonts` so the editor places caption baselines exactly like the renderer. 6 new API tests.

**Editor** (`frontend/src/editor/`): Konva canvas (mat + tinted texture tile, bands, photo from the proxy in
oriented space, inner/drop shadows, zoom/pan, selection, margins guide, magenta snap guides), crop tool
(drag/wheel pan & zoom inside the slot), framing panel (placement, margins with linking, quality lock, crop
ratio, 90° turns/flip, rotation), style panel (mat colour + texture strength, bands ≤ 3, shadow), colour picker
with saved swatches/presets/photo palette, alternatives panel with per-option previews, loupe (server region
render), TV preview (fullscreen, 3 bezels, matte overlay), artwork sheet (title, tags suggested from the
photos, favourite, snapshots + "revert to when opened"), review queue (filmstrip, progress, validate & next,
skip, J/K), undo/redo on Immer patches (grouped per gesture, 200 steps), autosave (800 ms debounce, `If-Match`,
409 → keep mine / take theirs). Creating artworks from the Inbox or Photos now goes straight into the review
queue (`/editor/$artworkId?queue=…`).

**Bugs found and fixed during the browser E2E** (all three froze the tab — worth remembering):
1. *Render loop*: `openArtwork` rewrote `sizes` with a fresh object on every call while the photo query
   produced a new array on every render. Guarded, and the sizes map is now keyed on its values.
2. *One React render per mouse event*: crop dragging (and the loupe's pointer reporting) re-rendered the whole
   editor and redrew the canvas per event; the event queue outran the renderer. Both are now accumulated and
   flushed once per animation frame (`EditorStage`) — which is also what the 60 fps budget asks for.
3. *Inner shadow*: S3's "ring drawn 20 000 px away" makes the browser allocate a surface spanning the shape and
   its shadow. The ring is now drawn around the layer and clipped (`docs/research/render-parity.md` corrected).
Also: a 404 artwork left the editor spinning forever (now an error with a way back), and `Escape` in the TV
preview closed the preview *and* left the editor (the preview now captures the key).

**Verified**: `make check` green (281 backend tests, 107 conformance cases, mypy strict, ESLint, tsc, i18n).
In a real browser against a copy of the dev library (17 photos, 14 artworks): the editor opens an artwork,
margins re-place the slot live with the badge following (42 % → 32 %), lock switching applies and autosaves
(native keeps scale exactly 1 and pushes the change into the margins as §7.4 requires — the values matched a
hand-run of the pure functions), crop ratio 1:1 re-crops, crop dragging pans the photo, linen texture and the
recessed shadow render, and every change autosaves and is reloaded correctly.

**Open items when the session ended** — all closed on 2026-09-19, see below.

## 2026-09-19 — Phase 5 verification & sign-off

Driven in a real browser (production build served by the backend on trusted localhost, against a copy of the
dev library). Everything left open on 2026-09-18 was exercised; three bugs came out of it.

**The loupe is not broken.** The panel opens on `Z` and on the button, and the 512² server region appears
(the `POST /render/region` round trip is ~75 ms). What failed last session was the *screenshot tool*: the
Chrome extension's `Page.captureScreenshot` times out for as long as the loupe's blob image is on screen (the
page itself stays responsive — JS keeps answering), so the panel was there and invisible to the harness.
Same cause as "`computer.zoom` and fullscreen capture time out on this page": a tooling limit, not the app.
Related: a Konva canvas sometimes composites **black** in a captured screenshot while its pixels are correct
(verified by reading the canvas back with `getImageData`) — never conclude "the canvas is empty" from a
screenshot alone.

**Bugs found and fixed**:
1. *`Escape` in the colour popover left the editor.* Radix handles `Escape` in the capture phase on the
   document; the command registry (tinykeys) listens on `window` in the bubble phase, so both ran: the
   popover closed **and** the editor navigated to `/artworks`. The layers now swallow the key
   (`onEscapeKeyDown` → `stopPropagation`) in `shared/ui/Dialog`, `editor/panels/ColorField` and
   `features/artworks/ArtworkViewer`.
2. *Captions were drawn ≈ 14 TV px too high* (96 px font) and measured without their weight: the editor
   applied the renderer's baseline rule to a Konva `Text` node, which places its `y` differently
   (`(ascent − descent) / 2 + lineHeight / 2` below it, `textBaseline = "alphabetic"`).
   `editor/canvas/fonts.ts` now replicates Konva's own rule and font shorthand — details and numbers in
   `docs/research/render-parity.md`. The font metrics from `GET /fonts` are no longer needed by the canvas
   (the endpoint keeps them; the caption editor of Phase 6 will want the catalogue anyway).
3. *The Settings default style/layout were ignored* by the "Create artworks" dialog, which hardcoded
   Gallery recessed + Single. It now follows `GET /artwork-defaults` (the user's pick still wins; the
   defaults are derived during render, not copied into state when the query answers).

**Client vs server parity (Phase 5 AC)**: measured in the page on three artworks — MAE **1.05 / 1.22 / 1.52**
per channel (max 52 / 59 / 169, on antialiased edges and glyph stems), caption ink box within one canvas
pixel of the server's. Table and method: `docs/research/render-parity.md`.

**Also verified in the browser**: undo/redo (`Ctrl+Z` / `Ctrl+Shift+Z`) across an alternative being applied;
the alternatives panel (an upscaled slot offers *keep framing / shrink the photo / fit in the mat* with
previews, and applying one switches the lock and re-places the slot: 140 % → native 100 %); the colour
popover (curated presets, photo palette with dominant/muted entries, saving a swatch → `POST /swatches`);
the TV preview (fullscreen, bezel, `Escape` closes only the preview); "validate & next" through the draft
queue (progress counts down, the next draft opens); Inbox `$mod+a` → `n` → create → straight into the review
queue with the artwork built from the default style (Linen after changing it in Settings).

**Not verified**: the 40-photo keyboard-only run of the AC was done on a 11-draft queue, not 40; captions are
still read-only (Phase 6); free-form slot move/resize/rotate, multi-slot snapping and equal-gap guides are
Phase 6 as planned.

## Post-Phase-5 feedback round (2026-09-19)

Six items from the user's `remarks.md`, all driven in a real browser against a copy of the library
(`/tmp/e2e`, backend :8799 + Vite :5199):

1. *Margins could not be reduced under `native`.* `fit_in_mat` only re-derived the crop when it **overflowed**
   the available area, so growing the margins shrank the photo for good: shrinking them back left a small crop
   in a wide mat. It now re-derives on every margin edit, both ways (§7.4). Measured: top margin 280 → 700 →
   280 on a 3072×4080 photo gives crop 1175×1560 → 858×1140 → 1175×1560, i.e. an exact round-trip.
2. *A typed margin did nothing.* The number field snapped typed values with the §7.5 tolerance of 8 *screen*
   px — tens of document px on a fitted stage — so `1` next to a `0` margin came back as `0`. Snapping is now
   for dragged values only, and `NumberField` keeps the typed text while focused instead of fighting the
   caret with the re-placed document value.
3. *`?` now closes the cheat sheet* as well as opening it (`toggleCheatSheet`).
4. *`Enter` confirms the "Create artworks" dialog.* Radix focused the first tabbable element — the close
   cross — so `Enter` cancelled; the dialog now focuses its submit button (`onOpenAutoFocus`).
5. *Photo zoom is now a visible control*, not only the wheel: a slider + number field in the Photo section,
   `1×` = the whole photo at the current crop ratio, up to `8×`. Checked: `2×` on a 3072 px wide photo gives a
   1536 px crop under `native` (margins follow) and `1.5×` a 2048 px crop under `no_upscale`.
6. *Mirrored margins*: `margins.mirror_x` / `mirror_y` keep left = right / top = bottom, both when a side is
   edited and when native linking redistributes the free space. Two toggles next to "link all sides".

Schema change (`mirror_x`, `mirror_y`, defaults `false`) ⇒ `make gen-api`; geometry change ⇒ Python + TS +
four new conformance cases (`margins mirrored`, `margins mirrored on one axis`, `fit in mat native grows the
crop back`, and the mirror arguments on every `margins_for_slot` / `alternatives` case).

### Bundle size (2026-09-19)

`make serve` warned that the single JS chunk passed 800 kB. Measured by attributing generated bytes through
the sourcemap: react-dom 203 kB, **konva 181 kB + react-reconciler 126 kB** (the latter pulled in by
`react-konva`), router-core 51, i18next 61, query-core 35, virtual-core 23, qrcode 22, hash-wasm 18, app code
~90.

Done now: `qrcode` (pairing dialog) and `hash-wasm` (upload hashing) are loaded on demand — 40 kB raw / 16 kB
gzip off **every** page, the phone upload page included; main chunk 1051 → 1011 kB raw, 334 → 318 kB gzip.
`chunkSizeWarningLimit` sits just above that, so the warning still trips when a new dependency lands.

**Not** done: making the editor route lazy, which is where the real ~315 kB is (konva + reconciler +
react-colorful). Over the LAN under immutable hashed names that weight costs a few milliseconds, and the split
needs a stale-chunk error boundary first: `build.emptyOutDir` deletes the old hashed files, so a tab opened
before a rebuild would 404 on entering the editor (`/assets` is `StaticFiles`, so it is a clean 404, not
`index.html`). Worth doing when Phase 6 grows the editor further.

## 2026-09-21 — Phase 6 (multi-photo compositions)

**Pure core (mirrored Python/TypeScript, 134 conformance cases, was 107)**: `domain/arrange.py` ↔
`editor/core/arrange.ts` (§7.7) — bounding box, align on six edges, distribute with equal gaps, same size,
and where a slot the user adds lands (`new_slot_size` / `new_slot_rect`, cascading off the slots already
there). `ratio_label` gained its TypeScript mirror. Snapping (client-only, §7.5) gained the **equal-gap**
candidates promised for this phase plus `snap_rect`, which snaps a dragged slot by its left edge, centre and
right edge at once; 22 behaviour tests in `tests/unit/test_arrange.py`.

**Editor**: slots panel (front-first list = the z-order, drag to reorder, add/remove, photo picker with
search, replace, swap, empty a slot, fit/fill), free-form move/resize/rotate on the canvas (eight handles and
a rotation knob drawn by `SelectionOverlay`, hit-tested by `canvas/hit.ts`; `Shift` snaps the angle to 15°,
`Alt` disables snapping), multi-selection by Shift-click with align/distribute/same size/copy decorations,
caption editing (panel for every property, double-click on the canvas for the text, drag to move), position
and size fields for manual slots, and the shortcuts `a` (add slot), `t` (caption), `[` / `]` (z-order),
`Delete`, `$mod+a` (select every slot); the arrow keys now nudge the selected slots (or the caption), and
still the crop under the crop tool.

**Bugs found while driving it**:
1. *A slot added with a freshly picked photo was built as an empty one* — the editor only knows the sizes of
   the photos already in the document, so the crop took the slot's shape instead of the photo's (and the lock
   fell back to `free`). `store.ensurePhotoSize` now fetches the size before the operation runs (invariant 13).
2. *"Same size" made slots bigger than the reference*: the constraint solver resizes with **cover** semantics,
   so a slot whose aspect differs from the reference grew past it. It now fits *inside* the reference box.
3. *Clicking one slot of a multi-selection did not collapse the selection onto it* (the selection is kept on
   mousedown so the group can be dragged); it now collapses on mouseup when the pointer never moved.
Also fixed on the way: captions rotated around their text box on the canvas instead of their anchor point,
where the renderer pivots (`docs/research/render-parity.md`) — invisible until captions became editable.

**Verified** (production build served by the backend on trusted localhost, against a copy of the dev library):
`make check` green (332 backend tests, 134 conformance cases, mypy strict, ESLint, tsc, i18n). In the browser:
adding a slot from the picker (placement switches to `manual`, 4:3 photo → 908×684 slot, lock `no_upscale`),
dragging it (snapped its right edge to the canvas centre), resizing by the SE handle (908×684 → 1217×916 with
the crop growing to the full 4080×3072 photo, aspect consistent), rotating by the knob (38.1°, lock kept),
Shift-click multi-selection ("3 slots selected"), distribute (gaps 517/518), align top, same size (a 3:4 slot
became 511×679 inside the 900×678 reference), copy decorations, z-order by button and by `]`, nudging with the
arrows (227 → 230) with undo/redo, swapping two photos (each re-cropped to its new slot), emptying and
re-filling a slot, adding a caption and editing it inline, dropping a photo from the picker onto the mat (a new
slot lands under the pointer), and **equal-gap snapping** (dragged 20 px short of the stop, landed exactly on
it; `Alt` moved the raw 35 px instead). The server rendered every state (`render.png` 200, 5 slots + captions).

**Tooling note**: the Chrome-extension harness could not drive the app at all this time — the page never goes
idle (the SSE stream), so `executeScript`/`--dump-dom`/`--virtual-time-budget` all time out. The session used a
throwaway CDP driver instead (headless `chromium --remote-debugging-port` + `Runtime.evaluate`), which works
well; two harness gotchas are now in AGENTS.md (dispatch mouse events on the `<canvas>`, give synthetic
`KeyboardEvent`s a `code`). Because that tooling is not dependable, browser verification is now written down as
a **soft** requirement (`docs/PLAN.md` §13.6 and DoD item 5): still the preferred evidence for UI work, but a
phase is no longer held back by it — what could not be driven is recorded here instead.

**Not done / follow-ups**: no marquee (rubber-band) selection — slots are picked by click and Shift-click; the
photo picker has search but no tag/date filters; a dropped photo may land partly outside the canvas (allowed by
the document, clipped at render); the editor route is still not lazy (the bundle note of 2026-09-19 stands, and
this phase added ~15 kB of editor code).

## 2026-09-21 — Phase 7 stage 1 (composition block, solver, recipe catalogue)

The parametric foundations of `docs/simple-editor.md`. **Nothing in the UI uses them yet** — this is
the layer stages 2–4 build on.

**The document** gained an optional `composition` block (`schema` stays 1, so no migration and every
existing document stays valid): recipe id, `balance`, `outer`/`gutter` per axis, `format`, `border`,
`caption`, `detached`. The catalogue checks — the recipe exists, its cell count matches the slots,
`balance` is in range — need the catalogue, so they live in `validate_references` and surface as
`unknown_recipe` / `recipe_slot_count` / `balance_out_of_range` / `balance_not_supported`. Two rules
are structural and rejected by the model itself: `format: "original"` needs exactly one slot, and a
ratio's terms are ≤ 1000. A **detached** block may hold any slot count — the slots are the truth then,
so an artwork hand-edited in Advanced mode still round-trips.

**The solver** (`domain/composition.py` ↔ `editor/core/composition.ts`, 186 conformance cases, all
agreeing first try) implements §3: `fill` as a weighted split with exact gutters, and ratio formats
through the bottom-up affine relation `w = α·h + β` on **footprints**, fitted and centred in the
available area, then walked top-down with float edges. Plus `block_area` (the caption band),
`block_margins` (what §3.7 writes back to `margins`) and `refit_crop` (§4.1, centre + zoom kept).

**The catalogue**: `assets/presets/recipes.json`, 17 recipes — 1 single, 4 pairs, 5 triples, 5 quads,
one each for 5 and 6, seven of them declaring a `balance` range. Not a template: no DB table, no
seeding, stable ids, served read-only by `GET /api/v1/recipes` (admin) and read straight off disk by
the conformance script, so the client and both solvers share one source. Names are in i18n under
`recipes.*`.

**Two spec bugs found while implementing it**, both now fixed in `docs/simple-editor.md`:
1. *The worked example was off by one*: it rounded the block's float **height** (1591) where the
   solver rounds **edges** (284.4 … 1875.6 → 284 … 1876, so 1592). The same reason makes a cell's
   aspect exact only to `1 + r` px of width, not the 1 px §8 promised — the test asserts the honest
   bound now.
2. *§3.5 said an `auto` cell takes "the photo's own aspect"*, which is exactly what the `original`
   format already means — so every ratio chip would have been a no-op for a single photo. `auto` now
   means the format turned the photo's way (portrait photo + `3:2` → a 2:3 cell), which is what §3.1's
   "the photo's own orientation" says.

Also decided while implementing: the over-constrained recovery of §3.6 is a **fixed ladder** (gutters
scaled ×10/10…0/10, then `outer`) rather than the bisection the spec suggested — the two solvers must
agree bit for bit, and eleven divisions by ten give identical doubles in Python and JavaScript.

**Verified**: `make check` green — 674 backend tests (was 332), 320 conformance cases (was 134), mypy
strict, ESLint, tsc, i18n. 152 of the new tests are behaviour tests in `tests/unit/test_composition.py`
(tiling, aspects, centring, balance monotonicity, borders, no overlap, totality at every slider
extreme, crop preservation); 4 are API tests covering the catalogue endpoint and the composition
problem codes. **Not driven in a browser** (§13.6): stage 1 ships no UI, so there is nothing to drive —
the endpoint is covered by an API test and the solver by conformance on both sides.

**Not done** (stages 2–4): the server does not re-solve on save, `POST /artworks` still takes a
`layout_id`, and there is no Simple panel, mode switch or `Re-apply layout`. `settings.artwork_defaults`
still names a style + layout (Phase 8, §10).

## 2026-09-22 — Phase 7 stage 2 (server authority)

The composition is now the **source of truth** for the geometry, not a decoration of the document.

**The write-back** (`docs/simple-editor.md` §3.7) is one pure, mirrored function —
`composition.apply` ↔ `applyComposition` — and it is the only implementation of that table: rects
from the cells, rotation zeroed, crops re-fitted around their previous centre at their previous
zoom (§4.1), `crop_ratio` from the cell, `no_upscale` downgraded to `free` when the framing would
upscale, the border as a band, `margins` = the block's footprint insets, `placement = manual`, and
the one derived caption. 17 conformance cases run it **document in, document out**, so Python and
TypeScript agree field by field rather than on rects alone — they did, first try.

**On save**: `validated()` parses, checks the library references, then re-solves, so `PUT document`
and snapshot restore share one authority. A client bug can no longer persist a wrong rect, and an
API test proves it: half-size rects at the origin come back as the solved ones, with the reframe
intact and the lock downgraded to `free`. A **detached** block is stored verbatim (§5).

**On create**: `POST /artworks` takes `composition: {recipe?, format?, balance?, outer?, gutter?,
border?, caption?}`, all optional — and it is now the **default**: without a `layout_id` the photos
get the first recipe for their count, `original` for one photo and `fill` above. An explicit
`layout_id` still builds a Phase 6 document with no block, which is what the current create dialog
and the Advanced editor use. New codes: `unknown_recipe`, `no_recipe`, `recipe_slot_count`,
`layout_and_composition`.

**Three decisions the spec did not pin**, now written into §3.7: the caption baseline is
`1.05 × size` below its line's top (pure number, no font metrics, computed from the nominal `outer`
so a relaxed block does not drag the text with it); the composition owns the caption's *text and
side* while the document owns its *typography* (so a restyled caption survives a re-solve); and a
blank caption text derives no caption at all (the document model requires `text` ≥ 1 char).

**One bug found by reasoning about `aspect_consistent`**: `refit_crop` scaled the largest crop's
width *and* height by the zoom, rounding two independent sides. The error budget of
`aspect_consistent` is exactly `(rect.w + rect.h)(1 + k)/2` — the two roundings can reach it, so
the server could have rejected its own output. The height now comes from the width and the ratio;
the four existing fixtures were unchanged by the fix (verified by hand), and a parametrized test
re-validates an applied document for every recipe × format.

**Verified**: `make check` green — 817 backend tests (was 695), 337 conformance cases (was 320),
mypy strict, ESLint, tsc, i18n. **Not driven in a browser** (§13.6): stage 2 ships no UI. The
render path is covered anyway, since every artwork the API tests create now goes through the
composition path and renders.

**Known gap, closed by stage 4**: the Advanced editor ignores the document the server returns, so a
free-form slot move on a *composition-backed* artwork would be silently re-solved away. Nothing
reaches that state today — the create dialog always sends `layout_id`, so every artwork the UI
makes has no block — but stage 4's `detached` flag (set by the first free-form edit) is what makes
it safe, and it must land before the Simple/Advanced switch does.

## 2026-09-22 — Phase 7 stage 3 (the Simple panel)

The parametric editor is now something you can use: pick a layout, move two sliders.

**The panel** (`editor/panels/SimplePanel.tsx`) follows §6.2 top to bottom — Layout, Balance,
Format, Margins, Photos, Background, Border, Caption. Every control writes into the `composition`
block and lets `applyComposition` re-derive the geometry, so the editor previews exactly what the
server will store (the same mirrored function, stage 2). The layout picker draws its schemas by
**running the solver** at thumbnail parameters (§6.3): a new recipe in `recipes.json` appears with a
correct schema for free, and a thumbnail can never drift from the real layout.

**Slider bounds** are a bisection on `solve_strict` — a new mirrored primitive: one attempt, no
relaxation ladder. Bisecting on `solve` would have been quietly wrong, because the ladder answers
"roomy" for an over-constrained value by laying the block out with *other* gutters. The bisection
itself is client-only (`editor/core/bounds.ts`, like `snapping.ts`): the server needs no such rule,
its solver is total.

**Three rules the panel forced into the open**, now in §6.2 of the spec:
1. *Attaching a block must not eat a caption.* A hand-built artwork shows the picker alone; picking
   a layout attaches a block, which from then on owns the captions (§3.7) — so an existing caption's
   text moves into the block instead of being deleted on the next solve.
2. *Reframing turns the lock off.* Under `no_upscale` the constraint solver shrinks the **slot** as
   soon as the crop gets smaller than it (§7.3), which fights the cell. A reframe inside a cell now
   zooms with the lock off and restores §3.7's lock afterwards (`relock`), so the rect belongs to
   the composition at all times.
3. *Balance is clamped when the recipe changes.* The declared ranges differ between recipes
   (`hero-left` 0.40–0.75, `hero-right` 0.25–0.60), so carrying the value over unclamped builds a
   document the server rejects with `balance_out_of_range`. Found by reading the catalogue after
   the browser run had already set 0.7 on a hero-left; `balanceFor` clamps, and the browser now
   shows 0.75 → 60 % on the switch, stored without a 422.
4. *The photo count keeps the block valid.* A slot added or removed in the Advanced editor re-picks
   the recipe (§4.4); past the catalogue (7 photos and up) the block detaches, which is also what
   stops the server rejecting the save with `recipe_slot_count`.

**Verified in a real browser** (§13.6, headless Chromium over CDP against the production build on
trusted localhost — the harness the AGENTS.md gotcha describes):

- a 3-photo artwork created by `POST /artworks` with no layout id comes back parametric
  (`three-row`, `fill`);
- picking *Hero left* shows Balance at the recipe's 62 % default; switching the format to `3:2`
  replaces the slider with the "the format sets the proportions" hint (§4.3);
- dragging *Outer* to 320 shows `→ 373` next to it — and 373 px is exactly the margin the **server**
  stored after re-solving, which is the phase's AC: *the server-stored rects equal the ones the
  editor previewed*. The cells come out 3:2 to the rounding bound (2120×1414, 1000×667);
- a hand-built artwork shows "Pick a layout…" and attaches a block when one is picked, carrying its
  caption into it (`y = 2018`, the derived baseline);
- typing a caption switches it on *below*, dragging photo 1 onto photo 2 swaps them and re-frames
  both crops, zooming cell 2 to 3× changes only the crop (the rect stays the cell), and a 24 px
  border lands as a band on every slot.

**Verified**: `make check` green — 822 backend tests, 339 conformance cases, mypy strict, ESLint,
tsc, i18n.

**Not done** (stage 4): there is no `[Simple] [Advanced ᴮᴱᵀᴬ]` switch yet — the Simple panel sits on
top of the Advanced stack in the design tab, which is how it stays reachable for a hand-built
artwork. Free-form edits still do not set `detached`, so the gap flagged in the stage-2 note is
still open: a slot moved by hand on a composition-backed artwork is re-solved away on save. Stage 4
closes it, together with the banner and **Re-apply layout**.

## 2026-09-22 — Phase 7 stage 4 (the mode switch and `detached`) — **phase complete**

The editor now has two modes and a safe door between them.

**The switch** sits in the header (`[Simple] [Advanced ᴮᴱᵀᴬ]`, Simple default for every artwork,
registered as a palette command with no shortcut). Advanced shows the Phase 6 stack under the
warning strip. The canvas is shared but not identical: in Simple the stage runs the **crop**
gesture, so dragging reframes a photo inside its fixed cell and the transform handles are never
offered — the select/crop toggle is an Advanced control and is hidden in Simple.

**Detaching** (§5) is the interesting half. The rule the code applies is mechanical: **an edit
detaches exactly when `apply` would overwrite it**. That turned a vague list ("rotation, free
placement, per-slot decorations") into 20-odd call sites with an answer each:

- *detach*: move / resize / rotate a slot, align / distribute / same-size, fit / fill to photo,
  bands, quality lock, crop ratio, margins, placement, alternatives, a caption's position, adding
  or removing a caption;
- *do not detach*: the shadow, the mat, a caption's typography — `apply` leaves them alone, so they
  survive the next solve and must not cost the user their layout link;
- *re-solve instead*: orienting a photo (90°/flip changes the aspect an `original`/`auto` cell
  follows), re-ordering slots (the array order **is** the cell assignment, so it reads as a swap)
  and adding or removing a photo (§4.4).

A caption's text was the one field both modes write: typed on the canvas it now goes into
`composition.caption.text`, not just onto the caption, or the next solve would take it back.

**Re-apply layout** is one `store.edit()` patch behind a confirm dialog — which is exactly what
makes it safe to offer as a button: `⌘Z` puts the hand-made geometry back.

**Verified in a real browser** (CDP, production build on trusted localhost): Simple is the default
and shows the Layout panel; Advanced shows the beta strip and the old stack; an arrow-key nudge in
Advanced detaches; back in Simple the banner replaces the controls; Re-apply asks for confirmation
and restores the solved cells (`detached: false`, rects back to 120/2382 on the server); one `⌘Z`
brings the banner *and* the hand-made geometry back (`detached: true`, `x = 122` — the two nudges),
all of it round-tripping through the server. A shadow change in Advanced leaves `detached` false.

**A process note worth keeping**: the header switch silently did not land the first time — the
scripted replacement missed because prettier had reformatted the block, and that particular
substitution had no assertion. The browser run caught it immediately (the header had no switch at
all). Script every edit with an assertion, and never take "the checks are green" as evidence that a
UI change is actually *there*.

**Verified**: `make check` green — 822 backend tests, 339 conformance cases, mypy strict, ESLint,
tsc, i18n. Phase 7 is complete; `settings.artwork_defaults` still names a style + layout rather
than a style + recipe + format (§10, left to Phase 8 with the rest of the template work), and the
create dialog still sends a `layout_id`, so artworks made from the Photos page are hand-built until
the user picks a layout in the editor. Both are Phase 8's to change.

## 2026-09-22 — Phase 7 feedback round (`remarks.md`)

Seven items came back from using the Simple editor. One was a false alarm (the "asymmetric" bottom
margin was the caption band, which the user diagnosed themselves); the other six are treated.

**#7 — the zoom bug, and it was a real one.** `zoom_crop` grew the crop by the factor and then
clamped **width and height independently** against the photo. Scrolling out past the whole photo
therefore reshaped the crop — and since a crop whose aspect no longer matches its slot makes
`resize_crop` resize the *slot* to match, the cell visibly changed shape ("its frame is reduced or
extended"). Under `no_upscale` the slot followed the crop as well. The fix bounds the **factor** so
the crop stays inside the photo *with its aspect*, in both languages, with two conformance cases.
Verified in the browser: 40 wheel-outs now stop at exactly 1.00×, the rect unchanged and the crop
still at the cell's 0.7497.

**#3 — `4:3` and `3:4` rendered the same.** They did: `format_ratio` returned the *landscape form*
and the recipe's per-cell `landscape`/`portrait` annotation decided the orientation, which made
half the chips inert. A format now carries its orientation — the cells take the ratio as written —
and only `auto` (the 1-cell recipe) still turns it the photo's way. The panel gained a
**[Landscape] [Portrait]** toggle next to the chips. The recipes' cell kinds are inert as a result;
§10 notes they could be dropped.

**#4 — per-photo formats.** `composition.cell_formats` overrides the block's format cell by cell
(`null` inherits, `original` = that photo's own aspect, never `fill`). The solver already computed
a per-leaf aspect, so this was a parameter rather than a mechanism; the panel exposes it as a
"This photo" dropdown on the selected cell. A 1+2 with a `3:2` hero over two squares now works.

**#6 — creating from a multi-selection.** Selecting three photos created *three* artworks, because
the dialog defaulted to the one-slot "Single" layout and chunked the selection by slot count. It
now offers "One artwork with the 3 photos" (default) versus "One artwork per photo", and the
together path shows the recipe picker — so the dialog creates parametric artworks and the layout
dropdown is gone. Phase 8's "the create dialog still sends a layout_id" note is settled early.

**#2 — the zoom needed its tier.** The quality badge now sits under the zoom slider with a **Native
100%** button next to it. The first implementation drove the existing zoom action and landed a
pixel off — the badge read "Downscaled 100 %", which is exactly the lie the badge must never tell —
so the action sets the crop to the cell's size directly (`setNativeFraming`). It reads **Native
100%** and the stored crop equals the rect.

**#5 — swapping was undiscoverable.** Drag-onto-another was the only way and nothing said so. There
is now a hint line, a "cell 2 of 3" position row and **◀ ▶** buttons that swap with the neighbour.

**Verified**: `make check` green — 832 backend tests, 344 conformance cases. Everything above was
driven in a real browser (CDP): the create dialog from the Photos grid through to a stored 3-photo
parametric artwork, then the format orientation, a per-cell `1:1`, the swap arrows, Native 100% and
the wheel zoom-out, each checked against the **saved document** rather than the screen.

## 2026-09-23 — Phase 7 feedback, second round (`remarks.md`)

Ten items. Nine were actionable, one was a question answered in the reply (#7, below).

**#2 — the zoom bug was still there, and worse than it looked.** The previous round bounded
zooming *out*; nothing bounded zooming *in*. The wheel multiplied the crop by `1/1.06` without
limit, so a few seconds of scrolling shrank it to a handful of pixels, where two independently
rounded sides no longer describe the rect's aspect — and `resize_crop`'s answer to an inconsistent
crop is to resize the **slot**. Reproduced exactly: 120 wheel steps in took a 1800×1200 rect with a
3000×2000 crop to a 959×853 rect with an **8×8** crop, and zooming back out was stuck for ever
(`round_half_even(8 × 1.06) == 8`). Two fixes, both needed:

- `zoom_crop` (mirrored) now derives the height from the width and the **rect's** aspect, bounds
  the result by `largest_crop(source, that aspect)`, and always moves at least one pixel. The rect
  is the only reference that does not move: re-reading the aspect off the rounded crop every step
  drifts just as badly. Round trip now exact — all the way in to 1×1 and back out to the whole
  photo, with the rect untouched (four shapes checked, two conformance cases added).
- the editor routes the **wheel** through the same bounded 1×–8× scale as the slider
  (`zoomCrop` → `setPhotoZoom`), so scrolling cannot reach the pathological region at all.

**#1 — the upload overlay hijacked cell swaps.** Dragging a photo chip lit up "Drop photos or a
folder" across the window. A chip is an `<img>`, and Chrome offers such a drag to the page as a
file, so `hasFiles` was right about the `types` and wrong about the intent. Internal drags now
stamp themselves (`shared/dnd.ts`) and the global zone ignores a stamped drag — which also fixes
the same flash when dragging from the photo picker onto the canvas.

**#3 — clicking a photo on the canvas selects it.** In Simple the stage is always in crop mode, and
crop mode went straight to the gesture on the *primary* slot without hit-testing. It now selects
the photo under the pointer first, in both modes, so the canvas is a way to choose which photo the
panel edits and the chips are left to do the swapping.

**#4 — per-cell format, same control as the artwork's.** One `FormatChoice` component now serves
both, the per-cell one with an extra `Same as layout` chip: they are the same setting at two
scales, and chips-versus-dropdown made them read as unrelated.

**#5 — `original` at any photo count.** The document model rejected it above one slot. The rule was
conservative, not structural: `_leaf_aspect` has always given each leaf its own photo's aspect, and
a 3- and 4-cell solve lands each cell on its photo's ratio within the §3.4 tolerance. The rule is
gone (with the two client-side `original → fill` downgrades it forced), the chip is always offered.

**#6 — caption size is a slider in Simple.** No schema change: `apply` reads the typography back
off the document (§3.7), so the size round-trips on its own. It re-solves rather than detaches —
the band the solver reserves is a function of the size (§3.3).

**#8 — the frame style is changeable in the editor.** A dropdown in Background applies a style's
mat, shadow, border and caption typography, deliberately *not* its margins: under a block the
margins are derived, and the point is to re-dress the artwork without disturbing its layout. The
band becomes `composition.border` while a block is attached, since that is what owns `bands`.

**#9 — `P` toggles the TV preview** (it only ever opened it).

**#10 — a single photo hides what is about choosing a cell**: the layout picker (there is exactly
one 1-cell recipe), the gap sliders, the photo chips, the swap arrows and the per-cell format.

**#7 — the answer, no code.** A dropdown of "best quality" downscales (50 %, 25 %) is not worth
building: see the reply. The short version is that the renderer already resamples with a proper
filter, so there is no aliasing to dodge, and the tier the badge reports depends on the *cell* size
rather than on landing at a tidy fraction.

**Verified**: `make check` green — 834 backend tests, 346 conformance cases, mypy strict, ESLint,
tsc, i18n. Driven in a real browser (headless Chromium over CDP against the production build on
trusted localhost), each result read back from the **saved document** rather than off the screen:

- #2 — 200 wheel-ins then 300 wheel-outs on a 3-photo artwork: the crop stops at the 8× bound
  (384×510 of a 3071×4080 photo) and comes back to the whole photo, with the rect at 1427×1896
  before, during and after. The same sequence used to end at an 8×8 crop, a resized rect and no
  way back.
- #1 — a synthetic drag carrying a `File` raises the upload overlay; the same drag with our
  `text/x-the-frame-slot` stamp does not. Checked on both `/photos` and the editor route.
- #3 — clicking each of the three cells on the canvas moves the panel's "cell *n* of 3".
- #4/#5 — the format chips write `format: "3:2"` and `cell_formats: ["1:1"]`, and the solver
  answers with a 722×722 cell next to two 1083×722 ones; `original` on three photos gives each
  cell its own photo's aspect (1.327, 1.327, 0.752).
- #6 — the size slider takes the caption from 48 to 140 px and the margins re-solve around the
  bigger band (bottom 772 → 841).
- #8 — picking Linen writes its mat, a 12 px `#F6F2EA` border and an inner shadow.
- #9 — `P` opens the preview and closes it again.
- #10 — a one-photo artwork's panel has no Layout section, no Gap, no cell chips, no swap arrows
  and no per-cell format; a three-photo one has all of them.

Not driven: the native HTML drag that swaps two cells (a synthetic `dragstart`/`drop` pair does not
reproduce a real mouse drag — the previous round checked it, and this change only adds a `setData`
call to the existing handler).
