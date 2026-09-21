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

**Known limits / follow-ups**: collections can only be listed (creation in Phase 8), so the phone collection
picker stays empty; trashed artworks cannot be restored before Phase 8; no ESLint rule for literal JSX strings
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
`KeyboardEvent`s a `code`).

**Not done / follow-ups**: no marquee (rubber-band) selection — slots are picked by click and Shift-click; the
photo picker has search but no tag/date filters; a dropped photo may land partly outside the canvas (allowed by
the document, clipped at render); the editor route is still not lazy (the bundle note of 2026-09-19 stands, and
this phase added ~15 kB of editor code).
